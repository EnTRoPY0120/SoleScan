"""Deterministic product normalization and offer acceptance rules.

Retailer titles are noisy, but the model requested by a user is not a fuzzy
search suggestion.  This module keeps the normalization deliberately small and
predictable: brand aliases and harmless merchandising words are removed, while
model numbers, suffixes (``OG``, ``SD``, ``SE``), and collaboration names remain
part of the identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

from .schemas import Offer, SearchRequest


BRAND_ALIASES: dict[str, str] = {
    "nike": "nike",
    # Jordan is Nike's model family; recognizing it as Nike prevents a valid
    # ``Nike + Air Jordan`` query from being treated as a brand conflict.
    "jordan": "nike",
    "air jordan": "nike",
    "adidas": "adidas",
    "puma": "puma",
    "asics": "asics",
    "asics tiger": "onitsuka tiger",
    "onitsuka": "onitsuka tiger",
    "onitsuka tiger": "onitsuka tiger",
    "newbalance": "new balance",
    "new balance": "new balance",
    "nb": "new balance",
    "converse": "converse",
    "chuck taylor": "converse",
    "reebok": "reebok",
    "vans": "vans",
    "skechers": "skechers",
    "fila": "fila",
    "crocs": "crocs",
    "salomon": "salomon",
    "asics tiger": "onitsuka tiger",
}

# Words that describe merchandising rather than a model identity.  Do not add
# model suffixes such as OG, SD, GTX, or collaboration names here.
HARMLESS_MODEL_WORDS = {
    "shoe", "shoes", "sneaker", "sneakers", "footwear", "footwears",
    "trainer", "trainers", "boot", "boots", "sandal", "sandals",
    "slide", "slides", "slipper", "slippers", "clog", "clogs",
    "mule", "mules", "men", "mens", "man", "male", "women", "womens",
    "woman", "female", "ladies", "lady", "kids", "kid", "boys", "girls",
    "boy", "girl", "unisex", "adult", "junior", "youth", "infant",
    "new", "latest", "original", "official", "style", "product",
    "colour", "color", "black", "white", "grey", "gray", "red", "green",
    "blue", "navy", "pink", "yellow", "orange", "purple", "beige", "brown",
    "cream", "silver", "gold", "multi", "multicolor", "multicolour",
    "leather", "suede", "canvas", "mesh", "textile", "synthetic", "rubber",
}

FOOTWEAR_TYPES = {
    "shoe", "shoes", "sneaker", "sneakers", "trainer", "trainers", "footwear",
    "boot", "boots", "sandal", "sandals", "slide", "slides", "slipper",
    "slippers", "clog", "clogs", "mule", "mules", "loafer", "loafers",
    "flats", "flat", "heels", "heel", "cleat", "cleats", "football",
    "running", "basketball", "tennis", "skate", "skateboarding",
}
NON_FOOTWEAR_TYPES = {
    "apparel", "clothing", "shirt", "shirts", "tee", "hoodie", "jacket",
    "trouser", "trousers", "pants", "shorts", "dress", "sock", "socks",
    "bag", "bags", "backpack", "handbag", "accessory", "accessories",
    "cap", "hat", "wallet", "belt", "watch", "sunglasses", "jersey",
}

COLOUR_ALIASES = {
    "grey": "gray", "charcoal": "gray", "off white": "white", "cream": "beige",
    "multicolor": "multi", "multicolour": "multi",
}
MODEL_PLURAL_ALIASES = {
    "taylors": "taylor", "chucks": "chuck", "sambas": "samba",
    "speedcats": "speedcat", "mexicos": "mexico", "gazelles": "gazelle",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"['’]s\b", "", str(value).lower())
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return re.sub(r"\s+", " ", value)


def canonical_brand(value: str | None) -> str | None:
    text = normalize_text(value)
    if not text:
        return None
    return BRAND_ALIASES.get(text)


def recognized_brands(value: str | None) -> set[str]:
    """Return brands explicitly mentioned as whole-word aliases."""
    text = f" {normalize_text(value)} "
    found: set[str] = set()
    # Longest aliases first avoids matching ``jordan`` inside ``air jordan``.
    for alias, brand in sorted(BRAND_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        match = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text)
        if match:
            found.add(brand)
            text = text[:match.start()] + (" " * (match.end() - match.start())) + text[match.end():]
    return found


def _words(value: str | None) -> list[str]:
    return normalize_text(value).split()


def normalize_colour(value: str | None) -> set[str]:
    text = normalize_text(value).replace("off white", "white")
    result: set[str] = set()
    for word in text.split():
        result.add(COLOUR_ALIASES.get(word, word))
    return result


def model_tokens(value: str | None, *, remove_brand: str | None = None) -> tuple[str, ...]:
    """Normalize a model to an ordered token tuple.

    Singular/plural merchandising words are removed, but all other tokens are
    retained.  Ordered comparison means a model with an added suffix or a
    collaboration is not accidentally accepted.
    """
    words = _words(value)
    brand = canonical_brand(remove_brand)
    aliases = set()
    if brand:
        aliases = {alias for alias, canonical in BRAND_ALIASES.items() if canonical == brand}
    # Remove multi-word brand aliases as phrases. Chuck Taylor is both a
    # Converse alias and the model identity, so it is intentionally retained.
    # ``Jordan``/``Air Jordan`` identify a Nike model family rather than a
    # redundant retailer brand token. Keep them in the search identity so a
    # catalog query remains useful (``nike air jordan 1``), just as we keep the
    # Converse ``Chuck Taylor`` model name below.
    removable_phrases = [
        tuple(_words(alias)) for alias in aliases
        if alias not in {"chuck taylor", "jordan", "air jordan"}
    ]
    out: list[str] = []
    index = 0
    while index < len(words):
        phrase = next((phrase for phrase in sorted(removable_phrases, key=len, reverse=True)
                       if tuple(words[index:index + len(phrase)]) == phrase), None)
        if phrase:
            index += len(phrase)
            continue
        word = words[index]
        word = MODEL_PLURAL_ALIASES.get(word, word)
        if word not in HARMLESS_MODEL_WORDS:
            # Only pluralize harmless descriptors; a trailing s is meaningful
            # in model names such as ``Gazelle S`` or ``Campus 00s``.
            out.append(word)
        index += 1
    return tuple(out)


@dataclass(frozen=True)
class CanonicalSearch:
    brand: str | None
    model: tuple[str, ...]
    brands_in_query: frozenset[str]

    @property
    def model_text(self) -> str:
        return " ".join(self.model)


def canonical_search(request: SearchRequest) -> CanonicalSearch:
    selected = canonical_brand(request.brand)
    mentioned = recognized_brands(request.query)
    # A model-only query is allowed for any retailer; when a brand is selected,
    # remove all aliases of that selected brand from the model identity.
    brand = selected or (next(iter(mentioned)) if len(mentioned) == 1 else None)
    return CanonicalSearch(brand, model_tokens(request.query, remove_brand=brand), frozenset(mentioned))


def canonical_query(request: SearchRequest, *, include_brand: bool = True) -> str:
    """Build the single deterministic catalog query used by collectors."""
    search = canonical_search(request)
    # If the user entered only a recognized brand, do not duplicate it in the
    # marketplace query (``nike nike``).  Otherwise retain an unrecognized
    # model-only query verbatim after normalization.
    model = search.model_text or normalize_text(request.query)
    if include_brand and search.brand:
        if model == search.brand:
            return search.brand
        return f"{search.brand} {model}".strip()
    if not model and search.brand:
        return search.brand
    return model


def query_brand_conflict(request: SearchRequest) -> str | None:
    selected = canonical_brand(request.brand)
    mentioned = recognized_brands(request.query)
    if request.brand and not selected and mentioned:
        return sorted(mentioned)[0]
    if selected and mentioned - {selected}:
        return sorted(mentioned - {selected})[0]
    if len(mentioned) > 1 and not selected:
        return ", ".join(sorted(mentioned))
    return None


def tokens(value: str | None) -> set[str]:
    """Compatibility helper retained for callers that only need a set."""
    return set(model_tokens(value))


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
        cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
    else:
        cleaned = str(value)
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid INR price: {value}") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"Invalid INR price: {value}")
    return int((amount * 100).quantize(Decimal("1")))


def effective_price(listed: int, automatic_discount: int = 0, shipping: int | None = None) -> int:
    return max(0, listed - automatic_discount) + (shipping or 0)


def classify_category(
    value: str | None = None,
    *, category: str | None = None, product_type: str | None = None,
    breadcrumbs: Iterable[str] = (), url: str | None = None,
    tags: Iterable[str] = (), title: str | None = None,
) -> str:
    """Conservative category classifier: structured retailer data wins."""
    title = title or value
    structured = normalize_text(category or product_type)
    if structured:
        if any(re.search(rf"\b{re.escape(word)}\b", structured) for word in NON_FOOTWEAR_TYPES):
            return "non_footwear"
        if any(re.search(rf"\b{re.escape(word)}\b", structured) for word in FOOTWEAR_TYPES):
            return "footwear"
    values = [structured] if structured else []
    breadcrumb_values = [breadcrumbs] if isinstance(breadcrumbs, str) else (breadcrumbs or ())
    tag_values = [tags] if isinstance(tags, str) else (tags or ())
    values += [normalize_text(x) for x in breadcrumb_values]
    values += [normalize_text(x) for x in tag_values]
    values += [normalize_text(url)] if url else []
    values += [normalize_text(title)] if title else []
    joined = " ".join(values)
    if any(re.search(rf"\b{re.escape(word)}\b", joined) for word in NON_FOOTWEAR_TYPES):
        return "non_footwear"
    if any(re.search(rf"\b{re.escape(word)}\b", joined) for word in FOOTWEAR_TYPES):
        return "footwear"
    return "unknown"


def extract_department(value: str | None = None, *, department: str | None = None, gender: str | None = None,
                       breadcrumbs: Iterable[str] = (), url: str | None = None,
                       tags: Iterable[str] = (), title: str | None = None) -> str:
    title = title or value
    structured = normalize_text(department or gender)
    if structured:
        if re.search(r"\b(?:unisex|uni sex)\b", structured):
            return "unisex"
        if re.search(r"\b(?:kids?|boys?|girls?|junior|youth|infant|children)\b", structured):
            return "kids"
        if re.search(r"\b(?:women|womens|woman|female|ladies)\b", structured):
            return "women"
        if re.search(r"\b(?:men|mens|man|male)\b", structured):
            return "men"
    text = " ".join(normalize_text(x) for x in [department, gender, url, title] if x)
    breadcrumb_values = [breadcrumbs] if isinstance(breadcrumbs, str) else (breadcrumbs or ())
    tag_values = [tags] if isinstance(tags, str) else (tags or ())
    text += " " + " ".join(normalize_text(x) for x in breadcrumb_values)
    text += " " + " ".join(normalize_text(x) for x in tag_values)
    if re.search(r"\b(?:unisex|uni sex)\b", text):
        return "unisex"
    if re.search(r"\b(?:kids?|boys?|girls?|junior|youth|infant|children)\b", text):
        return "kids"
    if re.search(r"\b(?:women|womens|woman|female|ladies|girls?)\b", text):
        return "women"
    if re.search(r"\b(?:men|mens|man|male|boys?)\b", text):
        return "men"
    return "unknown"


def exact_model_match(request: SearchRequest, offer: Offer) -> bool:
    """Accept exact style codes or exact normalized model identity."""
    search = canonical_search(request)
    product_mentions = recognized_brands(" ".join(filter(None, [offer.brand, offer.model, offer.product_name])))
    product_brand = canonical_brand(offer.brand) or (next(iter(product_mentions)) if len(product_mentions) == 1 else None)
    if len(product_mentions) > 1:
        return False
    if request.brand and not search.brand:
        requested_raw = normalize_text(request.brand)
        if requested_raw and requested_raw not in normalize_text(offer.brand):
            return False
    if search.brand and product_brand and product_brand != search.brand:
        return False
    requested_code = normalize_text(request.query).replace(" ", "")
    offered_code = normalize_text(offer.style_code).replace(" ", "") if offer.style_code else ""
    if offered_code and requested_code == offered_code:
        return True
    product = model_tokens(offer.model or offer.product_name, remove_brand=search.brand or product_brand)

    def comparable(tokens: tuple[str, ...]) -> tuple[str, ...]:
        # Retailer titles often spell the same Jordan model as either
        # ``Jordan 1`` or ``Air Jordan 1``.  This is a family alias, not a
        # general-purpose stop word: ``Air Max`` and other model names remain
        # strict ordered identities.
        if len(tokens) >= 2 and tokens[:2] == ("air", "jordan"):
            return ("jordan",) + tokens[2:]
        return tokens

    return bool(search.model) and comparable(product) == comparable(search.model)


def colour_matches(request: SearchRequest, offer: Offer) -> bool:
    requested = normalize_colour(request.colourway)
    if not requested:
        return True
    offered = normalize_colour(offer.colourway or "")
    # Missing colour data is not a conflict; explicit, known colourways are
    # compared as a whole so Black/Red cannot satisfy Black/White.
    return not offered or offered == requested


def department_matches(request: SearchRequest, offer: Offer) -> bool:
    requested = getattr(request.department, "value", request.department)
    offered = getattr(offer.department, "value", offer.department)
    return requested in {None, "any", ""} or offered in {None, "unknown", "unisex", ""} or offered == requested


def accept_offer(request: SearchRequest, offer: Offer, *, footwear_scope_verified: bool = False) -> bool:
    category = getattr(offer.category, "value", offer.category)
    if category == "non_footwear" or (category == "unknown" and not footwear_scope_verified):
        return False
    try:
        if normalize_size(offer.requested_uk_size) != normalize_size(request.uk_size):
            return False
    except (TypeError, ValueError):
        return False
    if not exact_model_match(request, offer) or not department_matches(request, offer):
        return False
    return colour_matches(request, offer)


def match_score(request: SearchRequest, offer: Offer) -> float:
    # Keep this helper as an identity diagnostic for adapter integrations. The
    # collector's acceptance gate is ``accept_offer`` and additionally checks
    # category evidence; a missing category should not make this low-level
    # model comparison look like a different product.
    try:
        size_ok = normalize_size(offer.requested_uk_size) == normalize_size(request.uk_size)
    except (TypeError, ValueError):
        size_ok = False
    if not size_ok or not exact_model_match(request, offer) or not department_matches(request, offer):
        return 0.0
    return 1.0 if colour_matches(request, offer) else 0.0


def confidence_for(score: float) -> str:
    return "exact" if score >= 1 else "weak"


def rank_offers(offers: list[Offer] | SearchRequest, request: SearchRequest | list[Offer] | None = None) -> list[Offer]:
    # Accept both rank_offers(offers) and rank_offers(request, offers) for
    # collector integrations that want colour evidence computed at ranking.
    if isinstance(offers, SearchRequest):
        search_request = offers
        offer_list = request if isinstance(request, list) else []
    else:
        offer_list = offers
        search_request = request if isinstance(request, SearchRequest) else None
    if search_request:
        for offer in offer_list:
            offer.colour_match = colour_matches(search_request, offer)
    stock_rank = {"in_stock": 0, "unknown": 1, "out_of_stock": 2}
    return sorted(
        offer_list,
        key=lambda offer: (
            stock_rank.get(offer.stock_status or "unknown", 1),
            offer.shipping_paise is None,
            offer.effective_price_paise,
            not bool(getattr(offer, "colour_match", True)),
            offer.retailer.lower(),
            offer.product_name.lower(),
        ),
    )


def deduplicate_offers(offers: list[Offer]) -> list[Offer]:
    """Collapse identical seller/style/size/price inventory only."""
    chosen: dict[tuple[str, str, str, str, int], Offer] = {}
    for offer in offers:
        identity = normalize_text(offer.style_code or offer.product_name)
        try:
            requested_size = normalize_size(offer.requested_uk_size)
        except (TypeError, ValueError):
            requested_size = str(offer.requested_uk_size)
        key = (normalize_text(offer.seller or offer.retailer), identity,
               normalize_text(offer.colourway), requested_size,
               offer.effective_price_paise)
        current = chosen.get(key)
        if current is None or offer.match_score > current.match_score:
            chosen[key] = offer
    return list(chosen.values())


# Public descriptive aliases used by collectors and contract tests.
normalize_model_tokens = model_tokens
canonical_search_terms = canonical_search
model_matches = exact_model_match
filter_offer = accept_offer
canonicalize_query = canonical_query
is_exact_match = exact_model_match
