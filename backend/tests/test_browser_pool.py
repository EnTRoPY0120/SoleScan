from app.adapters import browser as browser_module
from app.adapters import base as base_module
from app.adapters.base import RetailerDefinition, RetailerBlockedError
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
