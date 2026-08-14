import json

import pytest

from app.adapters.base import AdapterError, RetailerDefinition
from app.adapters.puma import PumaAdapter
from app.adapters.shopify import ShopifyCatalogAdapter
from app.adapters.vegnonveg import VegNonVegAdapter
from app.schemas import SearchRequest


def puma_catalog(items):
    state = {"key": {"data": json.dumps({"searchProducts": {"itemsSection": {"items": items}}})}}
    data = {"props": {"urqlState": state, "siteConfig": {"env": {"SHA": "fixture"}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def test_puma_catalog_positive_empty_and_changed_contract():
    item = {"productSearchHit": {"masterId": "398846"}}
    assert PumaAdapter.parse_catalog(puma_catalog([item])) == (["398846"], "fixture")
    assert PumaAdapter.parse_catalog(puma_catalog([])) == ([], "fixture")
    with pytest.raises(AdapterError, match="unrecognized catalog shell"):
        PumaAdapter.parse_catalog("<main>Speedcat products load here</main>")
    with pytest.raises(AdapterError, match="extraction failed"):
        PumaAdapter.parse_catalog(puma_catalog([{"unexpected": True}]))


PUMA_PRODUCT = json.dumps({"data": {"product": {
    "id": "398846", "name": "Speedcat OG", "slug": "speedcat-og", "brand": "PUMA",
    "variations": [
        {"id": "398846_01", "name": "Speedcat OG", "colorValue": "01", "colorName": "Black White",
         "preview": "https://example.com/black.jpg", "styleNumber": "398846_01",
         "productPrice": {"price": 9999, "salePrice": 7999},
         "sizeGroups": [{"label": "UK", "sizes": [{"label": "9", "orderable": True}, {"label": "10", "orderable": False}]}]},
        {"id": "398846_02", "name": "Speedcat OG", "colorValue": "02", "colorName": "Red White",
         "preview": "https://example.com/red.jpg", "styleNumber": "398846_02",
         "productPrice": {"price": 9999, "salePrice": 9999},
         "sizeGroups": [{"label": "UK", "sizes": [{"label": "9", "orderable": False}]}]},
    ]
}}})


def test_puma_returns_one_offer_per_colour_with_exact_size_stock():
    offers = PumaAdapter().parse(PUMA_PRODUCT, SearchRequest(query="Speedcat", brand="Puma", uk_size="9"), "https://in.puma.com")
    assert len(offers) == 2
    assert offers[0].size_available and not offers[1].size_available
    assert offers[0].listed_price_paise == 999900
    assert offers[0].effective_price_paise == 799900
    assert offers[0].colourway == "Black White"
    assert "swatch=01" in offers[0].product_url


def test_puma_malformed_product_is_not_a_false_zero():
    with pytest.raises(AdapterError, match="malformed product"):
        PumaAdapter().parse("{}", SearchRequest(query="Speedcat", uk_size="9"), "https://x")


SHOPIFY_PRODUCT = json.dumps({
    "id": 1, "title": "Puma Speedcat OG Black", "vendor": "Puma",
    "options": [{"name": "Colour"}, {"name": "Size"}], "images": ["//cdn.example/shoe.jpg"],
    "variants": [
        {"options": ["Black", "UK 9"], "sku": "SPEED-9", "price": 799900, "compare_at_price": 999900, "available": True},
        {"options": ["Black", "UK 10"], "sku": "SPEED-10", "price": 799900, "compare_at_price": 999900, "available": False},
    ]
})


@pytest.mark.parametrize("retailer_id,name", [("superkicks", "Superkicks"), ("limited_edt", "Limited Edt")])
def test_shopify_catalog_stock_empty_and_changed_payload(retailer_id, name):
    adapter = ShopifyCatalogAdapter(RetailerDefinition(retailer_id, name, "boutique", f"https://{retailer_id}.example/search?q={{query}}"))
    suggestions = json.dumps({"resources": {"results": {"products": [{"handle": "speedcat"}]}}})
    assert adapter.parse_suggestions(suggestions) == ["/products/speedcat"]
    assert adapter.parse_suggestions('{"resources":{"results":{"products":[]}}}') == []
    available = adapter.parse(SHOPIFY_PRODUCT, SearchRequest(query="Speedcat", uk_size="9"), "https://x/products/speedcat")[0]
    sold_out = adapter.parse(SHOPIFY_PRODUCT, SearchRequest(query="Speedcat", uk_size="10"), "https://x/products/speedcat")[0]
    assert available.size_available and not sold_out.size_available
    assert available.effective_price_paise == 799900
    with pytest.raises(AdapterError, match="unreadable catalog"):
        adapter.parse_suggestions("not-json")


def veg_product(sizes: list[str]) -> str:
    boxes = "".join(f'<div class="size-box" data-size="{size}">{size}</div>' for size in sizes)
    return f'''<html><head><meta property="og:image" content="https://example/shoe.jpg"></head><body>
      <span class="article_code">39884601</span><h1 class="p-name">Puma SPEEDCAT OG</h1><p>BLACK/WHITE</p>
      <span data-snapmint-price="9,999"></span>{boxes}</body></html>'''


def test_vegnonveg_search_product_stock_and_contracts():
    search = '<div id="products"><div class="product"><a href="/products/speedcat">Shoe</a></div></div>'
    assert VegNonVegAdapter.parse_search_links(search, "https://www.vegnonveg.com/search") == ["https://www.vegnonveg.com/products/speedcat"]
    assert VegNonVegAdapter.parse_search_links('<div id="products"></div>', "https://x") == []
    adapter = VegNonVegAdapter()
    assert adapter.parse(veg_product(["8", "9"]), SearchRequest(query="Speedcat", uk_size="9"), "https://x")[0].size_available
    assert not adapter.parse(veg_product(["8"]), SearchRequest(query="Speedcat", uk_size="9"), "https://x")[0].size_available
    with pytest.raises(AdapterError, match="unrecognized catalog shell"):
        adapter.parse_search_links("<main></main>", "https://x")


def test_puma_partial_success_one_bad_product():
    """One malformed product must not discard valid products."""
    from app.adapters.puma import PartialResultError
    
    good_product = PUMA_PRODUCT  # valid
    bad_product = "{}"  # malformed
    
    adapter = PumaAdapter()
    
    # Valid parse works
    offers = adapter.parse(good_product, SearchRequest(query="Speedcat", uk_size="9"), "https://in.puma.com")
    assert len(offers) > 0
    
    # Bad parse raises AdapterError (which _fetch_one catches individually)
    with pytest.raises(AdapterError):
        adapter.parse(bad_product, SearchRequest(query="Speedcat", uk_size="9"), "https://in.puma.com")
    
    # Verify PartialResultError carries offers
    exc = PartialResultError("partial", offers=offers, reason_code="partial_results")
    assert len(exc.offers) > 0
    assert exc.reason_code == "partial_results"
