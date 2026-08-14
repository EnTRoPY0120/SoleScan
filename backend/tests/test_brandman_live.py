"""Opt-in contract check for Brandman's live New Balance India catalog."""

import json
import os
from urllib.parse import quote_plus

import pytest

from app.adapters.base import shared_client
from app.adapters.brandman import BrandmanAdapter
from app.normalization import normalize_size
from app.schemas import SearchRequest


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("SPF_RUN_LIVE_TESTS") != "1",
        reason="set SPF_RUN_LIVE_TESTS=1 to contact Brandman Retail",
    ),
]


async def test_brandman_live_product_price_discount_and_requested_size():
    adapter = BrandmanAdapter()
    search_url = adapter.definition.search_url.format(query=quote_plus("574"))
    search_response = await shared_client.get(search_url)
    links = adapter.parse_search_links(search_response.text, str(search_response.url))
    assert links, "Brandman's live catalog returned no New Balance 574 product links"

    candidate = None
    for product_url in links[:6]:
        response = await shared_client.get(f'{product_url.split("?", 1)[0]}.js')
        product = json.loads(response.text)
        if str(product.get("vendor", "")).casefold() != "new balance":
            continue
        for variant in product.get("variants") or []:
            if not variant.get("available"):
                continue
            for option in variant.get("options") or []:
                try:
                    candidate = (product_url.split("?", 1)[0], response.text, normalize_size(str(option)))
                    break
                except ValueError:
                    continue
            if candidate:
                break
        if candidate:
            break

    assert candidate, "No in-stock UK-sized New Balance variant was found in the live Brandman results"
    product_url, payload, requested_size = candidate
    offer = adapter.parse(payload, SearchRequest(query="574", uk_size=requested_size), product_url)[0]

    assert offer.retailer == "New Balance · Brandman"
    assert offer.seller == "Brandman Retail Ltd"
    assert offer.product_url.startswith("https://brandmanretail.com/products/")
    assert offer.product_name and offer.brand == "New Balance"
    assert offer.requested_uk_size == requested_size and offer.size_available
    assert offer.listed_price_paise > 0
    assert 0 <= offer.automatic_discount_paise <= offer.listed_price_paise
    assert offer.effective_price_paise == offer.listed_price_paise - offer.automatic_discount_paise
