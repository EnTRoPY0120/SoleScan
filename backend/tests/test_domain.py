from datetime import datetime, timezone

import pytest

from app.normalization import deduplicate_offers, effective_price, match_score, normalize_size, parse_inr_paise, rank_offers
from app.schemas import ConditionalOffer, Offer, SearchRequest


def offer(**changes):
    values = dict(retailer="Store", product_name="Nike Air Jordan 1 Low", brand="Nike", requested_uk_size="8", size_available=True, listed_price_paise=1000000, automatic_discount_paise=0, shipping_paise=0, effective_price_paise=1000000, product_url="https://example.com/a", match_score=.8, last_checked=datetime.now(timezone.utc))
    values.update(changes)
    return Offer(**values)


@pytest.mark.parametrize(("raw", "expected"), [("UK 8", "8"), ("8.5", "8.5"), ("8½", "8.5"), (9, "9")])
def test_normalize_size(raw, expected): assert normalize_size(raw) == expected

def test_invalid_size():
    with pytest.raises(ValueError): normalize_size("large")

def test_currency_and_effective_price():
    assert parse_inr_paise("₹12,999.50") == 1_299_950
    assert effective_price(1_000_000, 100_000, 25_00) == 902_500

def test_unknown_shipping_ranks_after_known_total():
    unknown = offer(retailer="Unknown", effective_price_paise=800000, shipping_paise=None)
    known = offer(retailer="Known", effective_price_paise=900000, shipping_paise=0)
    assert rank_offers([unknown, known])[0].retailer == "Known"

def test_conditional_offer_does_not_change_effective_price():
    candidate = offer(conditional_offers=[ConditionalOffer(kind="coupon", description="SAVE10", amount_paise=100000)])
    assert candidate.effective_price_paise == candidate.listed_price_paise

def test_matching_and_weak_classification():
    request = SearchRequest(query="Air Jordan 1 Low", brand="Nike", uk_size="8")
    assert match_score(request, offer()) > .72
    assert match_score(request, offer(product_name="Adidas Samba", brand="Adidas")) < .55

def test_dedup_marketplace_inventory_but_retains_different_retailers():
    duplicated = [offer(retailer="Nykaa", seller="Nike India", style_code="ABC", product_url="https://a"), offer(retailer="Nike", seller="Nike India", style_code="ABC", product_url="https://b")]
    assert len(deduplicate_offers(duplicated)) == 1
    separate = [offer(retailer="Nike", style_code="ABC"), offer(retailer="Foot Locker", style_code="ABC")]
    assert len(deduplicate_offers(separate)) == 2

