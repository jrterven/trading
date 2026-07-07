from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.config import get_settings
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

    assert service.save_articles(articles) == 3
    assert service.save_articles(articles) == 0
    cached = service.get_articles("AAPL", limit=10)

    assert len(cached) == 3
    assert cached[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_news_fetch_only_downloads_missing_windows(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    get_settings.cache_clear()

    class FakeAlpaca:
        def __init__(self) -> None:
            self.calls: list[tuple[datetime, datetime]] = []

        async def fetch_news(self, symbol: str, start: datetime, end: datetime, limit: int):
            self.calls.append((start, end))
            return [
                NewsArticle(
                    id=f"alpaca:{symbol}:{start.date()}",
                    source="alpaca",
                    symbol=symbol,
                    headline=f"{symbol} headline {start.date()}",
                    published_at=start + timedelta(hours=1),
                    raw_symbols=[symbol],
                )
            ]

    service = NewsService()
    fake = FakeAlpaca()
    service.alpaca = fake  # type: ignore[assignment]
    start = datetime(2026, 1, 1, tzinfo=UTC)

    first = await service.fetch_and_store_with_summary("AAPL", start, start + timedelta(days=2), limit=10)
    second = await service.fetch_and_store_with_summary("AAPL", start, start + timedelta(days=3), limit=10)

    assert len(fake.calls) == 3
    assert fake.calls[-1] == (start + timedelta(days=2), start + timedelta(days=3))
    assert len(service.get_articles("AAPL", start, start + timedelta(days=3), limit=10)) == 3
    assert first.summary.fetched == 2
    assert first.summary.new == 2
    assert first.summary.existing == 0
    assert second.summary.fetched == 1
    assert second.summary.new == 1
    assert second.summary.existing == 2
    assert second.summary.total == 3
    assert second.summary.daily.max is not None
    assert second.summary.daily.min is not None
    assert second.summary.daily.max.count == 1
    assert second.summary.daily.max.date == "2026-01-03"
    assert second.summary.daily.min.count == 1
    assert second.summary.daily.min.date == "2026-01-01"
    assert second.summary.daily.average == 1.0


def test_same_article_can_link_to_multiple_symbols_with_different_relation_types():
    service = NewsService()
    published = datetime(2026, 1, 1, tzinfo=UTC)
    article = NewsArticle(
        id="alpaca:shared",
        source="alpaca",
        symbol="AAPL",
        headline="Apple supplier chip shortage pressures broader technology sector",
        published_at=published,
        raw_symbols=["AAPL"],
    )

    service.save_articles([article], requested_symbol="AAPL")
    service.save_articles([article], requested_symbol="MSFT")

    apple = service.get_articles("AAPL", published - timedelta(days=1), published + timedelta(days=1))[0]
    microsoft = service.get_articles("MSFT", published - timedelta(days=1), published + timedelta(days=1))[0]

    assert apple.id == microsoft.id == "alpaca:shared"
    assert apple.relation_type == "direct"
    assert microsoft.relation_type == "indirect"
