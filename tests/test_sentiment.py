from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.schemas import NewsArticle
from backend.services.news import NewsService
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


@pytest.mark.asyncio
async def test_run_sentiment_with_empty_article_list_returns_empty():
    service = SentimentService()

    assert await service.run_for_symbol("AAPL", article_ids=[], use_ollama=False) == []


@pytest.mark.asyncio
async def test_get_scores_returns_persisted_scores_for_news_range(monkeypatch):
    published = datetime(2026, 7, 1, tzinfo=UTC)
    news = NewsService()
    sentiment = SentimentService()
    monkeypatch.setattr(sentiment, "_load_pipeline", lambda: None)
    news.save_articles(
        [
            NewsArticle(
                id="alpaca:range-score",
                source="alpaca",
                symbol="AAPL",
                headline="Apple reports strong profit growth",
                published_at=published,
                available_at=published,
                raw_symbols=["AAPL"],
            )
        ],
        requested_symbol="AAPL",
    )

    score = await sentiment.score_article(
        news.get_articles("AAPL", published - timedelta(days=1), published + timedelta(days=1))[0],
        use_ollama=False,
    )
    sentiment.save_scores([score])

    scores = sentiment.get_scores(
        "AAPL",
        start=published - timedelta(days=1),
        end=published + timedelta(days=1),
    )

    assert [item.article_id for item in scores] == ["alpaca:range-score"]
