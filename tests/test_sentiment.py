from __future__ import annotations

from backend.services.sentiment import SentimentService


def test_lexicon_fallback_scores_financial_text(monkeypatch):
    service = SentimentService()
    monkeypatch.setattr(service, "_load_pipeline", lambda: None)

    probabilities, model = service._score_with_finbert_or_lexicon(
        "Apple reports strong profit growth and raises guidance"
    )

    assert model == "lexicon-fallback"
    assert probabilities["positive"] > probabilities["negative"]
    assert round(sum(probabilities.values()), 6) == 1.0

