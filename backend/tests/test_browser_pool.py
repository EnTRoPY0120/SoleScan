import pytest
from unittest.mock import AsyncMock
import json

from app.adapters import browser as browser_module
from app.adapters import base as base_module
from app.adapters.base import AdapterError, RetailerDefinition, RetailerBlockedError
from app.schemas import SearchRequest


class FakeContext:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self):
        self.contexts = []
        self.closed = False

    def is_connected(self):
        return not self.closed

    async def new_context(self, **kwargs):
        context = FakeContext()
        self.contexts.append(context)
        return context

    async def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self):
        self.launches = 0
        self.browser = FakeBrowser()

    async def launch(self, **kwargs):
        self.launches += 1
        return self.browser


class FakePlaywright:
    def __init__(self):
        self.chromium = FakeChromium()
        self.stopped = False

    async def stop(self):
        self.stopped = True


class FakeStarter:
    def __init__(self, playwright):
        self.playwright = playwright

    async def start(self):
        return self.playwright


async def test_browser_pool_reuses_process_and_cleans_up(monkeypatch):
    playwright = FakePlaywright()
    monkeypatch.setattr(browser_module, "async_playwright", lambda: FakeStarter(playwright))
    pool = browser_module.BrowserPool(max_contexts=2)
    first = await pool.context()
    await pool.release(first)
    second = await pool.context()
    await pool.release(second)
    assert playwright.chromium.launches == 1
    assert len(playwright.chromium.browser.contexts) == 2
    assert all(context.closed for context in playwright.chromium.browser.contexts)
    await pool.stop()
    assert playwright.chromium.browser.closed and playwright.stopped


async def test_real_chromium_product_extraction_and_shutdown():
    pool = browser_module.BrowserPool(max_contexts=1)
    context = await pool.context()
    try:
        page = await context.new_page()
        await page.set_content('''
          <html><head><meta property="og:image" content="https://example.com/shoe.jpg"></head>
          <body><h1>Converse Malden Street Black</h1><p>₹4,499</p>
          <button>UK 9</button><p>Style code A00811C</p></body></html>
        ''')
        definition = RetailerDefinition("myntra", "Myntra", "marketplace", "https://www.myntra.com/{query}", uses_browser=True)
        adapter = browser_module.BrowserMarketplaceAdapter(definition, pool)
        offer = await adapter._extract_product(page, SearchRequest(query="Malden Street", uk_size="9"), "https://example.com/p/1")
        assert offer is not None and offer.size_available
        assert offer.listed_price_paise == 449900
    finally:
        await pool.release(context)
        await pool.stop()


async def test_browser_search_does_not_abort_on_http_preflight(monkeypatch):
    class FakeLocator:
        def __init__(self, kind):
            self.kind = kind

        async def inner_text(self):
            return "No products matched your search"

        async def evaluate_all(self, script):
            return []

    class FakePage:
        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_timeout(self, milliseconds):
            return None

        def locator(self, selector):
            return FakeLocator(selector)

    class SearchContext(FakeContext):
        async def route(self, *args, **kwargs):
            return None

        async def new_page(self):
            return FakePage()

    class SearchPool:
        async def context(self):
            return SearchContext()

        async def release(self, context):
            await context.close()

    async def blocked_preflight(*args, **kwargs):
        raise RetailerBlockedError("plain HTTP request was blocked")

    # This would have made the old implementation fail before opening the
    # browser. Browser-backed adapters must no longer call it.
    monkeypatch.setattr(base_module.shared_client, "get", blocked_preflight)
    definition = RetailerDefinition(
        "reebok", "Reebok India", "official",
        "https://reebok.example/c/search?search_query={query}",
        uses_browser=True,
    )
    adapter = browser_module.BrowserMarketplaceAdapter(definition, SearchPool())

    assert await adapter.search(SearchRequest(query="Club C", uk_size="9")) == []


