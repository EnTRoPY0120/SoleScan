import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from .base import AdapterError, PartialResultError, RetailerAdapter, RetailerBlockedError, RetailerDefinition, detect_challenge, shared_client
from ..assisted_runtime import AssistedBrowserRuntime, assisted_runtime
from ..normalization import canonical_query, classify_category, effective_price, extract_department, normalize_size, parse_inr_paise, recognized_brands
from ..schemas import ConditionalOffer, Offer, SearchRequest


PRODUCT_LINK_SELECTORS = {
    "foot_locker": 'a[href*="/product/"],a[href*="/products/"],a[href*="/p/"]',
    "myntra": 'a[href*="/buy"],a[href*="/p/"]',
    "ajio": 'a[href*="/p/"]',
    "nykaa_fashion": 'a[href*="/p/"],a[href*="/product/"]',
    "reebok": 'a[href*="/p/"]',
}
HTTP_FALLBACK_RETAILERS = {"foot_locker", "myntra", "nykaa_fashion"}


class BrowserPool:
    """One Chromium process, with an isolated context for every retailer run."""

    def __init__(self, max_contexts: int = 3) -> None:
        self._playwright = None
        self._browser = None
        self._assisted_playwright = None
        self._assisted_browser = None
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

    async def context(self, storage_state: str | None = None):
        await self.start()
        await self._semaphore.acquire()
        try:
            kwargs = {"locale": "en-IN", "timezone_id": "Asia/Kolkata",
                      "viewport": {"width": 1280, "height": 900}}
            if storage_state and os.path.exists(storage_state):
                kwargs["storage_state"] = storage_state
            return await self._browser.new_context(**kwargs)
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
            try:
                if self._browser:
                    await self._browser.close()
            finally:
                try:
                    if self._playwright:
                        await self._playwright.stop()
                finally:
                    try:
                        if self._assisted_browser:
                            await self._assisted_browser.close()
                    finally:
                        if self._assisted_playwright:
                            await self._assisted_playwright.stop()
                        self._browser = self._playwright = self._assisted_browser = self._assisted_playwright = None

    async def assisted_context(self, storage_state: str | None = None):
        """Open an isolated headful context for a user-cleared challenge.

        The runtime compose file provides Xvfb/x11vnc/websockify on localhost;
        keeping this separate from normal headless collection prevents a
        challenge session from changing ordinary search behaviour.
        """
        async with self._lock:
            connected = bool(
                self._assisted_browser
                and getattr(self._assisted_browser, "is_connected", lambda: True)()
            )
            if not self._assisted_playwright or not connected:
                self._assisted_playwright = await async_playwright().start()
                try:
                    # Pass DISPLAY explicitly. Playwright's headed launch can
                    # otherwise lose the inherited display in long-lived ASGI
                    # process environments even though the X socket is ready.
                    launch_env = dict(os.environ)
                    launch_env["DISPLAY"] = os.getenv("DISPLAY", ":99")
                    self._assisted_browser = await self._assisted_playwright.chromium.launch(
                        headless=False, env=launch_env,
                    )
                except Exception:
                    await self._assisted_playwright.stop()
                    self._assisted_playwright = self._assisted_browser = None
                    raise
        await self._semaphore.acquire()
        try:
            kwargs = {"locale": "en-IN", "timezone_id": "Asia/Kolkata",
                      "viewport": {"width": 1280, "height": 900}}
            if storage_state and os.path.exists(storage_state):
                kwargs["storage_state"] = storage_state
            return await self._assisted_browser.new_context(**kwargs)
        except Exception:
            self._semaphore.release()
            raise


browser_pool = BrowserPool()


class SessionBusyError(RuntimeError):
    pass


class ChallengeNotClearedError(RuntimeError):
    pass


