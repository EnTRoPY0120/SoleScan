import json
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import AdapterError, RetailerAdapter, RetailerDefinition, build_search_url, shared_client
from ..normalization import effective_price, normalize_size, parse_inr_paise
from ..schemas import ConditionalOffer, Offer, SearchRequest


class StructuredDataAdapter(RetailerAdapter):
    """Safe default adapter for retailer search pages and embedded schema.org data."""

    def __init__(self, definition: RetailerDefinition) -> None:
        self.definition = definition

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        if self.definition.uses_browser:
            raise AdapterError("This retailer requires an interactive browser; browser collection is unavailable")
        url = build_search_url(self.definition.search_url, request)
        response = await shared_client.get(url)
        return self.parse(response.text, request, str(response.url))

    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        soup = BeautifulSoup(payload, "html.parser")
        products: list[dict] = []
        explicit_empty = False
        recognized = False
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            found = self._find_products(data)
            products.extend(found)
            if found:
                recognized = True
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                recognized = True
                entries = data.get("itemListElement")
                explicit_empty = entries == [] or data.get("numberOfItems") == 0
        if not recognized:
            raise AdapterError(
                f"{self.definition.name} returned an unrecognized catalog shell",
                reason_code="catalog_shell",
            )
        if not products and explicit_empty:
            return []
        offers: list[Offer] = []
        for product in products:
            built = self._to_offer(product, request, source_url)
            if built:
                offers.append(built)
        if products and not offers:
            raise AdapterError(
                f"{self.definition.name} product extraction failed",
                reason_code="product_extraction_failed",
            )
        return offers

    def _find_products(self, node: object) -> list[dict]:
        found: list[dict] = []
        if isinstance(node, list):
            for child in node:
                found.extend(self._find_products(child))
        elif isinstance(node, dict):
            node_type = node.get("@type")
            if node_type == "Product" or (isinstance(node_type, list) and "Product" in node_type):
                found.append(node)
            for key in ("@graph", "itemListElement", "item"):
                if key in node:
                    found.extend(self._find_products(node[key]))
        return found

    def _to_offer(self, product: dict, request: SearchRequest, source_url: str) -> Offer | None:
        raw_offer = product.get("offers") or {}
        if isinstance(raw_offer, list):
            raw_offer = raw_offer[0] if raw_offer else {}
        if not isinstance(raw_offer, dict):
            return None
        currency = str(raw_offer.get("priceCurrency", "INR")).upper()
        if currency not in {"INR", "RS", "₹"}:
            return None
        price = raw_offer.get("price") or raw_offer.get("lowPrice")
        if price is None:
            return None
        try:
            listed = parse_inr_paise(price)
        except ValueError:
            return None
        requested_size = normalize_size(request.uk_size)
        availability = str(raw_offer.get("availability", "")).lower()
        sizes = product.get("sizes") or product.get("size") or []
        if isinstance(sizes, str):
            sizes = [part.strip() for part in sizes.split(",")]
        normalized_sizes: set[str] = set()
        for value in sizes:
            try:
                normalized_sizes.add(normalize_size(str(value)))
            except ValueError:
                pass
        if normalized_sizes:
            stock_status = "in_stock" if requested_size in normalized_sizes else "out_of_stock"
        elif "outofstock" in availability:
            stock_status = "out_of_stock"
        else:
            stock_status = "unknown"
        size_available = stock_status == "in_stock"
        image = product.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, dict):
            image = image.get("url")
        brand = product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        seller = raw_offer.get("seller")
        if isinstance(seller, dict):
            seller = seller.get("name")
        shipping = raw_offer.get("shippingDetails", {}).get("shippingRate", {}).get("value") if isinstance(raw_offer.get("shippingDetails"), dict) else None
        shipping_paise = parse_inr_paise(shipping) if shipping is not None else None
        auto_discount = parse_inr_paise(product.get("automaticDiscount", 0))
        conditional: list[ConditionalOffer] = []
        for promo in product.get("conditionalOffers", []):
            if isinstance(promo, dict) and promo.get("description"):
                conditional.append(ConditionalOffer(**promo))
        return Offer(
            retailer=self.definition.name,
            seller=str(seller) if seller else None,
            product_name=str(product.get("name") or "Unnamed product"),
            brand=str(brand) if brand else None,
            model=product.get("model"),
            colourway=product.get("color"),
            image_url=str(image) if image else None,
            style_code=product.get("sku") or product.get("mpn"),
            requested_uk_size=requested_size,
            size_available=size_available,
            stock_status=stock_status,
            listed_price_paise=listed,
            automatic_discount_paise=auto_discount,
            shipping_paise=shipping_paise,
            effective_price_paise=effective_price(listed, auto_discount, shipping_paise),
            conditional_offers=conditional,
            product_url=urljoin(source_url, str(raw_offer.get("url") or product.get("url") or source_url)),
            return_policy=product.get("returnPolicy") or "Confirm the current return policy with the retailer.",
            match_score=0,
            last_checked=datetime.now(timezone.utc),
        )
