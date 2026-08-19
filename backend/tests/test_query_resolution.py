import pytest

from app.query_resolution import ModelEvidence, ModelVocabulary, TrustedModel
from app.schemas import SearchRequest


def test_resolves_one_misspelled_model_token_without_changing_the_identity():
    vocabulary = ModelVocabulary([
        TrustedModel(brand="Onitsuka Tiger", model="MEXICO 66"),
    ])

    resolution = vocabulary.resolve(
        SearchRequest(query="onitsuka mexio 66", uk_size="9")
    )

    assert resolution.original_query == "onitsuka mexio 66"
    assert resolution.resolved_query == "onitsuka mexico 66"
    assert resolution.corrected is True


def test_official_evidence_teaches_a_model_but_one_marketplace_does_not():
    request = SearchRequest(query="mexio 66", uk_size="9")
    official = ModelVocabulary.from_evidence([
        ModelEvidence("onitsuka_tiger", "official", "Onitsuka Tiger", "MEXICO 66"),
    ])
    marketplace = ModelVocabulary.from_evidence([
        ModelEvidence("marketplace_a", "marketplace", "Onitsuka Tiger", "MEXICO 66"),
    ])

    assert official.resolve(request).resolved_query == "mexico 66"
    assert marketplace.resolve(request).corrected is False


def test_two_independent_nonofficial_retailers_can_corroborate_a_model():
    vocabulary = ModelVocabulary.from_evidence([
        ModelEvidence("marketplace_a", "marketplace", "Onitsuka Tiger", "MEXICO 66"),
        ModelEvidence("specialist_b", "boutique", "Onitsuka Tiger", "MEXICO 66"),
    ])

    resolution = vocabulary.resolve(SearchRequest(query="mexio 66", uk_size="9"))

    assert resolution.resolved_query == "mexico 66"


def test_curated_vocabulary_bootstraps_a_fresh_install():
    resolution = ModelVocabulary.default().resolve(
        SearchRequest(query="onitsuka mexio 66", uk_size="9")
    )

    assert resolution.resolved_query == "onitsuka mexico 66"


@pytest.mark.parametrize(
    ("query", "models"),
    [
        ("mexic 66", ["MEXICO 66", "MEXICA 66"]),
        ("mexico 67", ["MEXICO 66"]),
        ("mexico 66 sd", ["MEXICO 66"]),
    ],
    ids=["ambiguous", "different-number", "model-suffix"],
)
def test_does_not_resolve_ambiguous_or_identity_changing_queries(query, models):
    vocabulary = ModelVocabulary([
        TrustedModel("Onitsuka Tiger", model) for model in models
    ])

    resolution = vocabulary.resolve(SearchRequest(query=query, uk_size="9"))

    assert resolution.corrected is False
    assert resolution.resolved_query == query