class AssistedBrowserSessions:
    """Single-user, single-retailer assisted browser session coordinator."""

    def __init__(self, pool: BrowserPool | None = None, directory=None, runtime: AssistedBrowserRuntime | None = None) -> None:
        from ..config import settings
        self.pool = pool or browser_pool
        self.directory = Path(directory or settings.browser_sessions_dir)
        self.runtime = runtime or assisted_runtime
        self.idle_seconds = settings.assisted_session_idle_seconds
        self._lock = asyncio.Lock()
        self._active: dict | None = None
        self._expiry_task: asyncio.Task | None = None

    def state_for(self, retailer_id: str) -> str:
        if self._active and self._active["retailer_id"] == retailer_id:
            return "active"
        path = self.directory / f"{retailer_id}.json"
        if not path.exists():
            return "none"
        try:
            payload = json.loads(path.read_text())
            if not isinstance(payload, dict):
                return "expired"
            cookies = payload.get("cookies", [])
            if not isinstance(cookies, list):
                return "expired"
            if any(not isinstance(cookie, dict) for cookie in cookies):
                return "expired"
            finite = [float(cookie.get("expires", -1)) for cookie in cookies if float(cookie.get("expires", -1)) > 0]
            if finite and max(finite) <= time.time():
                return "expired"
        except (OSError, ValueError, TypeError):
            return "expired"
        return "active"

    async def start(self, retailer_id: str, search_id: str, url: str) -> dict:
        async with self._lock:
            if self._active is not None:
                raise SessionBusyError("Another retailer session is already active")
            await self.runtime.ensure_ready()
            self.directory.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.directory, 0o700)
            except OSError:
                pass
            path = self.directory / f"{retailer_id}.json"
            usable_state = path.exists() and self.state_for(retailer_id) == "active"
            try:
                context = await self.pool.assisted_context(str(path) if usable_state else None)
            except TypeError:
                # Keep small test/dry-run pools compatible with the original
                # no-argument context hook; production BrowserPool supports
                # storage state explicitly.
                context = await self.pool.assisted_context()
            try:
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            except Exception:
                # Navigation failures must not consume the single assisted
                # session slot or leave a browser context holding a semaphore
                # permit indefinitely.
                await self.pool.release(context)
                raise
            self._active = {"retailer_id": retailer_id, "search_id": search_id,
                            "context": context, "page": page, "path": path}
            self._expiry_task = asyncio.create_task(self._expire_after(retailer_id, search_id))
            from ..config import settings
            return {"retailer_id": retailer_id, "search_id": search_id,
                    "session_state": "active", "viewer_url": settings.vnc_url}

    async def complete(self, retailer_id: str, search_id: str, *, challenge_cleared: bool | None) -> dict:
        async with self._lock:
            active = self._active
            if not active or active["retailer_id"] != retailer_id or active["search_id"] != search_id:
                raise RuntimeError("No matching retailer session is active")
            # ``None`` is allowed for a retailer that only showed a consent
            # page; visible verification text is still checked below. An
            # explicit negative acknowledgement can never save browser state.
            if challenge_cleared is False:
                raise ChallengeNotClearedError("The verification challenge is not cleared")
            try:
                body = await active["page"].locator("body").inner_text()
                if detect_challenge(body):
                    raise ChallengeNotClearedError("The verification challenge is not cleared")
            except ChallengeNotClearedError:
                raise
            except Exception:
                # A test double or a retailer that replaces the page is still
                # allowed when the UI has explicitly confirmed completion.
                pass
            path = active["path"]
            await active["context"].storage_state(path=str(path))
            os.chmod(path, 0o600)
            await self.pool.release(active["context"])
            self._active = None
            self._cancel_expiry()
            return {"retailer_id": retailer_id, "session_state": "active", "storage_path": str(path)}

    async def reset(self, retailer_id: str) -> None:
        async with self._lock:
            if self._active and self._active["retailer_id"] == retailer_id:
                await self.pool.release(self._active["context"])
                self._active = None
                self._cancel_expiry()
            path = self.directory / f"{retailer_id}.json"
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    async def _expire_after(self, retailer_id: str, search_id: str) -> None:
        try:
            await asyncio.sleep(self.idle_seconds)
            async with self._lock:
                active = self._active
                if active and active["retailer_id"] == retailer_id and active["search_id"] == search_id:
                    await self.pool.release(active["context"])
                    self._active = None
                    self._expiry_task = None
        except asyncio.CancelledError:
            return

    def _cancel_expiry(self) -> None:
        task, self._expiry_task = self._expiry_task, None
        if task and task is not asyncio.current_task():
            task.cancel()


assisted_sessions = AssistedBrowserSessions()


