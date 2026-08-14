import asyncio
import json

from sqlalchemy import select

from app.adapters.base import RetailerAdapter, RetailerBlockedError, RetailerDefinition
from app.adapters.onitsuka import OnitsukaAdapter
from app.db import SearchRow, SessionLocal, init_db
from app.schemas import Offer, SearchRequest
from app.search import SearchManager


def catalog_payload(products: list[dict]) -> str:
    response = json.dumps({"data": {"productSearch": {"total_count": len(products), "items": [{"product": item} for item in products]}}})
    escaped = json.dumps(response)
    return f"<script>const rawResponse = {escaped};</script>"


def product() -> dict:
    return {
        "uid": "1", "sku": "D507L.0152", "name": "MEXICO 66",
        "canonical_url": "//www.onitsukatiger.com/in/en-in/product/mexico-66/d507l.0152.html",
        "image": {"url": "https://images.example/mexico.jpg"},
        "price_range": {"minimum_price": {"regular_price": {"value": 11000}}},
        "gender": "UNISEX",
    }


def test_onitsuka_embedded_catalog_contracts_and_unknown_fallback():
    adapter = OnitsukaAdapter()
    parsed = adapter.parse_catalog(catalog_payload([product()]))
    assert parsed[0]["sku"] == "D507L.0152"
    assert adapter.parse_catalog(catalog_payload([])) == []
    request = SearchRequest(query="Mexico 66", uk_size="8")
    offer = adapter.parse(catalog_payload([product()]), request, "https://example.test")[0]
    assert offer.stock_status == "unknown" and not offer.size_available


def test_onitsuka_size_conversion_and_exact_magento_stock():
    adapter = OnitsukaAdapter()
    request = SearchRequest(query="Mexico 66", uk_size="8")
    detail = json.dumps({"attributes": {"200": {
        "code": "footwear_size", "options": [
            {"id": "size-9", "label": "Men US 9/Women US 10.5", "products": ["child-1"]},
            {"id": "size-10", "label": "Men US 10/Women US 11.5", "products": ["child-2"]},
        ]}}, "index": {"child-1": {"200": "size-9"}}, "salable": {"200": {"size-9": ["child-1"]}}})
    available = adapter.parse_detail(detail, request, product())
    assert available.stock_status == "in_stock" and available.size_available
    unavailable = adapter.parse_detail(detail, SearchRequest(query="Mexico 66", uk_size="9"), product())
    assert unavailable.stock_status == "out_of_stock" and not unavailable.size_available
    assert adapter.us_to_uk("Women US 10", "women") == "8"
    assert adapter.us_to_uk("K10", "kids") is None


class CountingAdapter(RetailerAdapter):
    def __init__(self, *, manual: bool = False, blocked: bool = False):
        self.calls = 0
        self.blocked = blocked
        self.definition = RetailerDefinition(
            "counting", "Counting", "official", "https://example.com/search?q={query}",
            collection_mode="manual" if manual else "automatic",
        )

    async def search(self, request, *, bypass_cache=False):
        self.calls += 1
        if self.blocked:
            raise RetailerBlockedError(
                "denied", reason_code="http_403", http_status=403,
                circuit_state="open",
            )
        return []

    def parse(self, payload, request, source_url):
        return []


async def complete(manager: SearchManager, search_id: str):
    for _ in range(100):
        result = manager.get(search_id)
        if result.state == "complete":
            return result
        await asyncio.sleep(0.01)
    raise AssertionError("search did not complete")


async def test_manual_adapter_performs_no_call_and_has_safe_link():
    init_db()
    adapter = CountingAdapter(manual=True)
    manager = SearchManager([adapter])
    created = await manager.create(SearchRequest(query="Mexico 66", uk_size="8"), bypass_cache=True)
    result = await complete(manager, str(created.id))
    assert adapter.calls == 0
    assert result.retailers[0].state == "manual"
    assert result.retailers[0].source == "https://example.com/search?q=Mexico+66"


async def test_cached_failure_keeps_diagnostics_and_clone_never_becomes_source():
    init_db()
    adapter = CountingAdapter(blocked=True)
    manager = SearchManager([adapter])
    request = SearchRequest(query="Cache Diagnostics", uk_size="8")
    original = await manager.create(request, bypass_cache=True)
    original_result = await complete(manager, str(original.id))
    cached = await manager.create(request.model_copy())
    status = cached.retailers[0]
    assert status.state == "blocked"
    assert status.reason_code == "http_403" and status.http_status == 403
    assert status.source.startswith("https://")
    with SessionLocal() as db:
        sources = db.scalars(select(SearchRow).where(
            SearchRow.cache_key == manager.cache_key(request), SearchRow.cached.is_(False)
        )).all()
    assert [row.id for row in sources] == [str(original_result.id)]
    restarted = SearchManager([adapter]).get(str(cached.id))
    assert restarted.retailers[0].reason_code == "http_403"


def test_legacy_offer_infers_stock_status():
    raw = {
        "retailer": "Store", "product_name": "Shoe", "requested_uk_size": "8",
        "size_available": False, "listed_price_paise": 10000,
        "effective_price_paise": 10000, "product_url": "https://example.com/shoe",
        "match_score": 0,
    }
    assert Offer.model_validate(raw).stock_status == "out_of_stock"
