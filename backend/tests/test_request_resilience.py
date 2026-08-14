import httpx
import pytest

from app.adapters.base import AdapterError, RateLimitedClient, RetailerBlockedError


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


async def test_retry_jitter_retry_after_and_success_reset():
    fake = FakeTime()
    statuses = iter([
        httpx.Response(500),
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, text="catalog"),
    ])
    transport = httpx.MockTransport(lambda request: next(statuses))
    client = RateLimitedClient(transport=transport, clock=fake.clock, sleep=fake.sleep, random_value=lambda: .5, min_interval=0)
    response = await client.get("https://shop.example/search")
    assert response.status_code == 200
    assert fake.sleeps == pytest.approx([.2, 2])
    assert client.state_for("shop.example").failures == 0
    assert client.state_for("shop.example").cooldown_until == 0


async def test_403_does_not_retry_and_opens_ten_minute_cooldown():
    fake = FakeTime()
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(403)
    client = RateLimitedClient(transport=httpx.MockTransport(handler), clock=fake.clock, sleep=fake.sleep, min_interval=0)
    with pytest.raises(RetailerBlockedError) as blocked:
        await client.get("https://blocked.example/search")
    assert calls == 1
    assert blocked.value.reason_code == "http_403"
    assert blocked.value.retry_count == 0
    with pytest.raises(RetailerBlockedError) as cooldown:
        await client.get("https://blocked.example/search")
    assert cooldown.value.reason_code == "host_cooldown"
    assert calls == 1


async def test_exhausted_429_cooldown_and_recovery():
    fake = FakeTime()
    status = 429
    def handler(request):
        return httpx.Response(status, request=request)
    client = RateLimitedClient(transport=httpx.MockTransport(handler), clock=fake.clock, sleep=fake.sleep, random_value=lambda: 0, min_interval=0)
    with pytest.raises(AdapterError) as exhausted:
        await client.get("https://busy.example/search")
    assert exhausted.value.retry_count == 2
    assert client.state_for("busy.example").cooldown_until >= fake.now + 120
    with pytest.raises(RetailerBlockedError):
        await client.get("https://busy.example/search")
    fake.now += 121
    status = 200
    assert (await client.get("https://busy.example/search")).status_code == 200


async def test_network_failures_retry_three_times_and_open_cooldown():
    fake = FakeTime()
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)
    client = RateLimitedClient(transport=httpx.MockTransport(handler), clock=fake.clock, sleep=fake.sleep, random_value=lambda: 0, min_interval=0)
    with pytest.raises(AdapterError) as failure:
        await client.get("https://offline.example/search")
    assert calls == 3
    assert failure.value.reason_code == "network_failure"
    assert client.state_for("offline.example").cooldown_until >= fake.now + 60


async def test_repeated_403_doubles_cooldown():
    fake = FakeTime()
    def handler(request):
        return httpx.Response(403)
    client = RateLimitedClient(transport=httpx.MockTransport(handler), clock=fake.clock, sleep=fake.sleep, min_interval=0)
    
    # First 403 → 600s cooldown
    with pytest.raises(RetailerBlockedError):
        await client.get("https://blocked2.example/search")
    state = client.state_for("blocked2.example")
    assert state.failures == 1
    assert abs(state.cooldown_until - (fake.now + 600)) < 1
    
    # Advance past cooldown to trigger half-open probe
    fake.now += 601
    
    # Half-open probe → another 403 → doubled cooldown (1200s from now)
    with pytest.raises(RetailerBlockedError):
        await client.get("https://blocked2.example/search")
    state = client.state_for("blocked2.example")
    assert state.failures == 2
    assert abs(state.cooldown_until - (fake.now + 1200)) < 2


async def test_half_open_success_closes_circuit():
    fake = FakeTime()
    attempt = 0
    def handler(request):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            return httpx.Response(403)
        return httpx.Response(200, text="ok")
    client = RateLimitedClient(transport=httpx.MockTransport(handler), clock=fake.clock, sleep=fake.sleep, min_interval=0)
    
    with pytest.raises(RetailerBlockedError):
        await client.get("https://halfopen.example/search")
    
    fake.now += 601  # past cooldown
    response = await client.get("https://halfopen.example/search")
    assert response.status_code == 200
    state = client.state_for("halfopen.example")
    assert state.failures == 0
    assert state.cooldown_until == 0
