import asyncio
from datetime import datetime, timezone
import re
from urllib.parse import quote_plus, urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import AdapterError, RetailerAdapter, RetailerDefinition, shared_client
from ..normalization import canonical_query, classify_category, effective_price, extract_department, normalize_size, parse_inr_paise
from ..schemas import Offer, SearchRequest


class VegNonVegAdapter(RetailerAdapter):
    definition = RetailerDefinition(
        "vegnonveg", "VegNonVeg", "boutique", "https://www.vegnonveg.com/search?q={query}",
        adapter_type="vegnonveg", footwear_only_scope=True
    )

    async def search(self, request: SearchRequest, *, bypass_cache: bool = False) -> list[Offer]:
        response = await shared_client.get(
            self.definition.search_url.format(query=quote_plus(canonical_query(request, include_brand=True)))
        )
        links = self.parse_search_links(response.text, str(response.url))
        semaphore = asyncio.Semaphore(2)

        async def collect(link: str) -> list[Offer]:
            async with semaphore:
                product = await shared_client.get(link)
            return self.parse(product.text, request, link)

        batches = await asyncio.gather(*(collect(link) for link in links[:8]), return_exceptions=True)
        offers = [offer for batch in batches if isinstance(batch, list) for offer in batch]
        failures = sum(isinstance(item, Exception) for item in batches)
        if failures and offers:
            from .base import PartialResultError
            raise PartialResultError(
                f"VegNonVeg: {failures} of {len(batches)} products could not be collected",
                offers=offers, reason_code="partial_results",
            )
        if failures:
            raise next(item for item in batches if isinstance(item, Exception))
        if links and not offers:
            raise AdapterError(
                "VegNonVeg product extraction failed", reason_code="product_extraction_failed"
            )
        return offers

    @staticmethod
    def parse_search_links(payload: str, source_url: str) -> list[str]:
        soup = BeautifulSoup(payload, "html.parser")
        container = soup.select_one("#products")
        if container is None:
            raise AdapterError(
                "VegNonVeg returned an unrecognized catalog shell", reason_code="catalog_shell"
            )
        cards = container.select('.product a[href*="/products/"]')
        links: list[str] = []
        for card in cards:
            url = urlsplit(urljoin(source_url, str(card.get("href") or "")))._replace(query="", fragment="").geturl()
            if url and url not in links:
                links.append(url)
        if container.select(".product") and not links:
            raise AdapterError(
                "VegNonVeg catalog response changed", reason_code="catalog_contract_changed"
            )
        return links

    def parse(self, payload: str, request: SearchRequest, source_url: str) -> list[Offer]:
        soup = BeautifulSoup(payload, "html.parser")
        heading = soup.select_one("h1.p-name")
        article = soup.select_one(".article_code")
        price_node = soup.select_one("[data-snapmint-price]")
        if heading is None or article is None or price_node is None:
            raise AdapterError(
                "VegNonVeg returned malformed product data", reason_code="malformed_product"
            )
        try:
            listed = parse_inr_paise(str(price_node.get("data-snapmint-price") or ""))
        except ValueError as exc:
            raise AdapterError(
                "VegNonVeg returned malformed product pricing", reason_code="malformed_product"
            ) from exc
        requested = normalize_size(request.uk_size)
        size_nodes = soup.select(".size-box[data-size]")
        available = False
        for node in size_nodes:
            raw = re.sub(r"\s*\(.*?\)\s*$", "", str(node.get("data-size") or ""), flags=re.S)
            try:
                if normalize_size(raw.replace("UK", "")) == requested:
                    available = not bool(re.search(r"sold|disabled|unavailable|out.of.stock", " ".join(node.get("class", [])), re.I))
                    if available:
                        break
            except ValueError:
                continue
        name = heading.get_text(" ", strip=True)
        colour_node = heading.find_next_sibling("p")
        colour = colour_node.get_text(" ", strip=True) if colour_node else None
        image = soup.select_one('meta[property="og:image"]')
        brand = name.split(maxsplit=1)[0] if " " in name else None
        return [Offer(
            retailer=self.definition.name, seller="VegNonVeg", product_name=name,
            brand=brand, model=name, colourway=colour,
            category="footwear",
            department=extract_department(title=name, url=source_url),
            image_url=str(image.get("content")) if image and image.get("content") else None,
            style_code=article.get_text(" ", strip=True) or None,
            requested_uk_size=requested, size_available=available,
            stock_status=("in_stock" if available else "out_of_stock" if size_nodes else "unknown"),
            listed_price_paise=listed, automatic_discount_paise=0,
            shipping_paise=None, effective_price_paise=effective_price(listed),
            product_url=source_url,
            return_policy="Confirm VegNonVeg's current return eligibility on the product page.",
            match_score=0, last_checked=datetime.now(timezone.utc),
        )]
