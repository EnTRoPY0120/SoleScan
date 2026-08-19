import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.base import RetailerAdapter, RetailerBlockedError, RetailerDefinition
from app.db import init_db
from app.query_resolution import ModelVocabulary, TrustedModel
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


async def test_search_preserves_original_query_but_collects_with_resolved_query():
    init_db()

    class CapturingAdapter(FakeAdapter):
        seen_query = None

        async def search(self, request, *, bypass_cache=False):
            self.seen_query = request.query
            return []

    adapter = CapturingAdapter("resolved")
    manager = SearchManager(
        [adapter],
        vocabulary=ModelVocabulary([TrustedModel("Onitsuka Tiger", "MEXICO 66")]),
    )
    created = await manager.create(
        SearchRequest(query="onitsuka mexio 66", uk_size="9"),
        bypass_cache=True,
    )
    result = await wait_complete(manager, str(created.id))

    assert result.request.query == "onitsuka mexio 66"
    assert result.resolved_query == "onitsuka mexico 66"
    assert adapter.seen_query == "onitsuka mexico 66"
    reloaded = SearchManager(
        [adapter],
        vocabulary=ModelVocabulary([TrustedModel("Onitsuka Tiger", "MEXICO 66")]),
    ).get(str(result.id))
    assert reloaded.resolved_query == "onitsuka mexico 66"


async def test_verified_official_offer_teaches_the_next_search():
    init_db()

    class OnitsukaAdapter(FakeAdapter):
        async def search(self, request, *, bypass_cache=False):
            return [Offer(
                retailer="Onitsuka Tiger India", seller="Onitsuka Tiger India",
                product_name="MEXICO 66", brand="Onitsuka Tiger", model="MEXICO 66",
                category="footwear",
                requested_uk_size=request.uk_size, size_available=True,
                listed_price_paise=1100000, shipping_paise=0,
                effective_price_paise=1100000,
                product_url="https://example.com/mexico-66", match_score=0,
                last_checked=datetime.now(timezone.utc),
            )]

    manager = SearchManager([OnitsukaAdapter("onitsuka_learning")])
    exact = await manager.create(
        SearchRequest(query="onitsuka mexico 66", uk_size="9"), bypass_cache=True
    )
    await wait_complete(manager, str(exact.id))

    typo = await manager.create(
        SearchRequest(query="onitsuka mexio 66", uk_size="9")
    )
    result = await wait_complete(manager, str(typo.id))

    assert result.resolved_query == "onitsuka mexico 66"
    assert result.cached is True
    assert len(result.offers) == 1


async def test_shopper_can_search_the_original_text_without_correction():
    init_db()

    class CapturingAdapter(FakeAdapter):
        seen_query = None

        async def search(self, request, *, bypass_cache=False):
            self.seen_query = request.query
            return []

    adapter = CapturingAdapter("literal")
    manager = SearchManager(
        [adapter],
        vocabulary=ModelVocabulary([TrustedModel("Onitsuka Tiger", "MEXICO 66")]),
    )
    created = await manager.create(SearchRequest(
        query="onitsuka mexio 66", uk_size="9", allow_query_correction=False,
    ), bypass_cache=True)
    result = await wait_complete(manager, str(created.id))

    assert result.resolved_query is None
    assert adapter.seen_query == "onitsuka mexio 66"


async def test_recheck_retailer_creates_a_revision_and_preserves_other_observations():
    init_db()

    class MutableAdapter(FakeAdapter):
        def __init__(self, id, price):
            super().__init__(id)
            self.price = price
            self.calls = 0

        async def search(self, request, *, bypass_cache=False):
            self.calls += 1
            return [Offer(
                retailer=self.definition.name,
                product_name="Nike Air Jordan 1 Low", brand="Nike",
                model="Air Jordan 1 Low", category="footwear",
                requested_uk_size=request.uk_size, size_available=True,
                listed_price_paise=self.price, shipping_paise=0,
                effective_price_paise=self.price,
                product_url=f"https://example.com/{self.definition.id}", match_score=0,
                last_checked=datetime.now(timezone.utc),
            )]

    selected = MutableAdapter("selected", 900000)
    untouched = MutableAdapter("untouched", 950000)
    manager = SearchManager([selected, untouched])
    original = await manager.create(
        SearchRequest(query="Air Jordan 1 Low", brand="Nike", uk_size="9"),
        bypass_cache=True,
    )
    original = await wait_complete(manager, str(original.id))
    untouched_offer = next(offer for offer in original.offers if offer.retailer == "Untouched")
    selected.price = 800000

    revision = await manager.recheck_retailer(str(original.id), "selected")
    revision = await wait_complete(manager, str(revision.id))

    assert revision.revision_of == original.id
    assert revision.rechecked_retailer_id == "selected"
    assert revision.verification_attempt == 1
    assert next(offer for offer in revision.offers if offer.retailer == "Selected").effective_price_paise == 800000
    preserved = next(offer for offer in revision.offers if offer.retailer == "Untouched")
    assert preserved.last_checked == untouched_offer.last_checked
    assert (selected.calls, untouched.calls) == (2, 1)
    assert [status.retailer_id for status in revision.retailers] == ["selected", "untouched"]
    reloaded = SearchManager([selected, untouched]).get(str(revision.id))
    assert reloaded.revision_of == original.id
    assert reloaded.rechecked_retailer_id == "selected"
    assert reloaded.verification_attempt == 1
    other_revision = await manager.recheck_retailer(str(revision.id), "untouched")
    other_revision = await wait_complete(manager, str(other_revision.id))
    assert other_revision.rechecked_retailer_id == "untouched"
    assert other_revision.verification_attempt == 1


async def test_failed_verification_recheck_discards_state_before_manual_retry(tmp_path, monkeypatch):
    from app.adapters.browser import assisted_sessions
    init_db()

    class ChallengeAdapter(FakeAdapter):
        def __init__(self):
            super().__init__("reebok")
            self.definition = replace(self.definition, session_capable=True)

        async def search(self, request, *, bypass_cache=False):
            raise RetailerBlockedError(
                "Verification is still required", reason_code="verification_challenge"
            )

    monkeypatch.setattr(assisted_sessions, "directory", tmp_path)
    retained = Path(tmp_path) / "reebok.json"
    retained.write_text('{"cookies": []}')
    manager = SearchManager([ChallengeAdapter()])
    original = await manager.create(
        SearchRequest(query="Reebok Club C 85", uk_size="9"), bypass_cache=True,
    )
    original = await wait_complete(manager, str(original.id))

    revision = await manager.recheck_retailer(str(original.id), "reebok")
    revision = await wait_complete(manager, str(revision.id))

    assert revision.retailers[0].outcome == "verification_required"
    assert revision.retailers[0].session_state == "none"
    assert not retained.exists()

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
