import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from .base import AdapterError, RetailerAdapter, RetailerBlockedError, RetailerDefinition, detect_challenge
from ..normalization import effective_price, normalize_size, parse_inr_paise
from ..schemas import ConditionalOffer, Offer, SearchRequest


PRODUCT_LINK_SELECTORS = {
    "foot_locker": 'a[href*="/product/"],a[href*="/products/"],a[href*="/p/"]',
    "myntra": 'a[href*="/buy"],a[href*="/p/"]',
    "ajio": 'a[href*="/p/"]',
    "nykaa_fashion": 'a[href*="/p/"],a[href*="/product/"]',
    "reebok": 'a[href*="/p/"]',
}


class BrowserPool:
    """One Chromium process, with an isolated context for every retailer run."""

    def __init__(self, max_contexts: int = 3) -> None:
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_contexts)

    async def start(self) -> None:
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return
            self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(headless=True)
            except Exception:
                await self._playwright.stop()
                self._playwright = None
                raise

    async def context(self):
        await self.start()
        await self._semaphore.acquire()
        try:
            return await self._browser.new_context(
                locale="en-IN", timezone_id="Asia/Kolkata",
                viewport={"width": 1280, "height": 900},
            )
        except Exception:
            self._semaphore.release()
            raise

    async def release(self, context) -> None:
        try:
            await context.close()
        finally:
            self._semaphore.release()

    async def stop(self) -> None:
        async with self._lock:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            self._browser = self._playwright = None


browser_pool = BrowserPool()


