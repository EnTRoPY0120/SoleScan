import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from .schemas import Offer, SearchRequest


BRAND_ALIASES = {
    "newbalance": "new balance",
    "nb": "new balance",
    "onitsuka": "onitsuka tiger",
    "asics tiger": "onitsuka tiger",
}
STOPWORDS = {"shoe", "shoes", "sneaker", "sneakers", "mens", "womens", "unisex"}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    value = re.sub(r"\s+", " ", value)
    return BRAND_ALIASES.get(value, value)


def tokens(value: str | None) -> set[str]:
    return {part for part in normalize_text(value).split() if part not in STOPWORDS}


def normalize_size(value: str | int | float) -> str:
    raw = str(value).lower().strip()
    raw = re.sub(r"^(uk|u\.k\.)\s*", "", raw)
    raw = raw.replace("½", ".5")
    if not re.fullmatch(r"\d{1,2}(?:\.0|\.5)?", raw):
        raise ValueError("UK size must be a whole or half size, for example 8 or 8.5")
    number = Decimal(raw)
    if number < 1 or number > 18:
        raise ValueError("UK size must be between 1 and 18")
    return str(int(number)) if number == number.to_integral() else f"{number:.1f}"


def parse_inr_paise(value: str | int | float | Decimal) -> int:
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9.]", "", value.replace(",", ""))
    else:
        cleaned = str(value)
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid INR price: {value}") from exc
    return int((amount * 100).quantize(Decimal("1")))


def effective_price(listed: int, automatic_discount: int = 0, shipping: int | None = None) -> int:
    return max(0, listed - automatic_discount) + (shipping or 0)


def match_score(request: SearchRequest, offer: Offer) -> float:
    query_tokens = tokens(" ".join(filter(None, [request.brand, request.query])))
    product_tokens = tokens(" ".join(filter(None, [offer.brand, offer.model, offer.product_name])))
    if not query_tokens or not product_tokens:
        return 0.0
    overlap = len(query_tokens & product_tokens) / len(query_tokens)
    sequence = SequenceMatcher(None, normalize_text(request.query), normalize_text(offer.product_name)).ratio()
    score = 0.62 * overlap + 0.23 * sequence
    if request.brand:
        score += 0.1 if tokens(request.brand) <= product_tokens else -0.15
    if request.colourway:
        colour_tokens = tokens(request.colourway)
        score += 0.05 * (len(colour_tokens & tokens(offer.colourway or offer.product_name)) / max(1, len(colour_tokens)))
    if offer.style_code and normalize_text(offer.style_code) in normalize_text(request.query):
        score = max(score, 0.98)
    return min(1.0, max(0.0, score))


def confidence_for(score: float) -> str:
    if score >= 0.92:
        return "exact"
    if score >= 0.72:
        return "strong"
    if score >= 0.55:
        return "possible"
    return "weak"


def rank_offers(offers: list[Offer]) -> list[Offer]:
    stock_rank = {"in_stock": 0, "unknown": 1, "out_of_stock": 2}
    return sorted(
        offers,
        key=lambda offer: (
            stock_rank[offer.stock_status or "unknown"],
            offer.shipping_paise is None,
            offer.effective_price_paise,
            -offer.match_score,
            offer.retailer.lower(),
        ),
    )


def deduplicate_offers(offers: list[Offer]) -> list[Offer]:
    """Collapse duplicated marketplace inventory, never distinct retailer prices."""
    chosen: dict[tuple[str, str, str, int], Offer] = {}
    for offer in offers:
        identity = normalize_text(offer.style_code or offer.product_name)
        key = (
            normalize_text(offer.seller or offer.retailer),
            identity,
            offer.requested_uk_size,
            offer.effective_price_paise,
        )
        current = chosen.get(key)
        if current is None or offer.match_score > current.match_score:
            chosen[key] = offer
    return list(chosen.values())
