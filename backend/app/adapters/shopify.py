import asyncio
from datetime import datetime, timezone
import json
from urllib.parse import quote_plus, urlencode, urljoin, urlsplit

from .base import AdapterError, RetailerAdapter, RetailerDefinition, shared_client
from ..normalization import canonical_query, classify_category, effective_price, extract_department, normalize_size
from ..schemas import Offer, SearchRequest


class ShopifyCatalogAdapter(RetailerAdapter):
    """Shopify predictive search plus the public storefront product JSON."""

    def __init__(self, definition: RetailerDefinition) -> None:
        self.definition = definition
        parsed = urlsplit(definition.search_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        params = urlencode({
            "q": canonical_query(request, include_brand=True),
            "resources[type]": "product",
            "resources[limit]": "6",
        })
        response = await shared_client.get(f"{self.origin}/search/suggest.json?{params}")
        links = self.parse_suggestions(response.text)[:12]
        semaphore = asyncio.Semaphore(2)

        async def collect(link: str) -> Offer | None:
            product_url = urljoin(self.origin, link).split("?", 1)[0]
            async with semaphore:
                product_response = await shared_client.get(f"{product_url}.js")
            return self.parse_product(product_response.text, request, product_url)

        results = await asyncio.gather(*(collect(link) for link in links[:8]), return_exceptions=True)
        offers = [offer for offer in results if isinstance(offer, Offer)]
        failures = sum(isinstance(item, Exception) for item in results)
        if failures and offers:
            from .base import PartialResultError
            raise PartialResultError(
                f"{self.definition.name}: {failures} of {len(results)} products could not be collected",
                offers=offers, reason_code="partial_results",
            )
        if failures:
            raise next(item for item in results if isinstance(item, Exception))
        if links and not offers:
            raise AdapterError(
                f"{self.definition.name} product extraction failed",
                reason_code="product_extraction_failed",
            )
        return offers

    def parse_suggestions(self, payload: str) -> list[str]:
        try:
            document = json.loads(payload)
            products = document["resources"]["results"]["products"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AdapterError(
                f"{self.definition.name} returned an unreadable catalog response",
                reason_code="malformed_catalog",
            ) from exc
        if not isinstance(products, list):
            raise AdapterError(
                f"{self.definition.name} catalog response changed",
                reason_code="catalog_contract_changed",
            )
        links: list[str] = []
        for product in products:
            if not isinstance(product, dict):
                continue
            link = product.get("url") or (f"/products/{product['handle']}" if product.get("handle") else None)
            if link and str(link) not in links:
                links.append(str(link))
        if products and not links:
            raise AdapterError(
                f"{self.definition.name} catalog response changed",
                reason_code="catalog_contract_changed",
            )
        return links

    def parse_product(self, payload: str, request: SearchRequest, product_url: str) -> Offer | None:
        try:
            product = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AdapterError(
                f"{self.definition.name} returned malformed product data",
                reason_code="malformed_product",
            ) from exc
        if not isinstance(product, dict) or not product.get("title") or not isinstance(product.get("variants"), list):
            raise AdapterError(
                f"{self.definition.name} returned malformed product data",
                reason_code="malformed_product",
            )
        requested = normalize_size(request.uk_size)
        option_names = [str(item.get("name", "")).lower() for item in product.get("options") or [] if isinstance(item, dict)]
        size_positions = {index for index, name in enumerate(option_names) if "size" in name}
        color_positions = {index for index, name in enumerate(option_names) if "color" in name or "colour" in name}
        matching: list[dict] = []
        for variant in product["variants"]:
            values = variant.get("options") or [variant.get("option1"), variant.get("option2"), variant.get("option3")]
            candidates = [values[index] for index in size_positions if index < len(values)] if size_positions else values
            for value in candidates:
                try:
                    normalized = normalize_size(str(value).upper().replace("UK", "").strip())
                except ValueError:
                    continue
                if normalized == requested:
                    matching.append(variant)
                    break
        chosen = next((variant for variant in matching if variant.get("available")), None)
        chosen = chosen or (matching[0] if matching else None)
        fallback = product["variants"][0] if product["variants"] else {}
        pricing = chosen or fallback
        try:
            sale = int(pricing.get("price") or product.get("price") or 0)
            listed = int(pricing.get("compare_at_price") or product.get("compare_at_price") or sale)
        except (TypeError, ValueError) as exc:
            raise AdapterError(
                f"{self.definition.name} returned malformed product pricing",
                reason_code="malformed_product",
            ) from exc
        if sale <= 0:
            return None
        values = (chosen or fallback).get("options") or []
        colour = next((values[index] for index in color_positions if index < len(values)), None)
        images = product.get("images") or []
        featured = (chosen or {}).get("featured_image") or product.get("featured_image") or (images[0] if images else None)
        if isinstance(featured, dict):
            featured = featured.get("src")
        brand = str(product.get("vendor") or "") or None
        return Offer(
            retailer=self.definition.name, seller=self.definition.name,
            product_name=str(product["title"]), brand=brand, model=str(product["title"]),
            colourway=str(colour) if colour else None,
            category=classify_category(title=product.get("title"), tags=product.get("tags") or (), url=product_url),
            department=extract_department(title=product.get("title"), tags=product.get("tags") or (), url=product_url),
            image_url=urljoin(product_url, str(featured)) if featured else None,
            style_code=str((chosen or fallback).get("sku") or product.get("id") or "") or None,
            requested_uk_size=requested,
            size_available=bool(chosen and chosen.get("available")),
            stock_status=("in_stock" if chosen and chosen.get("available") else "out_of_stock" if matching else "unknown"),
            listed_price_paise=max(listed, sale), automatic_discount_paise=max(0, listed - sale),
            shipping_paise=None, effective_price_paise=effective_price(max(listed, sale), max(0, listed-sale)),
            product_url=product_url,
            return_policy=f"Confirm {self.definition.name}'s current return eligibility on the product page.",
            match_score=0, last_checked=datetime.now(timezone.utc),
        )

    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        offer = self.parse_product(payload, request, source_url)
        return [offer] if offer else []