class BrowserMarketplaceAdapter(RetailerAdapter):
    """Browser-backed collector for dynamic or HTTP-blocking storefronts."""

    def __init__(self, definition: RetailerDefinition, pool: BrowserPool | None = None) -> None:
        self.definition = definition
        self.pool = pool or browser_pool

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        query = request.query
        search_url = self.definition.search_url.format(query=quote_plus(query))

        # Do not probe browser-backed storefronts with the shared HTTP client.
        # A number of retailers reject non-browser requests while allowing an
        # ordinary browser navigation.  Treating that probe as authoritative
        # prevents Chromium from ever getting a chance to load the storefront.
        context = None
        try:
            context = await self.pool.context()
            await context.route(re.compile(r"\.(woff2?|mp4|webm)(\?|$)"), lambda route: route.abort())
            page = await context.new_page()
            if self.definition.id == "foot_locker":
                await page.goto(search_url, wait_until="domcontentloaded", timeout=15_000)
                field = page.locator('input[type="search"],input[placeholder*="Search" i]').first
                await field.wait_for(state="visible", timeout=6_000)
                await field.fill(query)
                await field.press("Enter")
                await page.wait_for_load_state("domcontentloaded", timeout=12_000)
            else:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=15_000)
            await page.wait_for_timeout(1_500)
            body = await page.locator("body").inner_text()
            if detect_challenge(body):
                raise RetailerBlockedError(
                    f"{self.definition.name} presented a verification challenge",
                    reason_code="verification_challenge", circuit_state="open",
                )
            selector = PRODUCT_LINK_SELECTORS[self.definition.id]
            links = await page.locator(selector).evaluate_all(
                "els => [...new Set(els.map(e => e.href).filter(Boolean))].slice(0, 6)"
            )
            if not links:
                if re.search(r"no (?:products|results|matches)|0 results", body, re.I):
                    return []
                raise AdapterError(
                    f"{self.definition.name} returned an unrecognized catalog shell",
                    reason_code="catalog_shell",
                )
            offers: list[Offer] = []
            for link in links[:4]:
                response = await page.goto(link, wait_until="domcontentloaded", timeout=10_000)
                if response and response.status == 404:
                    continue
                await page.wait_for_timeout(500)
                text = await page.locator("body").inner_text()
                if detect_challenge(text):
                    raise RetailerBlockedError(
                        f"{self.definition.name} presented a verification challenge",
                        reason_code="verification_challenge", circuit_state="open",
                    )
                offer = await self._extract_product(page, request, link)
                if offer:
                    offers.append(offer)
            if links and not offers:
                raise AdapterError(
                    f"{self.definition.name} product extraction failed",
                    reason_code="product_extraction_failed",
                )
            return offers
        except PlaywrightTimeoutError as exc:
            raise AdapterError(f"{self.definition.name} browser page timed out") from exc
        except Exception as exc:
            if isinstance(exc, AdapterError):
                raise
            message = str(exc)
            # Better diagnostics for common browser errors
            if "Executable doesn't exist" in message or "libnspr4.so" in message:
                raise AdapterError(
                    "Chromium is unavailable; start the supported Docker runtime",
                    reason_code="browser_unavailable",
                ) from exc
            # HTTP/2 protocol errors
            if "net::ERR_HTTP2_PROTOCOL_ERROR" in message or "HTTP2" in message:
                raise AdapterError(
                    f"{self.definition.name} failed due to an HTTP/2 transport error; the site may require a different protocol",
                    reason_code="transport_protocol",
                ) from exc
            # Generic net errors
            if "net::ERR_" in message:
                err_code = message.split("net::ERR_")[1].split()[0] if "net::ERR_" in message else "UNKNOWN"
                raise AdapterError(
                    f"{self.definition.name} could not load the page (net::ERR_{err_code})",
                    reason_code="browser_network_error",
                ) from exc
            # Generic browser error with type
            short_msg = message[:100] if len(message) > 100 else message
            raise AdapterError(
                f"{self.definition.name} browser collection failed ({type(exc).__name__}): {short_msg}",
                reason_code="browser_collection_failed",
            ) from exc
        finally:
            if context is not None:
                await self.pool.release(context)

    async def _extract_product(self, page, request: SearchRequest, url: str) -> Offer | None:
        data = await page.evaluate(r"""(size) => {
          const text = document.body?.innerText || '';
          const prop = name => document.querySelector(`meta[property="${name}"]`)?.content || '';
          const named = name => document.querySelector(`meta[name="${name}"]`)?.content || '';
          const h1 = document.querySelector('h1')?.innerText?.trim() || prop('og:title') || document.title;
          const candidates = [...document.querySelectorAll('button,[role="button"],li,[data-size],span')]
            .filter(e => (e.innerText || e.dataset?.size || '').trim().match(new RegExp('^(UK\\s*)?' + size.replace('.', '\\.') + '$', 'i')));
          const inStock = candidates.some(e => !e.disabled && e.getAttribute('aria-disabled') !== 'true' &&
            !/sold|disable|unavailable|out.of.stock/i.test(`${e.className} ${e.parentElement?.className || ''}`));
          const json = [...document.querySelectorAll('script[type="application/ld+json"]')].map(e => e.textContent).join('\n');
          return { text, name:h1, image:prop('og:image'), price:prop('product:price:amount') || named('twitter:data1'), inStock, json };
        }""", normalize_size(request.uk_size))
        return self._offer_from_snapshot(data, request, url)

    def _offer_from_snapshot(self, data: dict, request: SearchRequest, url: str) -> Offer | None:
        text, name = data.get("text", ""), data.get("name", "")
        price_matches = re.findall(r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]*(?:\.\d{1,2})?)", text, re.I)
        raw_price = data.get("price") or (price_matches[0] if price_matches else None)
        if not name or raw_price is None:
            return None
        listed = parse_inr_paise(raw_price)
        brand = "Converse" if "converse" in (name + " " + text[:500]).lower() else request.brand
        colour_match = re.search(r"\b(black|white|grey|gray|red|green|navy|blue|pink|beige|brown)\b", name, re.I)
        seller_match = re.search(r"Sold By\s*\n?([^\n]+)", text, re.I)
        style_match = re.search(r"(?:style|product)\s*(?:code|id)?\s*[:#-]?\s*([A-Z0-9-]{5,})", text, re.I)
        conditional: list[ConditionalOffer] = []
        coupon = re.search(r"(?:Use Code|Get it for)\s*\n?([^\n]{2,80})", text, re.I)
        if coupon:
            conditional.append(ConditionalOffer(kind="coupon", description=coupon.group(0).replace("\n", " ")))
        return Offer(
            retailer=self.definition.name, seller=seller_match.group(1).strip() if seller_match else None,
            product_name=name, brand=brand, model=name,
            colourway=colour_match.group(1).title() if colour_match else None,
            image_url=data.get("image") or None,
            style_code=style_match.group(1) if style_match else url.rstrip("/").split("/")[-1].split("?")[0],
            requested_uk_size=normalize_size(request.uk_size), size_available=bool(data.get("inStock")),
            listed_price_paise=listed, automatic_discount_paise=0, shipping_paise=None,
            effective_price_paise=effective_price(listed), conditional_offers=conditional,
            product_url=urljoin(self.definition.search_url, url),
            return_policy="Confirm the current retailer return window on the product page.",
            match_score=0, last_checked=datetime.now(timezone.utc),
        )

    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        """Parse deterministic product snapshots used for collector contract tests."""
        soup = BeautifulSoup(payload, "html.parser")
        text = soup.get_text("\n", strip=True)
        title = soup.select_one("h1")
        image = soup.select_one('meta[property="og:image"]')
        size = normalize_size(request.uk_size)
        candidates = soup.select("[data-size],button,li")
        available = any(
            (node.get("data-size") or node.get_text(" ", strip=True)).replace("UK", "").strip() == size
            and not node.has_attr("disabled")
            and node.get("aria-disabled") != "true"
            and not re.search(r"sold|disable|unavailable|out.of.stock", " ".join(node.get("class", [])), re.I)
            for node in candidates
        )
        offer = self._offer_from_snapshot({
            "text": text, "name": title.get_text(" ", strip=True) if title else "",
            "image": image.get("content") if image else None, "inStock": available,
        }, request, source_url)
        return [offer] if offer else []
