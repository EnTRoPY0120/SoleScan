import json
import re
from datetime import datetime, timezone

from .base import AdapterError, PartialResultError, RetailerAdapter, RetailerDefinition, shared_client
from ..normalization import effective_price, extract_department, normalize_size, parse_inr_paise
from ..schemas import Offer, ProductCategory, SearchRequest


PRODUCT_SEARCH = """
query ProductSearch($search: String!) {
  products(search: $search, currentPage: 1, pageSize: 8) {
    total_count
    items {
      __typename name sku url_key stock_status product_sub_title
      small_image { url }
      price_range {
        minimum_price {
          regular_price { value currency }
          final_price { value currency }
        }
      }
      ... on ConfigurableProduct {
        configurable_options { attribute_code values { value_index label } }
        variants { attributes { code value_index } product { sku stock_status } }
      }
    }
  }
}
"""


class AsicsAdapter(RetailerAdapter):
    """ASICS India's explicit Magento GraphQL search contract."""

    definition = RetailerDefinition(
        "asics", "ASICS India", "official",
        "https://www.asics.co.in/search.html?query={query}&page=1",
        adapter_type="asics", footwear_only_scope=True,
    )

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        response = await shared_client.post_json(
            "https://www.asics.co.in/graphql",
            {"query": PRODUCT_SEARCH, "operationName": "ProductSearch", "variables": {"search": request.query}},
            headers={"Content-Type": "application/json", "Store": "default"},
        )
        return self.parse(response.text, request, str(response.url))

    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        try:
            root = json.loads(payload)
            products = root["data"]["products"]
            total = products["total_count"]
            items = products["items"]
            if not isinstance(total, int) or not isinstance(items, list):
                raise TypeError
        except (json.JSONDecodeError, KeyError, TypeError):
            raise AdapterError(
                "ASICS India returned an unrecognized product-search response",
                reason_code="catalog_contract_changed",
                diagnostics={"stage": "catalog", "operation": "ProductSearch"},
            )
        if total == 0 and items == []:
            return []
        if total > 0 and not items:
            raise AdapterError(
                "ASICS India returned an inconsistent product-search response",
                reason_code="catalog_contract_changed",
                diagnostics={"stage": "catalog", "operation": "ProductSearch"},
            )

        offers: list[Offer] = []
        failures = 0
        for item in items:
            try:
                offers.append(self._to_offer(item, request))
            except (KeyError, TypeError, ValueError):
                failures += 1
        if failures and offers:
            raise PartialResultError(
                f"ASICS India: {failures} of {len(items)} products did not match the catalog contract",
                offers=offers, reason_code="partial_results",
                diagnostics={"stage": "product", "operation": "ProductSearch"},
            )
        if not offers:
            raise AdapterError(
                "ASICS India product extraction failed",
                reason_code="product_extraction_failed",
                diagnostics={"stage": "product", "operation": "ProductSearch"},
            )
        return offers

    def _to_offer(self, item: dict, request: SearchRequest) -> Offer:
        name = str(item["name"]).strip()
        sku = str(item["sku"]).strip()
        url_key = str(item["url_key"]).strip()
        prices = item["price_range"]["minimum_price"]
        regular = prices["regular_price"]
        final = prices["final_price"]
        if str(regular.get("currency", "INR")).upper() != "INR" or str(final.get("currency", "INR")).upper() != "INR":
            raise ValueError("unexpected currency")
        listed = parse_inr_paise(regular["value"])
        final_price = parse_inr_paise(final["value"])
        if final_price > listed:
            raise ValueError("invalid price range")

        requested = normalize_size(request.uk_size)
        size_values: dict[int, str] = {}
        for option in item.get("configurable_options") or []:
            if option.get("attribute_code") != "size":
                continue
            for value in option.get("values") or []:
                normalized = self._uk_size(value.get("label"))
                if normalized:
                    size_values[int(value["value_index"])] = normalized
        matching_statuses: list[str] = []
        for variant in item.get("variants") or []:
            indexes = [
                int(attribute["value_index"])
                for attribute in variant.get("attributes") or []
                if attribute.get("code") == "size"
            ]
            if any(size_values.get(index) == requested for index in indexes):
                matching_statuses.append(str((variant.get("product") or {}).get("stock_status", "")))
        if matching_statuses:
            stock_status = "in_stock" if "IN_STOCK" in matching_statuses else "out_of_stock"
        elif requested in size_values.values():
            stock_status = "out_of_stock"
        else:
            stock_status = "unknown"

        subtitle = str(item.get("product_sub_title") or "")
        image = item.get("small_image") or {}
        return Offer(
            retailer=self.definition.name,
            seller="ASICS India",
            product_name=name,
            brand="ASICS",
            model=name,
            category=ProductCategory.footwear,
            department=extract_department(title=f"{name} {subtitle}"),
            image_url=str(image.get("url")) if image.get("url") else None,
            style_code=sku,
            requested_uk_size=requested,
            size_available=stock_status == "in_stock",
            stock_status=stock_status,
            listed_price_paise=listed,
            automatic_discount_paise=listed - final_price,
            shipping_paise=None,
            effective_price_paise=effective_price(listed, listed - final_price),
            product_url=f"https://www.asics.co.in/{url_key}.html",
            return_policy="Confirm the current ASICS India return window on the product page.",
            match_score=0,
            last_checked=datetime.now(timezone.utc),
        )

    @staticmethod
    def _uk_size(label: object) -> str | None:
        match = re.search(r"UK\s*(\d+)(H)?\b", str(label or ""), re.I)
        if not match:
            return None
        value = f"{match.group(1)}.5" if match.group(2) else match.group(1)
        return normalize_size(value)
