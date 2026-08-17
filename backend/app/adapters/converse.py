import json
import re
from datetime import datetime, timezone

from .base import AdapterError, RetailerAdapter, RetailerDefinition, shared_client
from ..normalization import canonical_query, classify_category, effective_price, extract_department, normalize_size, parse_inr_paise
from ..schemas import Offer, SearchRequest


QUERY = """query Search($q:String!){products(search:$q,pageSize:12){items{
name sku url_key url_suffix stock_status small_image{url}
price_range{minimum_price{regular_price{value currency} final_price{value currency} discount{amount_off}}}
... on ConfigurableProduct{configurable_options{attribute_code label values{label value_index}}
variants{attributes{code value_index} product{sku stock_status}}}}}}"""


class ConverseAdapter(RetailerAdapter):
    definition = RetailerDefinition(
        "converse", "Converse India", "official",
        "https://www.converse.in/search.html?query={query}", footwear_only_scope=True,
    )

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        # The official catalog already scopes the brand; a stale optional brand
        # filter must not contaminate an otherwise precise Converse model query.
        query = canonical_query(request, include_brand=False)
        response = await shared_client.post_json(
            "https://www.converse.in/graphql", {"query": QUERY, "variables": {"q": query}}
        )
        return self.parse(response.text, request, "https://www.converse.in/")

    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        try:
            document = json.loads(payload)
            products = document["data"]["products"]["items"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AdapterError("Converse returned an unreadable catalog response") from exc
        requested = normalize_size(request.uk_size)
        results: list[Offer] = []
        for product in products:
            price = product.get("price_range", {}).get("minimum_price", {})
            final = price.get("final_price", {})
            regular = price.get("regular_price", {})
            if final.get("currency") != "INR":
                continue
            listed = parse_inr_paise(regular.get("value", final.get("value")))
            final_paise = parse_inr_paise(final.get("value"))
            size_indexes: set[int] = set()
            colourway = None
            for option in product.get("configurable_options") or []:
                if option.get("attribute_code") == "size":
                    for value in option.get("values") or []:
                        label = str(value.get("label", ""))
                        try:
                            if normalize_size(label.replace("UK", "")) == requested:
                                size_indexes.add(int(value["value_index"]))
                        except (ValueError, KeyError):
                            pass
            available = False
            for variant in product.get("variants") or []:
                indexes = {int(x["value_index"]) for x in variant.get("attributes") or [] if x.get("code") == "size"}
                if indexes & size_indexes and variant.get("product", {}).get("stock_status") == "IN_STOCK":
                    available = True
                    break
            sku = str(product.get("sku") or "")
            url_key = str(product.get("url_key") or "")
            match = re.search(r"-(black|white|grey|gray|red|green|navy|blue|pink)(?:-|$)", url_key, re.I)
            if match:
                colourway = match.group(1).title()
            results.append(Offer(
                retailer=self.definition.name, seller="Converse India",
                product_name=str(product.get("name") or "Converse sneaker"), brand="Converse",
                model=str(product.get("name") or ""), colourway=colourway,
                category="footwear",
                department=extract_department(title=product.get("name"), url=url_key),
                image_url=(product.get("small_image") or {}).get("url"), style_code=sku,
                requested_uk_size=requested, size_available=available,
                stock_status=("in_stock" if available else "out_of_stock" if size_indexes else "unknown"),
                listed_price_paise=listed, automatic_discount_paise=max(0, listed - final_paise),
                shipping_paise=0, effective_price_paise=effective_price(listed, max(0, listed-final_paise), 0),
                product_url=f"https://www.converse.in/{url_key}{product.get('url_suffix') or '.html'}",
                return_policy="Free returns are advertised by Converse India; reconfirm eligibility on the product page.",
                match_score=0, last_checked=datetime.now(timezone.utc),
            ))
        if products and not results:
            raise AdapterError(
                "Converse product extraction failed", reason_code="product_extraction_failed"
            )
        return results
