from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.providers.rss import article_mentions_symbol
from backend.schemas import NewsArticle
from backend.services.news import NewsService


def test_article_mentions_symbol_by_ticker_or_alias():
    assert article_mentions_symbol("AAPL", "Apple raises iPhone production")
    assert article_mentions_symbol("NVDA", "GPU demand remains strong")
    assert not article_mentions_symbol("TSLA", "Bank earnings preview")


def test_news_cache_deduplicates_articles():
    service = NewsService()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    articles = [
        NewsArticle(
            id=f"alpaca:{index}",
            source="alpaca",
            symbol="AAPL",
            headline=f"Apple headline {index}",
            published_at=start + timedelta(hours=index),
            raw_symbols=["AAPL"],
        )
        for index in range(3)
    ]

    service.save_articles(articles)
    service.save_articles(articles)
    cached = service.get_articles("AAPL", limit=10)

    assert len(cached) == 3
    assert cached[0].symbol == "AAPL"
