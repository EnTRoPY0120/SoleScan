"""Conservative interpretation of misspelled sneaker model queries."""

from __future__ import annotations

from dataclasses import dataclass

from .normalization import canonical_brand, canonical_search, model_tokens, normalize_text
from .schemas import SearchRequest


@dataclass(frozen=True)
class TrustedModel:
    brand: str | None
    model: str


@dataclass(frozen=True)
class ModelEvidence:
    retailer_id: str
    retailer_kind: str
    brand: str | None
    model: str


@dataclass(frozen=True)
class QueryResolution:
    original_query: str
    resolved_query: str
    corrected: bool


def _one_edit_apart(left: str, right: str) -> bool:
    if left == right or not left.isalpha() or not right.isalpha():
        return False
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    short, long = (left, right) if len(left) < len(right) else (right, left)
    index = 0
    while index < len(short) and short[index] == long[index]:
        index += 1
    return short[index:] == long[index + 1:]


class ModelVocabulary:
    def __init__(self, models: list[TrustedModel]) -> None:
        self.models = models

    @classmethod
    def default(cls, evidence: list[ModelEvidence] | None = None) -> "ModelVocabulary":
        learned = cls.from_evidence(evidence or [])
        return cls([TrustedModel("Onitsuka Tiger", "MEXICO 66"), *learned.models])

    @classmethod
    def from_evidence(cls, evidence: list[ModelEvidence]) -> "ModelVocabulary":
        grouped: dict[tuple[str | None, tuple[str, ...]], list[ModelEvidence]] = {}
        for item in evidence:
            brand = canonical_brand(item.brand)
            key = (brand, model_tokens(item.model, remove_brand=brand))
            grouped.setdefault(key, []).append(item)
        trusted: list[TrustedModel] = []
        for items in grouped.values():
            official = any(item.retailer_kind == "official" for item in items)
            corroborated = len({item.retailer_id for item in items}) >= 2
            if official or corroborated:
                trusted.append(TrustedModel(items[0].brand, items[0].model))
        return cls(trusted)

    def resolve(self, request: SearchRequest) -> QueryResolution:
        original = request.query
        search = canonical_search(request)
        matches: list[tuple[str, str]] = []
        for trusted in self.models:
            trusted_brand = canonical_brand(trusted.brand)
            if search.brand and trusted_brand and trusted_brand != search.brand:
                continue
            candidate = model_tokens(trusted.model, remove_brand=trusted_brand)
            if len(candidate) != len(search.model):
                continue
            differences = [
                (entered, expected)
                for entered, expected in zip(search.model, candidate)
                if entered != expected
            ]
            if len(differences) == 1 and _one_edit_apart(*differences[0]):
                matches.append(differences[0])
        unique = set(matches)
        if len(unique) != 1:
            return QueryResolution(original, original, False)
        entered, expected = unique.pop()
        words = normalize_text(original).split()
        words[words.index(entered)] = expected
        return QueryResolution(original, " ".join(words), True)