async def test_browser_http2_failure_retries_once_with_fresh_context():
    class FailingPage:
        async def goto(self, *_args, **_kwargs):
            raise RuntimeError("page.goto: net::ERR_HTTP2_PROTOCOL_ERROR")

    class FailingContext(FakeContext):
        async def route(self, *_args, **_kwargs):
            return None

        async def new_page(self):
            return FailingPage()

    class CountingPool:
        def __init__(self):
            self.contexts = []

        async def context(self, *_args):
            context = FailingContext()
            self.contexts.append(context)
            return context

        async def release(self, context):
            await context.close()

    pool = CountingPool()
    definition = RetailerDefinition(
        "browser_test", "Browser Test", "marketplace", "https://example.com/{query}", uses_browser=True,
    )
    adapter = browser_module.BrowserMarketplaceAdapter(definition, pool)

    with pytest.raises(AdapterError) as caught:
        await adapter.search(SearchRequest(query="Club C", uk_size="9"))
    assert caught.value.reason_code == "transport_protocol"
    assert caught.value.retry_count == 1
    assert caught.value.diagnostics["attempt"] == 2
    assert caught.value.diagnostics["net_error"] == "ERR_HTTP2_PROTOCOL_ERROR"
    assert len(pool.contexts) == 2 and all(context.closed for context in pool.contexts)


async def test_browser_transport_uses_explicit_http_fallback(monkeypatch):
    class FailingPage:
        async def goto(self, *_args, **_kwargs):
            raise RuntimeError("page.goto: net::ERR_HTTP2_PROTOCOL_ERROR")

    class FailingContext(FakeContext):
        async def route(self, *_args, **_kwargs): return None
        async def new_page(self): return FailingPage()

    class Pool:
        def __init__(self): self.calls = 0
        async def context(self, *_args): self.calls += 1; return FailingContext()
        async def release(self, context): await context.close()

    pool = Pool()
    definition = RetailerDefinition("myntra", "Myntra", "marketplace", "https://www.myntra.com/{query}", uses_browser=True)
    adapter = browser_module.BrowserMarketplaceAdapter(definition, pool)
    fallback = AsyncMock(return_value=[])
    monkeypatch.setattr(adapter, "_http_fallback", fallback)
    assert await adapter.search(SearchRequest(query="Club C", uk_size="9")) == []
    fallback.assert_awaited_once()
    assert pool.calls == 1


def test_myntra_http_fallback_contract_tracks_size_and_price():
    product = {
        "productId": 38419292,
        "product": "ASICS GEL-KAYANO 32 Men Running Shoes",
        "productName": "ASICS GEL-KAYANO 32 Men Running Shoes",
        "brand": "ASICS",
        "landingPageUrl": "sports-shoes/asics/gel-kayano-32/38419292/buy",
        "mrp": 16999,
        "price": 14449,
        "sizes": "8,8.5,9,10",
        "primaryColour": "Grey",
        "gender": "Men",
        "category": "Sports Shoes",
        "articleType": {"typeName": "Sports Shoes"},
        "images": [{"view": "default", "src": "http://assets.example/kayano.jpg"}],
    }
    payload = f'<script>window.__myx = {json.dumps({"searchData": {"results": {"totalCount": 1, "products": [product]}}})};</script>'
    definition = RetailerDefinition("myntra", "Myntra", "marketplace", "https://www.myntra.com/{query}", uses_browser=True)
    adapter = browser_module.BrowserMarketplaceAdapter(definition)
    offer = adapter._parse_myntra_search(
        payload,
        SearchRequest(query="GEL-KAYANO 32", brand="ASICS", uk_size="9"),
        "https://www.myntra.com/asics-gel-kayano-32",
    )[0]
    assert offer.model == "gel kayano 32"
    assert offer.size_available and offer.stock_status == "in_stock"
    assert offer.listed_price_paise == 1_699_900
    assert offer.effective_price_paise == 1_444_900
    assert offer.image_url.startswith("https://")
