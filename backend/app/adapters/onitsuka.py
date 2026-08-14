import asyncio
from datetime import datetime, timezone
import json
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from .base import (
    AdapterError,
    PartialResultError,
    RetailerAdapter,
    RetailerDefinition,
    shared_client,
)
from ..normalization import effective_price, normalize_size, normalize_text, parse_inr_paise
from ..schemas import Offer, SearchRequest


DETAIL_LIMIT = 6
DETAIL_TIMEOUT_SECONDS = 5
DETAIL_SEMAPHORE = asyncio.Semaphore(2)

PRODUCT_QUERY = """query Product($sku: String!) {
  products(filter: {sku: {eq: $sku}}, pageSize: 1) {
    items {
      name sku stock_status gender_for_search color_for_search
      ... on ConfigurableProduct {
        configurable_options { attribute_code values { label value_index } }
        variants { attributes { code value_index } product { sku stock_status } }
      }
    }
  }
}"""


class OnitsukaAdapter(RetailerAdapter):
    """Official Magento/Adobe catalog collector with exact variant stock."""

    definition = RetailerDefinition(
        "onitsuka_tiger",
        "Onitsuka Tiger India",
        "official",
        "https://www.onitsukatiger.com/in/en-in/catalogsearch/result/?q={query}",
        adapter_type="onitsuka",
    )

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        search_url = self.definition.search_url.format(query=quote_plus(request.query))
        response = await shared_client.get(search_url)
        products = self.parse_catalog(response.text)
        products = self._strongest(products, request)[:DETAIL_LIMIT]
        if not products:
            return []

        async def collect(product: dict) -> Offer:
            fallback = self._catalog_offer(product, request, stock_status="unknown")
            try:
                async with DETAIL_SEMAPHORE:
                    async with asyncio.timeout(DETAIL_TIMEOUT_SECONDS):
                        detail = await shared_client.post_json(
                            "https://www.onitsukatiger.com/in/en-in/graphql",
                            {
                                "operationName": "Product",
                                "query": PRODUCT_QUERY,
                                "variables": {"sku": str(product["sku"])},
                            },
                            headers={"Store": "default", "Content-Type": "application/json"},
                        )
                return self.parse_detail(detail.text, request, product)
            except (AdapterError, TimeoutError):
                return fallback

        offers = await asyncio.gather(*(collect(product) for product in products))
        unknown = sum(offer.stock_status == "unknown" for offer in offers)
        if unknown:
            raise PartialResultError(
                f"Onitsuka Tiger: size stock could not be verified for {unknown} of {len(offers)} products",
                offers=offers,
                reason_code="stock_verification_failed",
            )
        return offers

    @staticmethod
    def _decode_js_string(raw: str) -> str:
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError as exc:
            raise AdapterError(
                "Onitsuka Tiger returned malformed embedded catalog data",
                reason_code="malformed_catalog",
            ) from exc

    @classmethod
    def parse_catalog(cls, payload: str) -> list[dict]:
        # Magento Live Search server-renders Adobe's productSearch response as a
        # JavaScript string. Decode the JS escapes before decoding its JSON.
        match = re.search(r"(?:const|var)\s+rawResponse\s*=\s*\"((?:\\.|[^\"\\])*)\"\s*;", payload, re.S)
        raw: object | None = None
        if match:
            decoded = cls._decode_js_string(match.group(1))
            try:
                raw = json.loads(decoded)
            except json.JSONDecodeError as exc:
                raise AdapterError(
                    "Onitsuka Tiger returned malformed embedded catalog data",
                    reason_code="malformed_catalog",
                ) from exc
        else:
            # Deterministic fixtures may contain the response as JSON directly.
            try:
                raw = json.loads(payload)
            except json.JSONDecodeError:
                soup = BeautifulSoup(payload, "html.parser")
                for script in soup.find_all("script"):
                    text = script.string or script.get_text()
                    if "productSearch" not in text:
                        continue
                    try:
                        candidate = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    raw = candidate
                    break
        try:
            search = raw["data"]["productSearch"]  # type: ignore[index]
            items = search["items"]
            total = search["total_count"]
        except (KeyError, TypeError) as exc:
            raise AdapterError(
                "Onitsuka Tiger catalog response changed",
                reason_code="catalog_contract_changed",
            ) from exc
        if not isinstance(items, list) or not isinstance(total, int):
            raise AdapterError(
                "Onitsuka Tiger catalog response changed",
                reason_code="catalog_contract_changed",
            )
        products: list[dict] = []
        for item in items:
            product = item.get("product") if isinstance(item, dict) else None
            if isinstance(product, dict) and all(product.get(key) is not None for key in ("sku", "name", "canonical_url", "price_range")):
                products.append(product)
        if items and not products:
            raise AdapterError(
                "Onitsuka Tiger product extraction failed",
                reason_code="product_extraction_failed",
            )
        return products

    @staticmethod
    def _strongest(products: list[dict], request: SearchRequest) -> list[dict]:
        wanted = set(normalize_text(" ".join(filter(None, [request.query, request.colourway]))).split())

        def score(product: dict) -> tuple[int, int]:
            text = set(normalize_text(" ".join(str(product.get(k) or "") for k in ("name", "sku"))).split())
            return (len(wanted & text), -len(text - wanted))

        return sorted(products, key=score, reverse=True)

    @staticmethod
    def _url(product: dict) -> str:
        raw = str(product.get("canonical_url") or "")
        return urljoin("https://www.onitsukatiger.com", raw if not raw.startswith("//") else f"https:{raw}")

    @staticmethod
    def _gender(product: dict, detail: object | None = None) -> str:
        values = [product.get("gender"), product.get("gender_for_search")]
        if isinstance(detail, dict):
            products = detail.get("products")
            if isinstance(products, dict) and isinstance(products.get("items"), list) and products["items"]:
                detail = products["items"][0]
            values += [detail.get("gender"), detail.get("gender_for_search")]
        joined = " ".join(str(value or "") for value in values).lower()
        if "women" in joined and not any(word in joined for word in ("unisex", "men, women", "men/women")):
            return "women"
        if "kid" in joined:
            return "kids"
        return "men"

    @staticmethod
    def us_to_uk(label: str, gender: str) -> str | None:
        raw = label.upper().replace("½", ".5")
        if gender == "kids" or re.search(r"\bK\d", raw):
            return None
        pattern = r"WOM(?:E)?N(?:'S)?\s*US\s*(\d+(?:\.5)?)" if gender == "women" else r"MEN(?:'S|S)?\s*US\s*(\d+(?:\.5)?)"
        match = re.search(pattern, raw)
        if not match:
            match = re.search(r"\bUS\s*(\d+(?:\.5)?)", raw)
        if not match:
            return None
        us = float(match.group(1))
        uk = us - (2 if gender == "women" else 1)
        try:
            return normalize_size(uk)
        except ValueError:
            return None

    @classmethod
    def _stock_from_magento(cls, detail: dict, requested: str, gender: str) -> str:
        products = detail.get("products", {}).get("items") if isinstance(detail.get("products"), dict) else None
        product = products[0] if isinstance(products, list) and products else detail
        options = product.get("configurable_options") or product.get("options") or product.get("attributes") or []
        if isinstance(options, dict):
            options = list(options.values())
        wanted_indexes: set[str] = set()
        wanted_products: set[str] = set()
        for option in options:
            code = str(option.get("attribute_code") or option.get("code") or option.get("id") or "").lower()
            if "size" not in code:
                continue
            for value in option.get("values") or option.get("options") or []:
                label = str(value.get("label") or value.get("title") or value.get("id") or "")
                converted = cls.us_to_uk(label, gender)
                if converted == requested:
                    wanted_indexes.add(str(value.get("value_index") or value.get("id") or label))
                    wanted_products.update(str(item) for item in value.get("products") or [])
        # Native Magento jsonConfig identifies child variants through an index
        # and a nested salable map instead of a variants array.
        index = product.get("index") or {}
        if isinstance(index, dict) and wanted_indexes:
            for child_id, selections in index.items():
                if isinstance(selections, dict) and wanted_indexes & {str(value) for value in selections.values()}:
                    wanted_products.add(str(child_id))

        def leaf_ids(node: object) -> set[str]:
            if isinstance(node, list):
                return {str(value) for value in node}
            if isinstance(node, dict):
                return set().union(*(leaf_ids(value) for value in node.values())) if node else set()
            return set()

        if wanted_products:
            salable = leaf_ids(product.get("salable") or {})
            return "in_stock" if wanted_products & salable else "out_of_stock"
        variants = product.get("variants") or []
        matched = False
        for variant in variants:
            attrs = variant.get("attributes") or variant.get("selections") or []
            indexes = {str(x.get("value_index") or x.get("id") or x.get("value")) for x in attrs if isinstance(x, dict)}
            label = str(variant.get("size") or variant.get("label") or "")
            is_match = bool(indexes & wanted_indexes) or cls.us_to_uk(label, gender) == requested
            if not is_match:
                continue
            matched = True
            child = variant.get("product") or variant
            status = str(child.get("stock_status") or child.get("stockStatus") or "").upper()
            available = child.get("available")
            if status == "IN_STOCK" or available is True:
                return "in_stock"
        return "out_of_stock" if matched or wanted_indexes else "unknown"

    @classmethod
    def _extract_detail(cls, payload: str) -> dict:
        try:
            document = json.loads(payload)
            if isinstance(document, dict):
                if isinstance(document.get("data"), dict):
                    return document["data"]
                return document
        except json.JSONDecodeError:
            pass
        soup = BeautifulSoup(payload, "html.parser")

        def walk(node: object):
            if isinstance(node, dict):
                if isinstance(node.get("jsonConfig"), dict):
                    return node["jsonConfig"]
                for child in node.values():
                    found = walk(child)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for child in node:
                    found = walk(child)
                    if found is not None:
                        return found
            return None

        for script in soup.select('script[type="text/x-magento-init"], script[type="application/json"]'):
            try:
                found = walk(json.loads(script.string or script.get_text()))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(found, dict):
                return found
        raise AdapterError("Onitsuka Tiger product detail response changed", reason_code="product_contract_changed")

    @classmethod
    def parse_detail(cls, payload: str, request: SearchRequest, catalog: dict) -> Offer:
        detail = cls._extract_detail(payload)
        gender = cls._gender(catalog, detail)
        stock = cls._stock_from_magento(detail, normalize_size(request.uk_size), gender)
        return cls._catalog_offer(catalog, request, stock_status=stock, detail=detail)

    @classmethod
    def _catalog_offer(
        cls, catalog: dict, request: SearchRequest, *, stock_status: str, detail: dict | None = None
    ) -> Offer:
        try:
            price = catalog["price_range"]["minimum_price"]["regular_price"]["value"]
            listed = parse_inr_paise(price)
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterError("Onitsuka Tiger returned malformed INR pricing", reason_code="malformed_product") from exc
        image = catalog.get("image") or {}
        colour = catalog.get("color") or catalog.get("colourway") or catalog.get("color_for_search")
        if detail:
            detail_product = detail
            products = detail.get("products")
            if isinstance(products, dict) and isinstance(products.get("items"), list) and products["items"]:
                detail_product = products["items"][0]
            colour = colour or detail_product.get("color") or detail_product.get("color_for_search")
        return Offer(
            retailer=cls.definition.name,
            seller=cls.definition.name,
            product_name=str(catalog["name"]),
            brand="Onitsuka Tiger",
            model=str(catalog["name"]),
            colourway=str(colour) if colour else None,
            image_url=str(image.get("url")) if isinstance(image, dict) and image.get("url") else None,
            style_code=str(catalog["sku"]),
            requested_uk_size=normalize_size(request.uk_size),
            size_available=stock_status == "in_stock",
            stock_status=stock_status,
            listed_price_paise=listed,
            shipping_paise=0,
            effective_price_paise=effective_price(listed, shipping=0),
            product_url=cls._url(catalog),
            return_policy="Confirm Onitsuka Tiger India's current return eligibility on the product page.",
            match_score=0,
            last_checked=datetime.now(timezone.utc),
        )

    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        # `search()` always uses the Magento productSearch contract. This small
        # parser fallback keeps old saved JSON-LD fixtures readable without
        # allowing the live collector to mistake JSON-LD for verified stock.
        if 'type="application/ld+json"' in payload or "type='application/ld+json'" in payload:
            from .structured import StructuredDataAdapter

            return StructuredDataAdapter(self.definition).parse(payload, request, source_url)
        return [self._catalog_offer(item, request, stock_status="unknown") for item in self.parse_catalog(payload)]
