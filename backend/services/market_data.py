from __future__ import annotations

from datetime import datetime

from ..config import Settings, get_settings
from ..db import as_utc_naive, connection, rows_to_dicts
from ..providers.alpaca import AlpacaProvider, ProviderError
from ..schemas import Bar, SymbolResult
from ..time_utils import ensure_utc


class MarketDataService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.alpaca = AlpacaProvider(self.settings)

    async def search_symbols(self, query: str | None = None) -> list[SymbolResult]:
        try:
            return await self.alpaca.search_symbols(query)
        except ProviderError:
            return []

    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        refresh: bool = False,
    ) -> list[Bar]:
        symbol = symbol.upper()
        start = ensure_utc(start)
        end = ensure_utc(end)
        cached = [] if refresh else self._load_cached_bars(symbol, timeframe, start, end)
        if cached:
            return [bar for bar in cached if bar.source == "alpaca"]

        try:
            fetched = await self.alpaca.fetch_bars(symbol, timeframe, start, end)
        except ProviderError:
            fetched = []

        if not fetched:
            return []
        else:
            self.delete_bars_range(symbol, timeframe, start, end)
        self.save_bars(fetched)
        saved = self._load_cached_bars(symbol, timeframe, start, end) or fetched
        return [bar for bar in saved if bar.source == "alpaca"]

    def latest_price(self, symbol: str) -> float | None:
        with connection(self.settings) as con:
            row = con.execute(
                """
                SELECT close FROM bars
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                [symbol.upper()],
            ).fetchone()
        return float(row[0]) if row else None

    def save_bars(self, bars: list[Bar]) -> None:
        if not bars:
            return
        with connection(self.settings) as con:
            for bar in bars:
                con.execute(
                    "DELETE FROM bars WHERE symbol = ? AND timeframe = ? AND timestamp = ?",
                    [bar.symbol, bar.timeframe, as_utc_naive(bar.timestamp)],
                )
            con.executemany(
                """
                INSERT INTO bars
                (symbol, timeframe, timestamp, open, high, low, close, volume, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
                """,
                [
                    [
                        bar.symbol,
                        bar.timeframe,
                        as_utc_naive(bar.timestamp),
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        bar.source,
                    ]
                    for bar in bars
                ],
            )

    def delete_bars_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> None:
        with connection(self.settings) as con:
            con.execute(
                """
                DELETE FROM bars
                WHERE symbol = ? AND timeframe = ? AND timestamp BETWEEN ? AND ?
                """,
                [symbol.upper(), timeframe, as_utc_naive(start), as_utc_naive(end)],
            )

    def _load_cached_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        with connection(self.settings) as con:
            rows = rows_to_dicts(
                con.execute(
                    """
                    SELECT symbol, timeframe, timestamp, open, high, low, close, volume, source
                    FROM bars
                    WHERE symbol = ? AND timeframe = ? AND timestamp BETWEEN ? AND ?
                    ORDER BY timestamp ASC
                    """,
                    [symbol, timeframe, as_utc_naive(start), as_utc_naive(end)],
                )
            )
        return [Bar(**row) for row in rows]
