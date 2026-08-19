import json

import pytest

from app.adapters.asics import AsicsAdapter
from app.adapters.base import AdapterError
from app.schemas import SearchRequest


def payload(*, total=1, items=None):
    if items is None:
        items = [{
            "__typename": "ConfigurableProduct",
            "name": "GEL-KAYANO 14",
            "sku": "1203A537.118",
            "url_key": "1203a537-118-gel-kayano-14",
            "stock_status": "IN_STOCK",
            "product_sub_title": "Unisex Sportstyle Shoes",
            "small_image": {"url": "https://images.example/kayano.jpg"},
            "price_range": {"minimum_price": {
                "regular_price": {"value": "13999", "currency": "INR"},
                "final_price": {"value": "11199", "currency": "INR"},
            }},
            "configurable_options": [{"attribute_code": "size", "values": [
                {"value_index": 73, "label": "US10/UK9"},
                {"value_index": 5555, "label": "US10H/UK9H"},
            ]}],
            "variants": [
                {"attributes": [{"code": "size", "value_index": 73}], "product": {"sku": "x.10", "stock_status": "IN_STOCK"}},
                {"attributes": [{"code": "size", "value_index": 5555}], "product": {"sku": "x.10H", "stock_status": "OUT_OF_STOCK"}},
            ],
        }]
    return json.dumps({"data": {"products": {"total_count": total, "items": items}}})


def test_asics_graphql_contract_prices_and_exact_uk_stock():
    adapter = AsicsAdapter()
    available = adapter.parse(payload(), SearchRequest(query="GEL-KAYANO 14", uk_size="9"), "https://www.asics.co.in/graphql")[0]
    unavailable = adapter.parse(payload(), SearchRequest(query="GEL-KAYANO 14", uk_size="9.5"), "https://www.asics.co.in/graphql")[0]

    assert available.size_available and available.stock_status == "in_stock"
    assert unavailable.stock_status == "out_of_stock"
    assert available.listed_price_paise == 1_399_900
    assert available.effective_price_paise == 1_119_900
    assert available.style_code == "1203A537.118"
    assert available.product_url.endswith("1203a537-118-gel-kayano-14.html")


def test_asics_valid_empty_and_changed_contract_are_distinct():
    adapter = AsicsAdapter()
    request = SearchRequest(query="not-a-real-shoe", uk_size="9")
    assert adapter.parse(payload(total=0, items=[]), request, "https://www.asics.co.in/graphql") == []
    with pytest.raises(AdapterError) as caught:
        adapter.parse('{"data": {"products": {}}}', request, "https://www.asics.co.in/graphql")
    assert caught.value.reason_code == "catalog_contract_changed"
    assert caught.value.diagnostics == {"stage": "catalog", "operation": "ProductSearch"}
