import asyncio
from datetime import datetime, timezone
import json
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .base import AdapterError, PartialResultError, RetailerAdapter, RetailerBlockedError, RetailerDefinition, shared_client
from ..normalization import canonical_query, classify_category, effective_price, extract_department, normalize_size, parse_inr_paise
from ..schemas import Offer, SearchRequest


GUEST_QUERY = """mutation GuestLogon { guestLogon { accessToken refreshToken customerId
  customerContext { hashKey customerGroups } } }"""

PRODUCT_QUERY = """query Product($id: ID!) { product(id: $id) {
  id name header slug orderable brand
  variations { id name colorValue colorName preview styleNumber orderable
    productPrice { price salePrice promotionPrice bestPrice isSalePriceElapsed }
    sizeGroups { label sizes { id label value productId orderable maxOrderableQuantity } }
    images { href alt }
  }
} }"""

PUMA_SEMAPHORE = asyncio.Semaphore(2)


class PumaAdapter(RetailerAdapter):
    definition = RetailerDefinition(
        "puma", "Puma India", "official", "https://in.puma.com/in/en/search?q={query}",
        adapter_type="puma", footwear_only_scope=True
    )

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        search_url = self.definition.search_url.format(query=quote_plus(canonical_query(request, include_brand=False)))
        response = await shared_client.get(search_url)
        master_ids, client_version = self.parse_catalog(response.text)
        catalog_ids = master_ids[:12]
        # The catalog shell is inspected broadly, but detail/size calls stay
        # bounded to eight exact candidates.
        master_ids = catalog_ids[:8]
        if not catalog_ids:
            return []
        auth = await self._guest_headers(client_version)
        
        async def _fetch_one(master_id: str) -> list[Offer] | None:
            async with PUMA_SEMAPHORE:
                try:
                    payload = await self._product(master_id, auth)
                    return self.parse(payload, request, "https://in.puma.com/in/en/")
                except RetailerBlockedError:
                    raise
                except AdapterError:
                    return None

        results = await asyncio.gather(*(_fetch_one(mid) for mid in master_ids))
        all_offers: list[Offer] = []
        failed = 0
        for item in results:
            if item is None:
                failed += 1
            else:
                all_offers.extend(item)
        
        if not all_offers and master_ids:
            raise AdapterError("Puma product extraction failed for all products", reason_code="product_extraction_failed")
        if failed > 0 and all_offers:
            raise PartialResultError(
                f"Puma: {failed} of {len(master_ids)} products could not be parsed",
                offers=all_offers,
                reason_code="partial_results",
            )
        return all_offers

    @staticmethod
    def _next_data(payload: str) -> dict:
        soup = BeautifulSoup(payload, "html.parser")
        script = soup.select_one("script#__NEXT_DATA__")
        if script is None:
            raise AdapterError(
                "Puma returned an unrecognized catalog shell", reason_code="catalog_shell"
            )
        try:
            document = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError) as exc:
            raise AdapterError(
                "Puma returned malformed catalog data", reason_code="malformed_catalog"
            ) from exc
        if not isinstance(document, dict):
            raise AdapterError("Puma returned malformed catalog data", reason_code="malformed_catalog")
        return document

    @classmethod
    def parse_catalog(cls, payload: str) -> tuple[list[str], str]:
        document = cls._next_data(payload)
        try:
            state = document["props"]["urqlState"]
        except (KeyError, TypeError) as exc:
            raise AdapterError(
                "Puma catalog payload was missing", reason_code="catalog_payload_missing"
            ) from exc
        catalog = None
        try:
            for entry in state.values():
                data = entry.get("data") if isinstance(entry, dict) else None
                decoded = json.loads(data) if isinstance(data, str) else data
                if isinstance(decoded, dict) and "searchProducts" in decoded:
                    catalog = decoded["searchProducts"]
                    break
        except (json.JSONDecodeError, TypeError) as exc:
            raise AdapterError(
                "Puma returned malformed catalog data", reason_code="malformed_catalog"
            ) from exc
        if not isinstance(catalog, dict):
            raise AdapterError(
                "Puma catalog payload was missing", reason_code="catalog_payload_missing"
            )
        try:
            items = catalog["itemsSection"]["items"]
        except (KeyError, TypeError) as exc:
            raise AdapterError(
                "Puma catalog response changed", reason_code="catalog_contract_changed"
            ) from exc
        if not isinstance(items, list):
            raise AdapterError("Puma catalog response changed", reason_code="catalog_contract_changed")
        ids: list[str] = []
        for item in items:
            try:
                master_id = str(item["productSearchHit"]["masterId"])
            except (KeyError, TypeError):
                continue
            if master_id and master_id not in ids:
                ids.append(master_id)
        if items and not ids:
            raise AdapterError(
                "Puma product extraction failed", reason_code="product_extraction_failed"
            )
        version = str(
            document.get("props", {}).get("siteConfig", {}).get("env", {}).get("SHA", "web")
        )
        return ids, version

    async def _guest_headers(self, version: str) -> dict[str, str]:
        base = {
            "Accept": "application/graphql-response+json, application/json",
            "Content-Type": "application/json",
            "Locale": "en-IN",
            "Puma-Request-Source": "web",
            "X-GraphQL-Client-Name": "nitro-fe",
            "X-GraphQL-Client-Version": version,
            "X-Operation-Name": "GuestLogon",
        }
        response = await shared_client.post_json(
            "https://in.puma.com/api/graphql",
            {"operationName": "GuestLogon", "query": GUEST_QUERY, "variables": {}},
            headers=base,
        )
        try:
            guest = response.json()["data"]["guestLogon"]
            token = guest["accessToken"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AdapterError(
                "Puma could not start an anonymous catalog session",
                reason_code="anonymous_session_failed",
            ) from exc
        return {
            **base,
            "Authorization": f"Bearer {token}",
            "Refresh-Token": str(guest.get("refreshToken") or ""),
            "Customer-ID": str(guest.get("customerId") or ""),
            "Customer-Group": str((guest.get("customerContext") or {}).get("hashKey") or ""),
            "X-Operation-Name": "Product",
        }

    async def _product(self, master_id: str, headers: dict[str, str]) -> str:
        response = await shared_client.post_json(
            "https://in.puma.com/api/graphql",
            {"operationName": "Product", "query": PRODUCT_QUERY, "variables": {"id": master_id}},
            headers=headers,
        )
        return response.text

    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        try:
            document = json.loads(payload)
            product = document["data"]["product"]
            variations = product["variations"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AdapterError(
                "Puma returned malformed product data", reason_code="malformed_product"
            ) from exc
        if not isinstance(product, dict) or not isinstance(variations, list):
            raise AdapterError("Puma returned malformed product data", reason_code="malformed_product")
        requested = normalize_size(request.uk_size)
        results: list[Offer] = []
        for variation in variations:
            if not isinstance(variation, dict):
                continue
            price_data = variation.get("productPrice") or {}
            raw_sale = price_data.get("bestPrice") or price_data.get("promotionPrice") or price_data.get("salePrice") or price_data.get("price")
            raw_listed = price_data.get("price") or raw_sale
            if raw_sale is None or raw_listed is None:
                continue
            try:
                sale = parse_inr_paise(raw_sale)
                listed = parse_inr_paise(raw_listed)
            except ValueError:
                continue
            matching_sizes = []
            for group in variation.get("sizeGroups") or []:
                for size in group.get("sizes") or []:
                    raw_size = str(size.get("label") or size.get("value") or "")
                    try:
                        if normalize_size(raw_size.replace("UK", "")) == requested:
                            matching_sizes.append(size)
                    except ValueError:
                        continue
            available = any(bool(size.get("orderable")) for size in matching_sizes)
            stock_status = "in_stock" if available else "out_of_stock" if matching_sizes else "unknown"
            images = variation.get("images") or []
            image = variation.get("preview") or (images[0].get("href") if images else None)
            master_id = str(product.get("id") or "")
            variation_id = str(variation.get("id") or "")
            color_value = str(variation.get("colorValue") or variation_id.rsplit("_", 1)[-1])
            slug = str(product.get("slug") or "product")
            results.append(Offer(
                retailer=self.definition.name, seller="Puma India",
                product_name=str(variation.get("name") or product.get("name") or product.get("header") or "Puma sneaker"),
                brand=str(product.get("brand") or "Puma"),
                model=str(product.get("name") or product.get("header") or ""),
                colourway=variation.get("colorName"), image_url=image,
                category="footwear" if not classify_category(title=variation.get("name") or product.get("name"), url=slug) == "non_footwear" else "non_footwear",
                department=extract_department(gender=product.get("gender"), title=variation.get("name") or product.get("name"), url=slug),
                style_code=str(variation.get("styleNumber") or variation_id or master_id),
                requested_uk_size=requested, size_available=available,
                stock_status=stock_status,
                listed_price_paise=listed, automatic_discount_paise=max(0, listed - sale),
                shipping_paise=0, effective_price_paise=effective_price(listed, max(0, listed-sale), 0),
                product_url=f"https://in.puma.com/in/en/pd/{slug}/{master_id}?swatch={color_value}",
                return_policy="Confirm Puma India's current return eligibility on the product page.",
                match_score=0, last_checked=datetime.now(timezone.utc),
            ))
        if variations and not results:
            raise AdapterError(
                "Puma product extraction failed", reason_code="product_extraction_failed"
            )
        return results