class BrowserMarketplaceAdapter(RetailerAdapter):
    """Browser-backed collector for dynamic or HTTP-blocking storefronts."""

    def __init__(self, definition: RetailerDefinition, pool: BrowserPool | None = None) -> None:
        self.definition = definition
        self.pool = pool or browser_pool

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        for attempt in range(2):
            try:
                return await self._search_once(request)
            except AdapterError as exc:
                if (
                    exc.reason_code == "transport_protocol" and attempt == 0
                    and self.definition.id in HTTP_FALLBACK_RETAILERS
                ):
                    try:
                        return await self._http_fallback(request)
                    except AdapterError as fallback_exc:
                        fallback_exc.retry_count = 1
                        fallback_exc.diagnostics["attempt"] = 2
                        fallback_exc.diagnostics.setdefault("transport", "httpx_http1")
                        raise
                if exc.reason_code != "transport_protocol" or attempt == 1:
                    exc.retry_count = attempt
                    if exc.diagnostics:
                        exc.diagnostics["attempt"] = attempt + 1
                    raise
                # A protocol failure can be connection-specific. Release the
                # failed context in _search_once, then retry exactly once with
                # a new isolated browser context.
        raise AssertionError("bounded browser retry exhausted")

    async def _http_fallback(self, request: SearchRequest) -> list[Offer]:
        """Explicit HTTP/1 fallback after Chromium's HTTP/2 transport fails."""
        query = canonical_query(request, include_brand=self.definition.kind in {"boutique", "marketplace"})
        search_url = self.definition.search_url.format(query=quote_plus(query))
        response = await shared_client.get(search_url)
        if self.definition.id == "myntra":
            return self._parse_myntra_search(response.text, request, str(response.url))
        raise AdapterError(
            f"{self.definition.name} returned an unsupported fallback response",
            reason_code="catalog_contract_changed",
            http_status=response.status_code,
            diagnostics={
                "stage": "catalog", "final_url": str(response.url),
                "http_status": response.status_code, "transport": "httpx_http1",
            },
        )

    def _parse_myntra_search(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        soup = BeautifulSoup(payload, "html.parser")
        script_text = next(
            (node.string or node.get_text() for node in soup.find_all("script") if "window.__myx = " in (node.string or node.get_text())),
            None,
        )
        try:
            raw = script_text.split("window.__myx = ", 1)[1].rsplit(";", 1)[0]
            results = json.loads(raw)["searchData"]["results"]
            total = results["totalCount"]
            products = results["products"]
            if not isinstance(total, int) or not isinstance(products, list):
                raise TypeError
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise AdapterError(
                "Myntra returned an unrecognized search response",
                reason_code="catalog_contract_changed",
                diagnostics={"stage": "catalog", "final_url": source_url, "transport": "httpx_http1"},
            )
        if total == 0 and products == []:
            return []
        if total > 0 and not products:
            raise AdapterError(
                "Myntra returned an inconsistent search response",
                reason_code="catalog_contract_changed",
                diagnostics={"stage": "catalog", "final_url": source_url, "transport": "httpx_http1"},
            )

        offers: list[Offer] = []
        failures = 0
        requested = normalize_size(request.uk_size)
        for product in products[:8]:
            try:
                name = str(product["productName"] or product["product"]).strip()
                listed = parse_inr_paise(product["mrp"])
                sale = parse_inr_paise(product.get("price") or product["mrp"])
                if sale > listed:
                    raise ValueError
                sizes = {
                    normalize_size(value.strip())
                    for value in str(product.get("sizes") or "").split(",") if value.strip()
                }
                images = product.get("images") or []
                image = next((item.get("src") for item in images if item.get("view") in {"default", "search"} and item.get("src")), None)
                if image and image.startswith("http://"):
                    image = "https://" + image.removeprefix("http://")
                path = str(product["landingPageUrl"]).lstrip("/")
                brand = str(product.get("brand") or request.brand or "") or None
                offers.append(Offer(
                    retailer=self.definition.name,
                    product_name=name,
                    brand=brand,
                    model=self._myntra_model(name, brand, request),
                    colourway=product.get("primaryColour"),
                    category=classify_category(
                        category=product.get("category"), product_type=(product.get("articleType") or {}).get("typeName"),
                        title=name, url=path,
                    ),
                    department=extract_department(gender=product.get("gender"), title=name, url=path),
                    image_url=image,
                    style_code=str(product["productId"]),
                    requested_uk_size=requested,
                    size_available=requested in sizes,
                    stock_status="in_stock" if requested in sizes else "out_of_stock",
                    listed_price_paise=listed,
                    automatic_discount_paise=listed - sale,
                    shipping_paise=None,
                    effective_price_paise=effective_price(listed, listed - sale),
                    product_url=f"https://www.myntra.com/{path}",
                    return_policy="Confirm the current Myntra return window and seller on the product page.",
                    match_score=0,
                    last_checked=datetime.now(timezone.utc),
                ))
            except (KeyError, TypeError, ValueError):
                failures += 1
        if failures and offers:
            raise PartialResultError(
                f"Myntra: {failures} of {len(products[:8])} products did not match the catalog contract",
                offers=offers, reason_code="partial_results",
                diagnostics={"stage": "product", "final_url": source_url, "transport": "httpx_http1"},
            )
        if not offers:
            raise AdapterError(
                "Myntra product extraction failed", reason_code="product_extraction_failed",
                diagnostics={"stage": "product", "final_url": source_url, "transport": "httpx_http1"},
            )
        return offers

    @staticmethod
    def _myntra_model(name: str, brand: str | None, request: SearchRequest) -> str:
        """Remove only structured merchandising suffixes from an exact query title."""
        from ..normalization import normalize_text

        title_tokens = normalize_text(name).split()
        brand_tokens = normalize_text(brand).split()
        if brand_tokens and title_tokens[:len(brand_tokens)] == brand_tokens:
            title_tokens = title_tokens[len(brand_tokens):]
        query_tokens = canonical_query(request, include_brand=False).split()
        descriptors = {
            "men", "mens", "women", "womens", "unisex", "kids", "boys", "girls",
            "lace", "ups", "running", "sports", "sportstyle", "casual", "shoes",
            "shoe", "sneakers", "sneaker",
        }
        if title_tokens[:len(query_tokens)] == query_tokens and all(
            token in descriptors for token in title_tokens[len(query_tokens):]
        ):
            return " ".join(query_tokens)
        return name

    async def _search_once(self, request: SearchRequest) -> list[Offer]:
        query = canonical_query(request, include_brand=self.definition.kind in {"boutique", "marketplace"})
        search_url = self.definition.search_url.format(query=quote_plus(query))

        # Do not probe browser-backed storefronts with the shared HTTP client.
        # A number of retailers reject non-browser requests while allowing an
        # ordinary browser navigation.  Treating that probe as authoritative
        # prevents Chromium from ever getting a chance to load the storefront.
        context = None
        try:
            from ..config import settings
            saved_state = settings.browser_sessions_dir / f"{self.definition.id}.json"
            try:
                usable_state = saved_state.exists() and assisted_sessions.state_for(self.definition.id) == "active"
                context = await self.pool.context(str(saved_state) if usable_state else None)
            except TypeError:
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
            selector = PRODUCT_LINK_SELECTORS.get(
                self.definition.id,
                'a[href*="/product"],a[href*="/products/"],a[href*="/p/"]',
            )
            cards = await page.locator(selector).evaluate_all(
                "els => els.map(e => ({href:e.href, text:(e.innerText || e.getAttribute('aria-label') || '')})).filter(x => x.href).slice(0, 12)"
            )
            query_words = set(canonical_query(request, include_brand=False).split())
            links: list[str] = []
            for card in cards:
                link = card if isinstance(card, str) else card.get("href")
                card_text = "" if isinstance(card, str) else str(card.get("text") or "").lower()
                # Empty card text is retained because many retailer cards put
                # the title in a client-rendered child that is not available at
                # this point.  Otherwise require at least one canonical token.
                if link and (not card_text or any(word in card_text for word in query_words)) and link not in links:
                    links.append(link)
            if not links:
                if re.search(r"no (?:products|results|matches)|0 (?:products|results)|nothing found", body, re.I):
                    return []
                raise AdapterError(
                    f"{self.definition.name} returned an unrecognized catalog shell",
                    reason_code="catalog_shell",
                )
            # Detail requests are bounded and deliberately limited to two
            # concurrent pages so a marketplace cannot turn one search into a
            # burst of requests.
            detail_sem = asyncio.Semaphore(2)
            async def collect_detail(link: str) -> Offer | None:
                async with detail_sem:
                    detail_page = await context.new_page()
                    try:
                        response = await detail_page.goto(link, wait_until="domcontentloaded", timeout=10_000)
                        if response and response.status == 404:
                            return None
                        await detail_page.wait_for_timeout(500)
                        text = await detail_page.locator("body").inner_text()
                        if detect_challenge(text):
                            raise RetailerBlockedError(
                                f"{self.definition.name} presented a verification challenge",
                                reason_code="verification_challenge", circuit_state="open",
                            )
                        return await self._extract_product(detail_page, request, link)
                    finally:
                        await detail_page.close()
            batches = await asyncio.gather(*(collect_detail(link) for link in links[:8]), return_exceptions=True)
            if any(isinstance(item, RetailerBlockedError) for item in batches):
                raise next(item for item in batches if isinstance(item, RetailerBlockedError))
            offers = [item for item in batches if isinstance(item, Offer)]
            failures = [item for item in batches if isinstance(item, Exception)]
            if failures and offers:
                raise PartialResultError(
                    f"{self.definition.name}: {len(failures)} of {len(batches)} products could not be collected",
                    offers=offers, reason_code="partial_results",
                )
            if failures:
                raise failures[0]
            if links and not offers:
                raise AdapterError(
                    f"{self.definition.name} product extraction failed",
                    reason_code="product_extraction_failed",
                )
            return offers
        except PlaywrightTimeoutError as exc:
            raise AdapterError(
                f"{self.definition.name} browser page timed out", reason_code="retailer_timeout"
            ) from exc
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
                net_error = "ERR_HTTP2_PROTOCOL_ERROR" if "ERR_HTTP2_PROTOCOL_ERROR" in message else "HTTP2"
                raise AdapterError(
                    f"{self.definition.name} could not establish a browser connection",
                    reason_code="transport_protocol",
                    diagnostics={
                        "error_type": type(exc).__name__, "final_url": search_url,
                        "net_error": net_error, "stage": "navigation", "transport": "chromium",
                    },
                ) from exc
            # Generic net errors
            if "net::ERR_" in message:
                err_code = message.split("net::ERR_")[1].split()[0] if "net::ERR_" in message else "UNKNOWN"
                raise AdapterError(
                    f"{self.definition.name} could not establish a browser connection",
                    reason_code="browser_network_error",
                    diagnostics={
                        "error_type": type(exc).__name__, "final_url": search_url,
                        "net_error": f"ERR_{err_code}", "stage": "navigation", "transport": "chromium",
                    },
                ) from exc
            # Generic browser error with type
            short_msg = message[:100] if len(message) > 100 else message
            raise AdapterError(
                f"{self.definition.name} browser collection failed ({type(exc).__name__}): {short_msg}",
                reason_code="browser_collection_failed",
                diagnostics={
                    "error_type": type(exc).__name__, "final_url": search_url,
                    "stage": "browser_collection", "transport": "chromium",
                },
            ) from exc
        finally:
            if context is not None:
                await self.pool.release(context)

    async def _extract_product(self, page, request: SearchRequest, url: str) -> Offer | None:
        data = await page.evaluate(r"""(size) => {
          const text = document.body?.innerText || '';
          const prop = name => document.querySelector(`meta[property="${name}"]`)?.content || '';
          const item = name => document.querySelector(`[itemprop="${name}"]`)?.content || document.querySelector(`[itemprop="${name}"]`)?.innerText || '';
          const named = name => document.querySelector(`meta[name="${name}"]`)?.content || '';
          const h1 = document.querySelector('h1')?.innerText?.trim() || prop('og:title') || document.title;
          const candidates = [...document.querySelectorAll('button,[role="button"],li,[data-size],span')]
            .filter(e => (e.innerText || e.dataset?.size || '').trim().match(new RegExp('^(UK\\s*)?' + size.replace('.', '\\.') + '$', 'i')));
          const inStock = candidates.some(e => !e.disabled && e.getAttribute('aria-disabled') !== 'true' &&
            !/sold|disable|unavailable|out.of.stock/i.test(`${e.className} ${e.parentElement?.className || ''}`));
          const json = [...document.querySelectorAll('script[type="application/ld+json"]')].map(e => e.textContent);
          return { text, name:h1, image:prop('og:image'), price:prop('product:price:amount') || named('twitter:data1'), inStock, json,
            category: prop('product:category') || item('category'), department: named('department') || item('audience') };
        }""", normalize_size(request.uk_size))
        return self._offer_from_snapshot(data, request, url)

    def _offer_from_snapshot(self, data: dict, request: SearchRequest, url: str) -> Offer | None:
        text, name = data.get("text", ""), data.get("name", "")
        structured: dict = {}
        raw_json = data.get("json")
        if raw_json:
            try:
                decoded = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                if isinstance(decoded, list):
                    nodes = []
                    for item in decoded:
                        if isinstance(item, str):
                            try:
                                item = json.loads(item)
                            except (TypeError, ValueError):
                                continue
                        nodes.append(item)
                else:
                    nodes = [decoded]
                def product_node(node):
                    if isinstance(node, dict):
                        node_type = node.get("@type")
                        if node_type == "Product" or (isinstance(node_type, list) and "Product" in node_type):
                            return node
                        for child_key in ("@graph", "item", "itemListElement"):
                            found = product_node(node.get(child_key))
                            if found:
                                return found
                    elif isinstance(node, list):
                        for child in node:
                            found = product_node(child)
                            if found:
                                return found
                    return {}
                structured = next((found for found in (product_node(node) for node in nodes) if found), {})
            except (TypeError, ValueError, json.JSONDecodeError):
                structured = {}
        structured_offers = structured.get("offers") if isinstance(structured, dict) else {}
        if isinstance(structured_offers, list):
            structured_offers = structured_offers[0] if structured_offers else {}
        if not isinstance(structured_offers, dict):
            structured_offers = {}
        currency = str(structured_offers.get("priceCurrency", "INR")).upper()
        if currency not in {"INR", "RS", "₹"}:
            return None
        name = name or str(structured.get("name") or "")
        price_matches = re.findall(r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]*(?:\.\d{1,2})?)", text, re.I)
        raw_price = data.get("price") or structured_offers.get("price") or structured_offers.get("lowPrice") or (price_matches[0] if price_matches else None)
        if not name or raw_price is None:
            return None
        listed = parse_inr_paise(raw_price)
        structured_brand = structured.get("brand")
        if isinstance(structured_brand, dict):
            structured_brand = structured_brand.get("name")
        structured_image = structured.get("image")
        if isinstance(structured_image, list):
            structured_image = structured_image[0] if structured_image else None
        if isinstance(structured_image, dict):
            structured_image = structured_image.get("url")
        mentioned = recognized_brands(str(structured_brand or "") + " " + name + " " + text[:500])
        canonical = next(iter(mentioned)) if len(mentioned) == 1 else None
        brand = request.brand or (canonical.title() if canonical else None)
        if canonical == "new balance":
            brand = "New Balance"
        elif canonical == "onitsuka tiger":
            brand = "Onitsuka Tiger"
        colour_match = re.search(r"\b(black|white|grey|gray|red|green|navy|blue|pink|beige|brown)\b", name, re.I)
        colourway = structured.get("color") or (colour_match.group(1).title() if colour_match else None)
        seller_match = re.search(r"Sold By\s*\n?([^\n]+)", text, re.I)
        style_match = re.search(r"(?:style|product)\s*(?:code|id)?\s*[:#-]?\s*([A-Z0-9-]{5,})", text, re.I)
        structured_code = structured.get("sku") or structured.get("mpn")
        style_code = style_match.group(1) if style_match else (structured_code or url.rstrip("/").split("/")[-1].split("?")[0])
        conditional: list[ConditionalOffer] = []
        coupon = re.search(r"(?:Use Code|Get it for)\s*\n?([^\n]{2,80})", text, re.I)
        if coupon:
            conditional.append(ConditionalOffer(kind="coupon", description=coupon.group(0).replace("\n", " ")))
        return Offer(
            retailer=self.definition.name, seller=seller_match.group(1).strip() if seller_match else None,
            product_name=name, brand=brand, model=name,
            colourway=colourway,
            category=classify_category(category=data.get("category") or structured.get("category"), title=name, url=url),
            department=extract_department(department=data.get("department") or structured.get("gender") or structured.get("audience"), title=name, url=url),
            image_url=data.get("image") or structured_image or None,
            style_code=str(style_code) if style_code else None,
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
        category_meta = soup.select_one('meta[property="product:category"],meta[itemprop="category"],*[itemprop="category"]')
        department_meta = soup.select_one('meta[name="department"],meta[itemprop="audience"],*[itemprop="audience"]')
        ld_json = [node.get_text() for node in soup.select('script[type="application/ld+json"]')]
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
            "category": (category_meta.get("content") if category_meta and category_meta.has_attr("content") else category_meta.get_text(" ", strip=True) if category_meta else None),
            "department": (department_meta.get("content") if department_meta and department_meta.has_attr("content") else department_meta.get_text(" ", strip=True) if department_meta else None),
            "json": ld_json,
        }, request, source_url)
        return [offer] if offer else []
