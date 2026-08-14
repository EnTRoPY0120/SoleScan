import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import AdapterError, RetailerAdapter, RetailerDefinition, shared_client
from ..normalization import effective_price, normalize_size
from ..schemas import Offer, SearchRequest


class BrandmanAdapter(RetailerAdapter):
    """New Balance catalog from its authorized Indian operator, Brandman Retail."""

    definition = RetailerDefinition(
        "new_balance", "New Balance · Brandman", "official",
        "https://brandmanretail.com/search?q={query}&type=product",
        adapter_type="brandman"
    )

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        # Brandman carries several brands, but the adapter filters product JSON
        # to New Balance. Searching only the model avoids Shopify's broad OR
        # matching for the redundant "New Balance" tokens.
        search_url = f"https://brandmanretail.com/search/suggest.json?q={quote_plus(request.query)}&resources[type]=product&resources[limit]=6"
        response = await shared_client.get(search_url)
        links = self.parse_suggestions(response.text)[:6]
        semaphore = asyncio.Semaphore(2)

        async def collect(link: str) -> Offer | None:
            product_url = link.split("?", 1)[0]
            async with semaphore:
                product = await shared_client.get(f"{product_url}.js")
            return self.parse_product(product.text, request, product_url)

        results = await asyncio.gather(*(collect(link) for link in links), return_exceptions=True)
        offers = [offer for offer in results if isinstance(offer, Offer)]
        failures = sum(isinstance(item, Exception) for item in results)
        if failures and offers:
            from .base import PartialResultError
            raise PartialResultError(
                f"Brandman: {failures} of {len(results)} products could not be collected",
                offers=offers, reason_code="partial_results",
            )
        if failures:
            raise next(item for item in results if isinstance(item, Exception))
        return offers

    @staticmethod
    def parse_suggestions(payload: str) -> list[str]:
        try:
            products = json.loads(payload)["resources"]["results"]["products"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AdapterError(
                "Brandman returned an unreadable catalog response",
                reason_code="malformed_catalog",
            ) from exc
        if not isinstance(products, list):
            raise AdapterError("Brandman catalog response changed", reason_code="catalog_contract_changed")
        links = []
        for product in products:
            link = product.get("url") if isinstance(product, dict) else None
            if not link and isinstance(product, dict) and product.get("handle"):
                link = f"/products/{product['handle']}"
            if link:
                url = urljoin("https://brandmanretail.com", str(link))
                if url not in links:
                    links.append(url)
        if products and not links:
            raise AdapterError("Brandman catalog response changed", reason_code="catalog_contract_changed")
        return links

    @staticmethod
    def parse_search_links(payload: str, source_url: str) -> list[str]:
        soup = BeautifulSoup(payload, "html.parser")
        links: list[str] = []
        anchors = soup.select('.sf__pcard a[href*="/products/"]')
        if not anchors:  # Small deterministic fixtures and future theme fallback.
            anchors = soup.select('a[href*="/products/"]')
        for anchor in anchors:
            url = urljoin(source_url, str(anchor.get("href", "")))
            clean = urlsplit(url)._replace(query="", fragment="").geturl()
            if clean not in links:
                links.append(clean)
        return links

    def parse_product(self, payload: str, request: SearchRequest, product_url: str) -> Offer | None:
        try:
            product = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AdapterError("Brandman returned malformed product data") from exc
        if not isinstance(product, dict) or not product.get("title"):
            raise AdapterError("Brandman returned malformed product data")
        if str(product.get("vendor", "")).lower() != "new balance":
            return None
        requested = normalize_size(request.uk_size)
        variants = product.get("variants") or []
        matching = []
        for variant in variants:
            options = variant.get("options") or [variant.get("option1"), variant.get("option2")]
            for option in options:
                try:
                    if normalize_size(str(option)) == requested:
                        matching.append(variant)
                        break
                except ValueError:
                    continue
        chosen = next((variant for variant in matching if variant.get("available")), None)
        chosen = chosen or (matching[0] if matching else None)
        price = int((chosen or {}).get("price") or product.get("price") or 0)
        compared = int((chosen or {}).get("compare_at_price") or product.get("compare_at_price") or price)
        if price <= 0:
            return None
        images = product.get("images") or []
        image = (chosen or {}).get("featured_image") or (images[0] if images else product.get("featured_image"))
        colour = (chosen or {}).get("option1")
        if not colour and chosen:
            colour = next((
                option for option in chosen.get("options", [])
                if not re.fullmatch(r"(?:UK\s*)?\d{1,2}(?:\.5)?", str(option), re.I)
            ), None)
        if colour and str(colour).strip() == requested:
            colour = None
        code_match = re.search(r"\(([A-Z0-9-]{5,})\)\s*$", str(product["title"]), re.I)
        style_code = code_match.group(1).upper() if code_match else ((chosen or {}).get("sku") or None)
        discount = max(0, compared - price)
        return Offer(
            retailer=self.definition.name, seller="Brandman Retail Ltd",
            product_name=str(product["title"]), brand="New Balance", model=str(product["title"]),
            colourway=str(colour) if colour else None,
            image_url=urljoin(product_url, str(image)) if image else None,
            style_code=style_code, requested_uk_size=requested,
            size_available=bool(chosen and chosen.get("available")), listed_price_paise=compared,
            stock_status=("in_stock" if chosen and chosen.get("available") else "out_of_stock" if matching else "unknown"),
            automatic_discount_paise=discount, shipping_paise=None,
            effective_price_paise=effective_price(compared, discount), conditional_offers=[],
            product_url=product_url,
            return_policy="Confirm Brandman's current return eligibility on the product page.",
            match_score=0, last_checked=datetime.now(timezone.utc),
        )

    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        offer = self.parse_product(payload, request, source_url)
        return [offer] if offer else []
