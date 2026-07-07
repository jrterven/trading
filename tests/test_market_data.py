from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.config import get_settings
from backend.providers.alpaca import AlpacaProvider
from backend.schemas import Bar
from backend.services.market_data import DEFAULT_HISTORICAL_TIMEFRAMES, MarketDataService


def make_bar(symbol: str, timeframe: str, timestamp: datetime, close: float = 100) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1000,
        source="alpaca",
    )


def test_save_bars_is_idempotent():
    service = MarketDataService()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [
        make_bar("AAPL", "1Day", start),
        make_bar("AAPL", "1Day", start + timedelta(days=1), close=101),
    ]

    assert service.save_bars(bars) == 2
    assert service.save_bars(bars) == 0
    assert service.count_bars("AAPL", "1Day", start, start + timedelta(days=2)) == 2


@pytest.mark.asyncio
async def test_fetch_range_downloads_only_missing_segments(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    get_settings.cache_clear()

    class FakeAlpaca:
        def __init__(self) -> None:
            self.calls: list[tuple[datetime, datetime]] = []

        async def fetch_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime, limit: int = 10000):
            self.calls.append((start, end))
            return [make_bar(symbol, timeframe, start + timedelta(minutes=1), close=100 + len(self.calls))]

    service = MarketDataService()
    fake = FakeAlpaca()
    service.alpaca = fake  # type: ignore[assignment]
    start = datetime(2026, 1, 1, tzinfo=UTC)

    await service.fetch_and_store_range("AAPL", start, start + timedelta(days=10), ["1Min"])
    first_call_count = len(fake.calls)
    await service.fetch_and_store_range("AAPL", start, start + timedelta(days=20), ["1Min"])
    second_calls = fake.calls[first_call_count:]

    assert first_call_count == 2
    assert second_calls
    assert all(call_start >= start + timedelta(days=10) for call_start, _ in second_calls)


@pytest.mark.asyncio
async def test_get_bars_fetches_when_cache_is_partial(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    get_settings.cache_clear()

    class FakeAlpaca:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime, limit: int = 10000):
            self.calls += 1
            return [
                make_bar(symbol, timeframe, start, close=100),
                make_bar(symbol, timeframe, start + timedelta(days=1), close=101),
            ]

    service = MarketDataService()
    fake = FakeAlpaca()
    service.alpaca = fake  # type: ignore[assignment]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    service.save_bars([make_bar("AAPL", "1Day", start, close=90)])

    bars = await service.get_bars("AAPL", "1Day", start, start + timedelta(days=2))

    assert fake.calls == 1
    assert len(bars) == 2
    assert bars[0].close == 100


@pytest.mark.asyncio
async def test_fetch_range_caches_all_default_timeframes(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    get_settings.cache_clear()

    class FakeAlpaca:
        def __init__(self) -> None:
            self.timeframes: list[str] = []

        async def fetch_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime, limit: int = 10000):
            self.timeframes.append(timeframe)
            return [make_bar(symbol, timeframe, start + timedelta(minutes=1))]

    service = MarketDataService()
    fake = FakeAlpaca()
    service.alpaca = fake  # type: ignore[assignment]
    start = datetime(2026, 1, 1, tzinfo=UTC)

    summary = await service.fetch_and_store_range(
        "AAPL",
        start,
        start + timedelta(days=1),
        DEFAULT_HISTORICAL_TIMEFRAMES,
    )

    assert {item.timeframe for item in summary.timeframes} == set(DEFAULT_HISTORICAL_TIMEFRAMES)
    assert set(fake.timeframes) == set(DEFAULT_HISTORICAL_TIMEFRAMES)


@pytest.mark.asyncio
async def test_alpaca_bars_paginates(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    get_settings.cache_clear()
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def json(self) -> dict[str, Any]:
            return self.payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            calls.append(dict(params))
            page = len(calls)
            payload = {
                "bars": {
                    "AAPL": [
                        {
                            "t": f"2026-01-0{page}T14:30:00Z",
                            "o": page,
                            "h": page + 1,
                            "l": page - 1,
                            "c": page,
                            "v": 100,
                        }
                    ]
                }
            }
            if page == 1:
                payload["next_page_token"] = "next"
            return FakeResponse(payload)

    monkeypatch.setattr("backend.providers.alpaca.httpx.AsyncClient", lambda timeout: FakeClient())

    bars = await AlpacaProvider(get_settings()).fetch_bars(
        "AAPL",
        "1Day",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 3, tzinfo=UTC),
    )

    assert len(bars) == 2
    assert calls[1]["page_token"] == "next"
