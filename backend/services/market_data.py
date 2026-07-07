from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from ..config import Settings, get_settings
from ..db import as_utc_naive, connection, rows_to_dicts
from ..providers.alpaca import AlpacaProvider, ProviderError
from ..schemas import Bar, MarketDataFetchSummary, MarketDataTimeframeSummary, SymbolResult
from ..time_utils import ensure_utc

PROVIDER = "alpaca"
ADJUSTMENT = "raw"
PARAMS_VERSION = "bars:v1"
DEFAULT_HISTORICAL_TIMEFRAMES = ("1Min", "5Min", "15Min", "1Hour", "1Day")
WINDOW_SIZES = {
    "1Min": timedelta(days=7),
    "5Min": timedelta(days=30),
    "15Min": timedelta(days=30),
    "1Hour": timedelta(days=30),
    "1Day": timedelta(days=365),
}


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
        await self.fetch_and_store_range(symbol, start, end, [timeframe], refresh=refresh)
        if not self._range_covered(symbol, timeframe, start, end):
            return []
        return [bar for bar in self._load_cached_bars(symbol, timeframe, start, end) if bar.source == PROVIDER]

    async def fetch_and_store_range(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframes: list[str] | tuple[str, ...] = DEFAULT_HISTORICAL_TIMEFRAMES,
        refresh: bool = False,
    ) -> MarketDataFetchSummary:
        symbol = symbol.upper()
        start = ensure_utc(start)
        end = ensure_utc(end)
        summaries: list[MarketDataTimeframeSummary] = []
        for timeframe in timeframes:
            summaries.append(
                await self._fetch_timeframe(
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                    refresh=refresh,
                )
            )
        return MarketDataFetchSummary(symbol=symbol, start=start, end=end, timeframes=summaries)

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

    def save_bars(self, bars: list[Bar]) -> int:
        if not bars:
            return 0
        new_count = 0
        with connection(self.settings) as con:
            for bar in bars:
                is_new = (
                    con.execute(
                        """
                        SELECT 1 FROM bars
                        WHERE symbol = ? AND timeframe = ? AND timestamp = ?
                        LIMIT 1
                        """,
                        [bar.symbol.upper(), bar.timeframe, as_utc_naive(bar.timestamp)],
                    ).fetchone()
                    is None
                )
                con.execute(
                    """
                    INSERT INTO bars
                    (symbol, timeframe, timestamp, open, high, low, close, volume, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
                    ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE SET
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        volume = excluded.volume,
                        source = excluded.source
                    """,
                    [
                        bar.symbol.upper(),
                        bar.timeframe,
                        as_utc_naive(bar.timestamp),
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        bar.source,
                    ],
                )
                if is_new:
                    new_count += 1
        return new_count

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

    async def _fetch_timeframe(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        refresh: bool,
    ) -> MarketDataTimeframeSummary:
        if end <= start:
            return MarketDataTimeframeSummary(timeframe=timeframe)

        fetched = 0
        new = 0
        failed_windows = 0

        if self.settings.has_alpaca_credentials:
            windows = (
                self._split_windows(timeframe, start, end)
                if refresh
                else self._missing_windows(symbol, timeframe, start, end)
            )
            for window_start, window_end in windows:
                try:
                    bars = await self.alpaca.fetch_bars(symbol, timeframe, window_start, window_end)
                    fetched += len(bars)
                    new += self.save_bars(bars)
                    self._save_coverage(symbol, timeframe, window_start, window_end, "completed", len(bars))
                except Exception as exc:
                    failed_windows += 1
                    self._save_coverage(symbol, timeframe, window_start, window_end, "failed", 0, str(exc))

        total = self.count_bars(symbol, timeframe, start, end)
        return MarketDataTimeframeSummary(
            timeframe=timeframe,
            total=total,
            fetched=fetched,
            new=new,
            existing=max(total - new, 0),
            failed_windows=failed_windows,
        )

    def count_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> int:
        with connection(self.settings) as con:
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM bars
                WHERE symbol = ? AND timeframe = ? AND source = ?
                  AND timestamp BETWEEN ? AND ?
                """,
                [symbol.upper(), timeframe, PROVIDER, as_utc_naive(start), as_utc_naive(end)],
            ).fetchone()
        return int(row[0]) if row else 0

    def _range_covered(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> bool:
        return not self._missing_windows(symbol, timeframe, start, end)

    def _coverage_exists(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> bool:
        with connection(self.settings) as con:
            row = con.execute(
                """
                SELECT 1
                FROM bars_fetch_coverage
                WHERE provider = ? AND symbol = ? AND timeframe = ? AND status = 'completed'
                  AND params_hash = ?
                  AND start_at <= ? AND end_at >= ?
                LIMIT 1
                """,
                [
                    PROVIDER,
                    symbol.upper(),
                    timeframe,
                    self._params_hash(),
                    as_utc_naive(start),
                    as_utc_naive(end),
                ],
            ).fetchone()
        return row is not None

    def _save_coverage(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        status: str,
        bar_count: int,
        error: str | None = None,
    ) -> None:
        coverage_id = hashlib.sha1(
            f"{PROVIDER}:{symbol.upper()}:{timeframe}:{start.isoformat()}:{end.isoformat()}:{self._params_hash()}".encode()
        ).hexdigest()
        with connection(self.settings) as con:
            con.execute(
                """
                INSERT INTO bars_fetch_coverage
                (id, provider, symbol, timeframe, start_at, end_at, status, fetched_at,
                 params_hash, bar_count, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    status = excluded.status,
                    fetched_at = excluded.fetched_at,
                    bar_count = excluded.bar_count,
                    error = excluded.error
                """,
                [
                    coverage_id,
                    PROVIDER,
                    symbol.upper(),
                    timeframe,
                    as_utc_naive(start),
                    as_utc_naive(end),
                    status,
                    self._params_hash(),
                    bar_count,
                    error,
                ],
            )

    def _missing_windows(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        missing = [(start, end)]
        for coverage_start, coverage_end in self._completed_coverage_intervals(symbol, timeframe, start, end):
            next_missing: list[tuple[datetime, datetime]] = []
            for segment_start, segment_end in missing:
                if coverage_end <= segment_start or coverage_start >= segment_end:
                    next_missing.append((segment_start, segment_end))
                    continue
                if coverage_start > segment_start:
                    next_missing.append((segment_start, min(coverage_start, segment_end)))
                if coverage_end < segment_end:
                    next_missing.append((max(coverage_end, segment_start), segment_end))
            missing = next_missing
        windows: list[tuple[datetime, datetime]] = []
        for segment_start, segment_end in missing:
            windows.extend(self._split_windows(timeframe, segment_start, segment_end))
        return windows

    def _completed_coverage_intervals(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        with connection(self.settings) as con:
            rows = con.execute(
                """
                SELECT start_at, end_at
                FROM bars_fetch_coverage
                WHERE provider = ? AND symbol = ? AND timeframe = ? AND status = 'completed'
                  AND params_hash = ?
                  AND end_at > ? AND start_at < ?
                ORDER BY start_at ASC
                """,
                [
                    PROVIDER,
                    symbol.upper(),
                    timeframe,
                    self._params_hash(),
                    as_utc_naive(start),
                    as_utc_naive(end),
                ],
            ).fetchall()
        return [(ensure_utc(row[0]), ensure_utc(row[1])) for row in rows]

    def _split_windows(self, timeframe: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        windows: list[tuple[datetime, datetime]] = []
        window_size = WINDOW_SIZES.get(timeframe, timedelta(days=30))
        current = start
        while current < end:
            window_end = min(current + window_size, end)
            windows.append((current, window_end))
            current = window_end
        return windows

    def _params_hash(self) -> str:
        return hashlib.sha1(
            f"{PARAMS_VERSION}:provider={PROVIDER}:feed={self.settings.alpaca_data_feed}:adjustment={ADJUSTMENT}".encode()
        ).hexdigest()
