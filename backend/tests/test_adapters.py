import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.adapters.base import AdapterError, detect_challenge
from app.adapters.brandman import BrandmanAdapter
from app.adapters.registry import ADAPTERS, DEFINITIONS
from app.adapters.browser import BrowserMarketplaceAdapter
from app.adapters.converse import ConverseAdapter
from app.adapters.puma import PumaAdapter
from app.adapters.shopify import ShopifyCatalogAdapter
from app.adapters.vegnonveg import VegNonVegAdapter
from app.schemas import SearchRequest


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "retailer_products.json").read_text())

@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda item: item.definition.id)
def test_every_retailer_fixture_contract(adapter):
    if isinstance(adapter, (BrandmanAdapter, ConverseAdapter, PumaAdapter, ShopifyCatalogAdapter, VegNonVegAdapter, BrowserMarketplaceAdapter)):
        pytest.skip("covered by source-specific parser tests")
    payload = FIXTURES[adapter.definition.id]
    if payload == "@nike": payload = FIXTURES["nike"]
    offers = adapter.parse(payload, SearchRequest(query="Air Jordan 1 Low", brand="Nike", uk_size="8"), "https://retailer.example/search")
    assert len(offers) == 1
    result = offers[0]
    assert result.retailer == adapter.definition.name
    assert result.listed_price_paise == 999500
    assert result.effective_price_paise == 949500
    assert result.size_available
    assert result.conditional_offers[0].kind == "bank"

def test_non_inr_is_excluded():
    payload = FIXTURES["nike"].replace('"INR"', '"USD"')
    with pytest.raises(AdapterError, match="extraction failed"):
        ADAPTERS[0].parse(payload, SearchRequest(query="Jordan", uk_size="8"), "https://x")

def test_converse_graphql_fixture_tracks_requested_variant_stock():
    payload = json.dumps({"data":{"products":{"items":[{
        "name":"Chuck Taylor All Star Malden Street", "sku":"A00811C",
        "url_key":"chuck-taylor-all-star-malden-street-a00811c-black", "url_suffix":".html",
        "stock_status":"IN_STOCK", "small_image":{"url":"https://example.com/shoe.jpg"},
        "price_range":{"minimum_price":{"regular_price":{"value":4499,"currency":"INR"},"final_price":{"value":3999,"currency":"INR"},"discount":{"amount_off":500}}},
        "configurable_options":[{"attribute_code":"size","values":[{"label":"9 UK","value_index":226},{"label":"10 UK","value_index":229}]}],
        "variants":[{"attributes":[{"code":"size","value_index":226}],"product":{"sku":"A00811C-9","stock_status":"IN_STOCK"}},{"attributes":[{"code":"size","value_index":229}],"product":{"sku":"A00811C-10","stock_status":"OUT_OF_STOCK"}}]
    }]}}})
    adapter = ConverseAdapter()
    in_stock = adapter.parse(payload, SearchRequest(query="Chuck Taylor Malden Street", uk_size="9"), "https://www.converse.in/")[0]
    out_of_stock = adapter.parse(payload, SearchRequest(query="Chuck Taylor Malden Street", uk_size="10"), "https://www.converse.in/")[0]
    assert in_stock.size_available and not out_of_stock.size_available
    assert in_stock.listed_price_paise == 449900
    assert in_stock.effective_price_paise == 399900

async def test_browser_marketplace_snapshot_to_offer():
    class FakePage:
        async def evaluate(self, script, size):
            assert size == "9"
            return {
                "text":"CONVERSE\nMen Chuck Taylor All Star Malden Street\n₹4,499\nUK 9\nSold By\nBhaane Retail Private Limited",
                "name":"Men Chuck Taylor All Star Malden Street", "image":"https://example.com/shoe.jpg",
                "inStock":True,
            }
    adapter = BrowserMarketplaceAdapter(next(item for item in DEFINITIONS if item.id == 'nykaa_fashion'))
    offer = await adapter._extract_product(FakePage(), SearchRequest(query="Chuck Taylor Malden Street", uk_size="9"), "https://www.nykaafashion.com/product/p/1")
    assert offer is not None and offer.size_available
    assert offer.listed_price_paise == 449900
    assert offer.seller == "Bhaane Retail Private Limited"


