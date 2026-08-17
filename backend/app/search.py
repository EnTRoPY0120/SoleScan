import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from typing import AsyncIterator
from uuid import UUID, uuid4

import structlog
from sqlalchemy import desc, select

from .adapters import ADAPTERS, DEFINITIONS
from .adapters.base import AdapterError, PartialResultError, RetailerAdapter, RetailerBlockedError, build_search_url
from .config import settings
from .db import AdapterRunRow, OfferRow, SearchRow, SessionLocal, utcnow
from .normalization import accept_offer, classify_category, colour_matches, deduplicate_offers, extract_department, normalize_size, normalize_text, rank_offers
from .schemas import Offer, ProductCategory, ProductDepartment, RetailerStatus, SearchRequest, SearchResult


log = structlog.get_logger()
CACHE_VERSION = 6  # Exact model/category/department contract; do not replay v5 jobs.


class SearchNotFound(KeyError):
    pass


class SearchManager:
    def __init__(self, adapters: list[RetailerAdapter] | None = None) -> None:
        self.adapters = list(ADAPTERS if adapters is None else adapters)
        self.definitions = list(DEFINITIONS if adapters is None else [adapter.definition for adapter in self.adapters])
        self._results: dict[str, SearchResult] = {}
        self._events: dict[str, list[dict]] = defaultdict(list)
        self._conditions: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)
        self._tasks: set[asyncio.Task] = set()
        self.health: dict[str, tuple[str, str | None]] = {
            definition.id: ("unknown", None) for definition in DEFINITIONS
        }

    @staticmethod
    def _source_url(definition, request: SearchRequest) -> str:
        return build_search_url(
            definition.search_url, request,
            include_brand=definition.kind in {"boutique", "marketplace"},
        )

    @staticmethod
    def cache_key(request: SearchRequest) -> str:
        data = request.model_dump(mode="json")
        data["query"] = normalize_text(data["query"])
        data["brand"] = normalize_text(data.get("brand")) or None
        data["colourway"] = normalize_text(data.get("colourway")) or None
        data["uk_size"] = normalize_size(data["uk_size"])
        data["collector_version"] = CACHE_VERSION
        packed = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(packed.encode()).hexdigest()

    async def create(self, request: SearchRequest, *, bypass_cache: bool = False) -> SearchResult:
        request.uk_size = normalize_size(request.uk_size)
        if not bypass_cache:
            cached = self._find_cached(request)
            if cached:
                return await self._clone_cached(cached, request)
        search_id = str(uuid4())
        now = utcnow()
        statuses = [
            RetailerStatus(
                retailer_id=definition.id,
                retailer=definition.name,
                state="pending",
                source=self._source_url(definition, request),
                session_capable=definition.session_capable,
                session_state=self._session_state(definition.id),
            )
            for definition in self.definitions
        ]
        result = SearchResult(
            id=UUID(search_id), request=request, state="running", offers=[],
            retailers=statuses, created_at=now,
        )
        self._results[search_id] = result
        with SessionLocal.begin() as db:
            db.add(SearchRow(
                id=search_id, cache_key=self.cache_key(request),
                request_json=request.model_dump_json(), state="running", cached=False, created_at=now,
            ))
        await self._emit(search_id, "search_started", {"search_id": search_id})
        task = asyncio.create_task(self._run(search_id, bypass_cache=bypass_cache))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return result

    @staticmethod
    def _session_state(retailer_id: str) -> str:
        try:
            from .adapters.browser import assisted_sessions
            return assisted_sessions.state_for(retailer_id)
        except Exception:
            return "none"

    def _find_cached(self, request: SearchRequest) -> SearchRow | None:
        cutoff = utcnow() - timedelta(seconds=settings.cache_ttl_seconds)
        with SessionLocal() as db:
            return db.scalar(select(SearchRow).where(
                SearchRow.cache_key == self.cache_key(request),
                SearchRow.state == "complete",
                SearchRow.cached.is_(False),
                SearchRow.completed_at >= cutoff,
            ).order_by(desc(SearchRow.completed_at)).limit(1))

    async def _clone_cached(self, source: SearchRow, request: SearchRequest) -> SearchResult:
        new_id = str(uuid4())
        now = utcnow()
        with SessionLocal() as db:
            offers = db.scalars(select(OfferRow).where(OfferRow.search_id == source.id)).all()
            runs = db.scalars(select(AdapterRunRow).where(AdapterRunRow.search_id == source.id)).all()
        strong = [Offer.model_validate_json(row.offer_json) for row in offers if not row.weak]
        statuses = [self._status_from_run(row, cached=True) for row in runs]
        result = SearchResult(
            id=UUID(new_id), request=request, state="complete", offers=rank_offers(strong),
            retailers=statuses, created_at=now,
            completed_at=now, cached=True,
        )
        self._results[new_id] = result
        with SessionLocal.begin() as db:
            db.add(SearchRow(
                id=new_id, cache_key=self.cache_key(request), request_json=request.model_dump_json(),
                state="complete", cached=True, created_at=now, completed_at=now,
            ))
            for row in offers:
                db.add(OfferRow(search_id=new_id, retailer_id=row.retailer_id, offer_json=row.offer_json, weak=row.weak, checked_at=now))
            for row in runs:
                cloned_state = "cached" if row.state == "complete" else row.state
                db.add(AdapterRunRow(
                    search_id=new_id, retailer_id=row.retailer_id, state=cloned_state,
                    offer_count=row.offer_count, error=row.error, elapsed_ms=row.elapsed_ms,
                    reason_code=row.reason_code, http_status=row.http_status,
                    retry_count=row.retry_count, circuit_state=row.circuit_state,
                    source_url=row.source_url, created_at=now,
                ))
        await self._emit(new_id, "cache_hit", {"source_search_id": source.id})
        await self._emit(new_id, "search_complete", result.model_dump(mode="json"))
        return result

    async def _run(self, search_id: str, *, bypass_cache: bool) -> None:
        tasks = [
            asyncio.create_task(self._run_adapter(search_id, adapter, bypass_cache))
            for adapter in self.adapters
        ]
        try:
            async with asyncio.timeout(settings.overall_timeout_seconds):
                await asyncio.gather(*tasks, return_exceptions=True)
        except TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            result = self._results[search_id]
            for status in result.retailers:
                if status.state in {"pending", "running"}:
                    status.state = "timeout"
                    status.error = f"Overall {settings.overall_timeout_seconds:g}-second search deadline reached"
                    status.reason_code = "overall_timeout"
                    await self._emit(search_id, "retailer_error", status.model_dump(mode="json"))
                    definition = next((d for d in self.definitions if d.name == status.retailer), None)
                    if definition:
                        with SessionLocal.begin() as db:
                            existing = db.scalar(select(AdapterRunRow).where(
                                AdapterRunRow.search_id == search_id,
                                AdapterRunRow.retailer_id == definition.id,
                            ))
                            if existing is None:
                                db.add(AdapterRunRow(
                                    search_id=search_id, retailer_id=definition.id,
                                    state="timeout", error=status.error,
                                    reason_code=status.reason_code, source_url=status.source,
                                    elapsed_ms=round(settings.overall_timeout_seconds * 1000), created_at=utcnow(),
                                ))
        result = self._results[search_id]
        result.offers = rank_offers(deduplicate_offers(result.offers))
        result.state = "complete"
        result.completed_at = utcnow()
        with SessionLocal.begin() as db:
            row = db.get(SearchRow, search_id)
            if row:
                row.state = "complete"
                row.completed_at = result.completed_at
        await self._emit(search_id, "search_complete", result.model_dump(mode="json"))

    async def _run_adapter(self, search_id: str, adapter: RetailerAdapter, bypass_cache: bool) -> None:
        result = self._results[search_id]
        status = next(item for item in result.retailers if item.retailer == adapter.definition.name)
        status.state = "running"
        started = time.monotonic()
        await self._emit(search_id, "retailer_started", status.model_dump(mode="json"))
        state = "complete"
        error = None
        accepted: list[Offer] = []
        definition = adapter.definition
        try:
            async with asyncio.timeout(settings.retailer_timeout_seconds):
                offers = await adapter.search(result.request, bypass_cache=bypass_cache)
                for offer in offers:
                    self._prepare_offer(offer)
                    offer.colour_match = colour_matches(result.request, offer)
                    if accept_offer(result.request, offer, footwear_scope_verified=definition.footwear_only_scope):
                        offer.match_score = 1
                        offer.confidence = "exact"
                        accepted.append(offer)
                result.offers.extend(accepted)
                status.state = "complete"
                status.offer_count = len(accepted)
                self.health[adapter.definition.id] = ("healthy", None)
        except PartialResultError as exc:
            # Some products succeeded - use partial offers
            for offer in exc.offers:
                self._prepare_offer(offer)
                offer.colour_match = colour_matches(result.request, offer)
                if accept_offer(result.request, offer, footwear_scope_verified=definition.footwear_only_scope):
                    offer.match_score = 1
                    offer.confidence = "exact"
                    accepted.append(offer)
            result.offers.extend(accepted)
            state = status.state = "partial"
            status.offer_count = len(accepted)
            status.error = str(exc)[:300]
            self._apply_diagnostics(status, exc)
            self.health[adapter.definition.id] = ("healthy", str(exc))
            log.info("adapter_partial", retailer=adapter.definition.id, offer_count=len(accepted))
        except asyncio.TimeoutError:
            state = status.state = "timeout"
            error = status.error = f"Retailer did not respond within {settings.retailer_timeout_seconds:g} seconds"
            status.reason_code = "retailer_timeout"
            self.health[adapter.definition.id] = ("unavailable", error)
        except RetailerBlockedError as exc:
            state = status.state = "needs_session" if (
                definition.session_capable and exc.reason_code == "verification_challenge"
            ) else "blocked"
            error = status.error = str(exc)[:300] or "Retailer was not checked"
            self._apply_diagnostics(status, exc)
            self.health[adapter.definition.id] = ("unavailable", error)
            log.warning(
                "adapter_blocked", retailer=adapter.definition.id,
                reason_code=exc.reason_code, http_status=exc.http_status,
                retry_count=exc.retry_count, circuit_state=exc.circuit_state,
            )
        except AdapterError as exc:
            state = status.state = "timeout" if exc.reason_code == "retailer_timeout" else "error"
            error = status.error = str(exc)[:300] or "Retailer was unavailable"
            self._apply_diagnostics(status, exc)
            self.health[adapter.definition.id] = ("unavailable", error)
            log.warning(
                "adapter_failed", retailer=adapter.definition.id,
                reason_code=exc.reason_code, http_status=exc.http_status,
                retry_count=exc.retry_count, circuit_state=exc.circuit_state,
            )
        except Exception as exc:
            state = status.state = "error"
            error = status.error = str(exc)[:300] or type(exc).__name__
            self.health[adapter.definition.id] = ("unavailable", error)
            log.warning("adapter_failed", retailer=adapter.definition.id, error=type(exc).__name__)
        status.elapsed_ms = round((time.monotonic() - started) * 1000)
        with SessionLocal.begin() as db:
            db.add(AdapterRunRow(
                search_id=search_id, retailer_id=adapter.definition.id, state=state,
                offer_count=len(accepted), error=status.error or error, elapsed_ms=status.elapsed_ms,
                reason_code=status.reason_code, http_status=status.http_status,
                retry_count=status.retry_count, circuit_state=status.circuit_state,
                source_url=status.source, created_at=utcnow(),
            ))
            for offer in accepted:
                db.add(OfferRow(search_id=search_id, retailer_id=adapter.definition.id, offer_json=offer.model_dump_json(), weak=False, checked_at=utcnow()))
        event = "retailer_complete" if state in {"complete", "partial"} else "retailer_error"
        await self._emit(search_id, event, {
            **status.model_dump(mode="json"),
            "offers": [offer.model_dump(mode="json") for offer in accepted],
        })

    @staticmethod
    def _prepare_offer(offer: Offer) -> None:
        """Fill evidence fields when an adapter omitted them."""
        if getattr(offer, "category", None) in (None, "unknown"):
            offer.category = ProductCategory(classify_category(title=offer.product_name, url=offer.product_url))
        if getattr(offer, "department", None) in (None, "unknown"):
            offer.department = ProductDepartment(extract_department(title=offer.product_name, url=offer.product_url))

    @staticmethod
    def _apply_diagnostics(status: RetailerStatus, exc: AdapterError) -> None:
        status.reason_code = exc.reason_code
        status.http_status = exc.http_status
        status.retry_count = exc.retry_count
        status.circuit_state = exc.circuit_state
        SearchManager._apply_retry_at(status)

    @staticmethod
    def _apply_retry_at(status: RetailerStatus) -> None:
        if status.circuit_state != "open" or not status.source:
            return
        import httpx
        from .adapters.base import shared_client

        host = httpx.URL(status.source).host
        if not host:
            return
        state = shared_client.state_for(host)
        remaining = max(0.0, state.cooldown_until - shared_client._clock())
        if remaining:
            status.retry_at = datetime.now(timezone.utc) + timedelta(seconds=remaining)

    def get(self, search_id: str) -> SearchResult:
        if search_id in self._results:
            return self._results[search_id]
        with SessionLocal() as db:
            search = db.get(SearchRow, search_id)
            if not search:
                raise SearchNotFound(search_id)
            offers = db.scalars(select(OfferRow).where(OfferRow.search_id == search_id)).all()
            runs = db.scalars(select(AdapterRunRow).where(AdapterRunRow.search_id == search_id)).all()
        valid_offers: list[Offer] = []
        for row in offers:
            if row.weak:
                continue
            offer = Offer.model_validate_json(row.offer_json)
            definition = next((item for item in DEFINITIONS if item.id == row.retailer_id), None)
            self._prepare_offer(offer)
            if definition is not None and accept_offer(
                SearchRequest.model_validate_json(search.request_json), offer,
                footwear_scope_verified=definition.footwear_only_scope,
            ):
                valid_offers.append(offer)
        result = SearchResult(
            id=UUID(search.id), request=SearchRequest.model_validate_json(search.request_json), state=search.state,
            offers=rank_offers(valid_offers),
            retailers=[self._status_from_run(run) for run in runs],
            created_at=search.created_at, completed_at=search.completed_at, cached=search.cached,
        )
        self._results[search_id] = result
        return result

    @staticmethod
    def _status_from_run(run: AdapterRunRow, *, cached: bool = False) -> RetailerStatus:
        state = "cached" if cached and run.state == "complete" else ("needs_session" if run.state == "manual" else run.state)
        status = RetailerStatus(
            retailer_id=run.retailer_id,
            retailer=next((d.name for d in DEFINITIONS if d.id == run.retailer_id), run.retailer_id),
            state=state,
            offer_count=run.offer_count,
            error=run.error,
            elapsed_ms=run.elapsed_ms,
            reason_code=run.reason_code,
            http_status=run.http_status,
            retry_count=run.retry_count,
            circuit_state=run.circuit_state,
            source=run.source_url,
            session_capable=next((d.session_capable for d in DEFINITIONS if d.id == run.retailer_id), False),
            session_state=SearchManager._session_state(run.retailer_id),
        )
        SearchManager._apply_retry_at(status)
        return status

    async def events(self, search_id: str) -> AsyncIterator[dict]:
        self.get(search_id)
        index = 0
        while True:
            while index < len(self._events[search_id]):
                event = self._events[search_id][index]
                index += 1
                yield event
                if event["event"] == "search_complete":
                    return
            if self._results[search_id].state == "complete":
                yield {"event": "search_complete", "data": self._results[search_id].model_dump(mode="json")}
                return
            async with self._conditions[search_id]:
                try:
                    await asyncio.wait_for(self._conditions[search_id].wait(), timeout=15)
                except TimeoutError:
                    yield {"event": "keepalive", "data": {}}

    async def _emit(self, search_id: str, event: str, data: dict) -> None:
        self._events[search_id].append({"event": event, "data": data})
        async with self._conditions[search_id]:
            self._conditions[search_id].notify_all()


manager = SearchManager()
