import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from app.adapters.base import RetailerAdapter, RetailerBlockedError, RetailerDefinition
from app.db import init_db
from app.schemas import Offer, SearchRequest
from app.search import SearchManager


class FakeAdapter(RetailerAdapter):
    def __init__(self, id="fake", failure=False, delay=0):
        self.definition = RetailerDefinition(id, id.title(), "official", "https://example.com")
        self.failure, self.delay = failure, delay
    async def search(self, request, *, bypass_cache=False):
        await asyncio.sleep(self.delay)
        if self.failure: raise RuntimeError("blocked by retailer")
        return [Offer(retailer=self.definition.name, product_name="Nike Air Jordan 1 Low", brand="Nike", requested_uk_size=request.uk_size, size_available=True, listed_price_paise=900000, shipping_paise=0, effective_price_paise=900000, product_url="https://example.com/shoe", match_score=0, last_checked=datetime.now(timezone.utc))]
    def parse(self, payload, request, source_url): return []


async def wait_complete(manager, search_id):
    for _ in range(100):
        result = manager.get(search_id)
        if result.state == "complete": return result
        await asyncio.sleep(.01)
    raise AssertionError("search did not complete")


async def test_partial_failure_and_sse_ordering():
    init_db()
    manager = SearchManager([FakeAdapter("good"), FakeAdapter("bad", failure=True)])
    created = await manager.create(SearchRequest(query="Jordan 1 Low", brand="Nike", uk_size="8"), bypass_cache=True)
    result = await wait_complete(manager, str(created.id))
    assert len(result.offers) == 1
    assert any(status.state == "error" for status in result.retailers)
    events = [event["event"] async for event in manager.events(str(created.id))]
    assert events[0] == "search_started"
    assert events[-1] == "search_complete"
    assert "retailer_error" in events

async def test_cache_and_refresh_bypass():
    init_db()
    adapter = FakeAdapter("cachefake")
    manager = SearchManager([adapter])
    request = SearchRequest(query="Jordan 1 Cache Test", brand="Nike", uk_size="9")
    first = await manager.create(request, bypass_cache=True)
    await wait_complete(manager, str(first.id))
    second = await manager.create(request.model_copy())
    assert second.cached and second.state == "complete"
    refreshed = await manager.create(request.model_copy(), bypass_cache=True)
    assert not refreshed.cached

async def test_retailer_timeout_is_partial_failure():
    manager = SearchManager([FakeAdapter("fast"), FakeAdapter("slow", delay=.3)])
    created = await manager.create(SearchRequest(query="Air Jordan 1 Low", brand="Nike", uk_size="10"), bypass_cache=True)
    result = await wait_complete(manager, str(created.id))
    assert len(result.offers) == 1
    assert next(status for status in result.retailers if status.retailer == "Slow").state == "timeout"


async def test_blocked_retailer_is_reported_as_not_checked():
    class BlockedAdapter(FakeAdapter):
        async def search(self, request, *, bypass_cache=False):
            raise RetailerBlockedError(
                "Retailer is cooling down", reason_code="host_cooldown", circuit_state="open"
            )

    manager = SearchManager([BlockedAdapter("blocked")])
    created = await manager.create(SearchRequest(query="Speedcat OG", uk_size="9"), bypass_cache=True)
    result = await wait_complete(manager, str(created.id))
    status = result.retailers[0]
    assert status.state == "blocked"
    assert status.reason_code == "host_cooldown"
    assert status.circuit_state == "open"
    assert status.offer_count == 0


async def test_partial_result_is_reported_as_partial_state():
    from app.adapters.puma import PartialResultError
    
    init_db()
    
    class PartialAdapter(FakeAdapter):
        async def search(self, request, *, bypass_cache=False):
            offers = await super().search(request, bypass_cache=bypass_cache)
            raise PartialResultError("1 of 3 products failed", offers=offers, reason_code="partial_results")
    
    manager = SearchManager([PartialAdapter("partial_retailer")])
    created = await manager.create(SearchRequest(query="Air Jordan 1 Low", uk_size="8"), bypass_cache=True)
    result = await wait_complete(manager, str(created.id))
    assert len(result.offers) == 1  # got the partial offers
    status = result.retailers[0]
    assert status.state == "partial"
    assert status.offer_count == 1
    assert status.reason_code == "partial_results"