BRANDMAN_PRODUCT = json.dumps({
    "title": "New Balance Men 574 Grey Sneakers(ML574EVG)", "vendor": "New Balance",
    "handle": "new-balance-men-574-grey-sneakersml574evg", "price": 899900,
    "compare_at_price": 1099900, "images": ["//cdn.example.com/574.jpg"],
    "variants": [
        {"options": ["Grey", "8"], "sku": "ML574EVG-8", "price": 899900,
         "compare_at_price": 1099900, "available": True},
        {"options": ["Grey", "9"], "sku": "ML574EVG-9", "price": 899900,
         "compare_at_price": 1099900, "available": False},
    ],
})


def test_brandman_search_and_product_variants():
    adapter = BrandmanAdapter()
    links = adapter.parse_search_links(
        '<a href="/products/574?_pos=1">574</a><a href="/products/574?_pos=2">again</a>',
        "https://brandmanretail.com/search?q=574",
    )
    assert links == ["https://brandmanretail.com/products/574"]
    available = adapter.parse(BRANDMAN_PRODUCT, SearchRequest(query="574", uk_size="8"), links[0])[0]
    sold_out = adapter.parse(BRANDMAN_PRODUCT, SearchRequest(query="574", uk_size="9"), links[0])[0]
    missing = adapter.parse(BRANDMAN_PRODUCT, SearchRequest(query="574", uk_size="10"), links[0])[0]
    assert available.size_available and not sold_out.size_available and not missing.size_available
    assert available.listed_price_paise == 1099900
    assert available.automatic_discount_paise == 200000
    assert available.effective_price_paise == 899900
    assert available.style_code == "ML574EVG"
    assert available.colourway == "Grey"
    assert available.retailer == "New Balance · Brandman"
    assert available.seller == "Brandman Retail Ltd"
    assert available.product_url == "https://brandmanretail.com/products/574"


def test_brandman_is_the_only_dedicated_new_balance_source():
    adapter = BrandmanAdapter()
    assert adapter.definition in DEFINITIONS
    assert adapter.definition.id == "new_balance"
    assert adapter.definition.name == "New Balance · Brandman"
    assert urlsplit(adapter.definition.search_url).hostname == "brandmanretail.com"
    configured_hosts = {urlsplit(item.search_url).hostname for item in DEFINITIONS}
    assert "newbalance.com" not in configured_hosts
    assert "newbalance.co.in" not in configured_hosts


def test_brandman_malformed_and_non_new_balance_data():
    adapter = BrandmanAdapter()
    request = SearchRequest(query="574", uk_size="8")
    with pytest.raises(Exception, match="malformed product data"):
        adapter.parse("not json", request, "https://brandmanretail.com/products/bad")
    other_brand = json.loads(BRANDMAN_PRODUCT)
    other_brand["vendor"] = "Timberland"
    assert adapter.parse(json.dumps(other_brand), request, "https://x") == []


@pytest.mark.parametrize("retailer_id", ["reebok", "foot_locker", "myntra", "ajio", "nykaa_fashion"])
def test_browser_retailer_product_fixtures(retailer_id):
    adapter = BrowserMarketplaceAdapter(next(item for item in DEFINITIONS if item.id == retailer_id))
    payload = '''
      <html><head><meta property="og:image" content="https://example.com/shoe.jpg"></head><body>
      <h1>Converse Chuck Taylor Malden Street Black</h1><p>₹4,499</p>
      <p>Style code A00811C</p><p>Sold By Bhaane Retail Private Limited</p>
      <button data-size="9">UK 9</button><p>Use Code SNEAKER10</p></body></html>
    '''
    offers = adapter.parse(payload, SearchRequest(query="Malden Street", uk_size="9"), "https://retailer.example/p/a00811c")
    assert len(offers) == 1
    assert offers[0].size_available and offers[0].listed_price_paise == 449900
    assert offers[0].product_url == "https://retailer.example/p/a00811c"
    assert offers[0].conditional_offers[0].kind == "coupon"


def test_challenge_and_valid_empty_pages_are_distinct():
    assert detect_challenge("<title>Access Denied</title>")
    assert detect_challenge("Please verify you are human")
    assert detect_challenge("Unfortunately we are unable to give you access to our site at this time.")
    assert not detect_challenge("No products matched your search")
    assert BrandmanAdapter.parse_search_links("<p>No products matched</p>", "https://brandmanretail.com") == []
