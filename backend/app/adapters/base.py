from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import random
import time
from typing import Awaitable, Callable
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from ..config import settings
from ..schemas import Offer, SearchRequest


class AdapterError(RuntimeError):
    """A safe, user-displayable collector failure (never includes a response body)."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "adapter_unavailable",
        http_status: int | None = None,
        retry_count: int = 0,
        circuit_state: str = "closed",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.http_status = http_status
        self.retry_count = retry_count
        self.circuit_state = circuit_state


class RetailerBlockedError(AdapterError):
    """The retailer was not checked because access is blocked or cooling down."""


class PartialResultError(AdapterError):
    """A bounded collector retained valid offers while some details failed."""

    def __init__(self, message: str, offers: list[Offer], **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.offers = offers


CHALLENGE_MARKERS = (
    "access denied", "captcha", "cf-chl-", "cloudflare ray id",
    "verify you are human", "unusual traffic", "akamai reference",
    "unable to give you access", "security issue was automatically identified",
    "reference error:",
)


def detect_challenge(payload: str) -> bool:
    """Distinguish a blocked storefront from a legitimate empty result page."""
    raw = payload[:500_000].lower()
    if "cf-chl-" in raw or "cloudflare ray id" in raw:
        return True
    visible = BeautifulSoup(payload[:500_000], "html.parser").get_text(" ", strip=True).lower()
    return any(marker in visible for marker in CHALLENGE_MARKERS if marker not in {"cf-chl-", "cloudflare ray id"})


@dataclass(frozen=True)
class RetailerDefinition:
    id: str
    name: str
    kind: str
    search_url: str
    enabled: bool = True
    uses_browser: bool = False
    adapter_type: str | None = None  # "shopify", "browser", "structured", "puma", "converse", "brandman", "vegnonveg"
    collection_mode: str = "automatic"


class RetailerAdapter(ABC):
    definition: RetailerDefinition

    @abstractmethod
    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]: ...

    @abstractmethod
    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]: ...


@dataclass
class HostState:
    failures: int = 0
    cooldown_until: float = 0
    reason_code: str | None = None
    half_open: bool = False


class RateLimitedClient:
    """Shared bounded retry and host-cooldown policy for first-party requests."""

    def __init__(
        self,
        max_concurrency: int = 5,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        base_delay: float = 0.4,
        min_interval: float = 0.35,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._last_request: dict[str, float] = {}
        self._states: dict[str, HostState] = {}
        self._transport = transport
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._random = random_value
        self._base_delay = base_delay
        self._min_interval = min_interval
        self._loaded = False

    def state_for(self, host: str) -> HostState:
        return self._states.setdefault(host, HostState())

    def _persist_state(self, host: str, state: HostState) -> None:
        try:
            from ..db import SessionLocal, SourceHealthRow, utcnow
            with SessionLocal.begin() as db:
                row = db.get(SourceHealthRow, host)
                if row is None:
                    row = SourceHealthRow(host=host)
                    db.add(row)
                row.failures = state.failures
                remaining = max(0.0, state.cooldown_until - self._clock())
                row.cooldown_until = self._wall_clock() + timedelta(seconds=remaining) if remaining else None
                row.reason_code = state.reason_code
                row.updated_at = utcnow()
        except Exception:
            pass  # persistence is best-effort; don't let DB errors break requests

    def _load_persisted_states(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            from ..db import SessionLocal, SourceHealthRow
            with SessionLocal() as db:
                rows = db.query(SourceHealthRow).all()
                for row in rows:
                    state = self._states.setdefault(row.host, HostState())
                    state.failures = row.failures
                    expiry = row.cooldown_until
                    if expiry is not None:
                        if expiry.tzinfo is None:
                            expiry = expiry.replace(tzinfo=timezone.utc)
                        remaining = max(0.0, (expiry - self._wall_clock()).total_seconds())
                        state.cooldown_until = self._clock() + remaining if remaining else 0
                    state.reason_code = row.reason_code
        except Exception:
            pass

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
        return await self._request("GET", url, headers=headers)

    async def post_json(
        self, url: str, payload: dict, *, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        return await self._request("POST", url, json=payload, headers=headers)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        self._load_persisted_states()
        host = httpx.URL(url).host or "unknown"
        state = self.state_for(host)
        now = self._clock()
        
        # Check for active cooldown
        if state.cooldown_until > now:
            remaining = max(1, int(state.cooldown_until - now + 0.999))
            raise RetailerBlockedError(
                f"Retailer is cooling down after {state.reason_code or 'a failed request'} ({remaining}s remaining)",
                reason_code="host_cooldown", circuit_state="open",
            )
        
        # Half-open probe: was previously in cooldown, now trying again
        was_in_cooldown = state.cooldown_until > 0 and state.failures > 0
        if was_in_cooldown:
            state.half_open = True

        async with self._semaphore:
            interval = max(0.0, self._min_interval - (self._clock() - self._last_request.get(host, 0)))
            if interval:
                await self._sleep(interval + self._random() * 0.1)
            request_headers = {
                "User-Agent": settings.user_agent,
                "Accept-Language": "en-IN,en;q=0.8",
                **(kwargs.pop("headers", None) or {}),
            }
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.retailer_timeout_seconds),
                follow_redirects=True,
                headers=request_headers,
                transport=self._transport,
            ) as client:
                last_network_error: Exception | None = None
                last_status: int | None = None
                for attempt in range(3):
                    try:
                        response = await client.request(method, url, **kwargs)
                        self._last_request[host] = self._clock()
                    except (httpx.TimeoutException, httpx.NetworkError) as exc:
                        last_network_error = exc
                        if attempt < 2:
                            await self._sleep(self._jitter(attempt))
                            continue
                        self._open(host, 60, "network_failure")
                        raise AdapterError(
                            f"Retailer request failed ({type(exc).__name__})",
                            reason_code="network_failure", retry_count=attempt,
                            circuit_state="open",
                        ) from exc

                    status = response.status_code
                    last_status = status
                    if status in {401, 403}:
                        self._open(host, 600, f"http_{status}")
                        raise RetailerBlockedError(
                            "Retailer blocked the automated request",
                            reason_code=f"http_{status}", http_status=status,
                            retry_count=attempt, circuit_state="open",
                        )
                    if status == 404:
                        raise AdapterError(
                            "Retailer page was not found",
                            reason_code="http_404", http_status=404, retry_count=attempt,
                        )
                    if status in {408, 429} or 500 <= status <= 599:
                        if attempt < 2:
                            await self._sleep(max(self._jitter(attempt), self._retry_after(response)))
                            continue
                        seconds = 120 if status == 429 else 60
                        reason = "rate_limited" if status == 429 else f"http_{status}"
                        self._open(host, seconds, reason)
                        raise AdapterError(
                            f"Retailer request failed with HTTP {status}",
                            reason_code=reason, http_status=status, retry_count=attempt,
                            circuit_state="open",
                        )
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise AdapterError(
                            f"Retailer returned HTTP {status}", reason_code=f"http_{status}",
                            http_status=status, retry_count=attempt,
                        ) from exc
                    if detect_challenge(response.text):
                        self._open(host, 600, "verification_challenge")
                        raise RetailerBlockedError(
                            "Retailer presented a verification challenge",
                            reason_code="verification_challenge", http_status=status,
                            retry_count=attempt, circuit_state="open",
                        )
                    # Success: close the circuit
                    state.failures = 0
                    state.cooldown_until = 0
                    state.reason_code = None
                    state.half_open = False
                    self._persist_state(host, state)
                    return response

                # The loop always returns or raises; keep a safe fallback for type checkers.
                raise AdapterError(
                    f"Retailer request failed ({type(last_network_error).__name__})",
                    reason_code="request_exhausted", http_status=last_status, retry_count=2,
                )

    def _jitter(self, attempt: int) -> float:
        return self._random() * self._base_delay * (2**attempt)

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After")
        if not raw:
            return 0
        try:
            return max(0, float(raw))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0, (parsed - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return 0

    def _open(self, host: str, base_seconds: float, reason: str) -> None:
        state = self.state_for(host)
        state.failures += 1
        now = self._clock()
        # Exponential doubling: if we were in half-open state (recovering), double the cooldown
        if state.half_open and state.failures > 1:
            # Double the original cooldown duration, up to 24h
            new_duration = min(base_seconds * 2, 86400)
        else:
            new_duration = base_seconds
        state.cooldown_until = now + new_duration
        state.reason_code = reason
        state.half_open = False
        self._persist_state(host, state)


shared_client = RateLimitedClient()


def build_search_url(template: str, request: SearchRequest) -> str:
    # Brand and colour remain downstream match filters. Store search engines get
    # the model exactly once, which avoids broad OR matching and duplicate tokens.
    return template.format(query=quote_plus(request.query))
