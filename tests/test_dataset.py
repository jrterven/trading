from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.config import get_settings
from backend.schemas import Bar, NewsArticle, SentimentScore
from backend.services.dataset import DatasetService
from backend.services.market_data import MarketDataService
from backend.services.news import NewsService
from backend.services.sentiment import SentimentService
from backend.time_utils import utc_now


def test_dataset_summary_endpoint_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "dataset-empty.duckdb"))
    get_settings.cache_clear()
    app_module = importlib.reload(backend_main)

    with TestClient(app_module.app) as client:
        response = client.get("/api/dataset/summary")

    assert response.status_code == 200
    assert response.json() == []


def test_dataset_summary_groups_news_sentiment_and_bars():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    MarketDataService().save_bars(
        [
            Bar(
                symbol="AAPL",
                timeframe="1Day",
                timestamp=start,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1000,
                source="alpaca",
            ),
            Bar(
                symbol="AAPL",
                timeframe="1Hour",
                timestamp=start + timedelta(hours=1),
                open=101,
                high=102,
                low=100,
                close=101,
                volume=2000,
                source="alpaca",
            ),
        ]
    )
    news = NewsService()
    news.save_articles(
        [
            NewsArticle(
                id="alpaca:dataset-1",
                source="alpaca",
                symbol="AAPL",
                headline="Apple reports strong growth",
                published_at=start,
                raw_symbols=["AAPL"],
            ),
            NewsArticle(
                id="alpaca:dataset-2",
                source="alpaca",
                symbol="AAPL",
                headline="Apple faces pressure",
                published_at=start + timedelta(days=1),
                raw_symbols=["AAPL"],
            ),
        ],
        requested_symbol="AAPL",
    )
    SentimentService().save_scores(
        [
            SentimentScore(
                id="sentiment:dataset-1",
                article_id="alpaca:dataset-1",
                symbol="AAPL",
                label="positive",
                score=0.8,
                positive=0.8,
                neutral=0.1,
                negative=0.1,
                model="test",
                created_at=utc_now(),
            )
        ]
    )

    rows = DatasetService().summary()
    apple = next(row for row in rows if row.symbol == "AAPL")

    assert apple.news_count == 2
    assert apple.sentiment_count == 1
    assert apple.sentiment_coverage_pct == 50.0
    assert apple.has_news is True
    assert apple.has_sentiment is True
    assert apple.has_ohlcv is True
    assert {item.timeframe: item.count for item in apple.bars}["1Day"] == 1
    assert {item.timeframe: item.count for item in apple.bars}["1Hour"] == 1


def test_dataset_summary_includes_symbol_with_only_ohlcv():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    MarketDataService().save_bars(
        [
            Bar(
                symbol="MSFT",
                timeframe="1Day",
                timestamp=start,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1000,
                source="alpaca",
            )
        ]
    )

    rows = DatasetService().summary()
    msft = next(row for row in rows if row.symbol == "MSFT")

    assert msft.news_count == 0
    assert msft.sentiment_coverage_pct == 0.0
    assert msft.has_news is False
    assert msft.has_ohlcv is True
