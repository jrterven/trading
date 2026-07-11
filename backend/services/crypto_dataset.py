from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import duckdb

from ..config import Settings, get_settings
from ..db import as_utc_naive, rows_to_dicts
from ..schemas import (
    Bar,
    DatasetBarCoverage,
    DatasetSummaryRow,
    MarketDataFetchSummary,
    MarketDataTimeframeSummary,
    NewsArticle,
    NewsFetchDailyStats,
    NewsFetchDayCount,
    NewsFetchResponse,
    NewsFetchSummary,
    SentimentScore,
    SymbolResult,
)
from ..time_utils import ensure_utc, utc_now

RelationFilter = Literal["all", "direct", "indirect"]

TIMEFRAMES = ("1Min", "5Min", "15Min", "1Hour", "1Day")
CRYPTO_SYMBOLS: tuple[SymbolResult, ...] = (
    SymbolResult(symbol="BTC/USD", name="Bitcoin / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="ETH/USD", name="Ethereum / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="SOL/USD", name="Solana / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="XRP/USD", name="XRP / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="DOGE/USD", name="Dogecoin / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="ADA/USD", name="Cardano / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="AVAX/USD", name="Avalanche / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="LINK/USD", name="Chainlink / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="LTC/USD", name="Litecoin / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="BCH/USD", name="Bitcoin Cash / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="DOT/USD", name="Polkadot / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="UNI/USD", name="Uniswap / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="AAVE/USD", name="Aave / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="SHIB/USD", name="Shiba Inu / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="PEPE/USD", name="Pepe / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="BONK/USD", name="Bonk / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="ARB/USD", name="Arbitrum / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="FIL/USD", name="Filecoin / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="GRT/USD", name="The Graph / US Dollar", exchange="Alpaca Crypto", tradable=True),
    SymbolResult(symbol="CRV/USD", name="Curve / US Dollar", exchange="Alpaca Crypto", tradable=True),
)


class CryptoDatasetService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db_path = self.settings.root_dir / "data" / "crypto" / "crypto.duckdb"

    async def search_symbols(self, query: str | None = None) -> list[SymbolResult]:
        needle = (query or "").strip().upper()
        if not needle:
            return list(CRYPTO_SYMBOLS)
        compact_needle = needle.replace("/", "")
        matches = [
            item
            for item in CRYPTO_SYMBOLS
            if needle in item.symbol
            or compact_needle in item.symbol.replace("/", "")
            or needle in item.name.upper()
        ]
        return matches or list(CRYPTO_SYMBOLS)

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        symbol = self._normalize_symbol(symbol)
        start = ensure_utc(start)
        end = ensure_utc(end)
        with self._connection() as con:
            if con is None:
                return []
            rows = rows_to_dicts(
                con.execute(
                    """
                    SELECT symbol, timeframe, timestamp, open, high, low, close, volume, source
                    FROM bars
                    WHERE symbol = ? AND timeframe = ? AND timestamp BETWEEN ? AND ?
                    ORDER BY timestamp
                    """,
                    [symbol, timeframe, as_utc_naive(start), as_utc_naive(end)],
                )
            )
        return [Bar(**row) for row in rows]

    def get_articles(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
        relation_type: RelationFilter = "all",
    ) -> list[NewsArticle]:
        symbol = self._normalize_symbol(symbol)
        start = ensure_utc(start) if start else datetime(1970, 1, 1)
        end = ensure_utc(end) if end else utc_now() + timedelta(days=1)
        clauses = ["nas.symbol = ?", "na.published_at BETWEEN ? AND ?"]
        params: list[Any] = [symbol, as_utc_naive(start), as_utc_naive(end)]
        if relation_type != "all":
            clauses.append("nas.relation_type = ?")
            params.append(relation_type)
        params.append(limit)
        with self._connection() as con:
            if con is None:
                return []
            rows = rows_to_dicts(
                con.execute(
                    f"""
                    SELECT na.id, na.source, nas.symbol, na.headline, na.summary, na.url, na.author,
                           na.published_at, COALESCE(na.available_at, na.published_at) AS available_at,
                           na.content, na.raw_symbols, nas.relation_type, nas.relevance_score,
                           nas.relation_reason, nas.classifier_model, nas.classifier_version
                    FROM news_articles na
                    JOIN news_article_symbols nas ON nas.article_id = na.id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY na.published_at DESC
                    LIMIT ?
                    """,
                    params,
                )
            )
        return [self._article_from_row(row) for row in rows]

    def fetch_with_summary(
        self,
        symbol: str,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        relation_type: RelationFilter,
    ) -> NewsFetchResponse:
        symbol = self._normalize_symbol(symbol)
        start = ensure_utc(start) if start else utc_now() - timedelta(days=14)
        end = ensure_utc(end) if end else utc_now()
        articles = self.get_articles(symbol, start=start, end=end, limit=limit, relation_type=relation_type)
        total = self.count_articles(symbol, start, end)
        return NewsFetchResponse(
            articles=articles,
            summary=NewsFetchSummary(
                total=total,
                fetched=0,
                existing=total,
                new=0,
                daily=self._daily_stats(start, end, self.count_articles_by_day(symbol, start, end)),
                market_data=self.market_data_summary(symbol, start, end),
            ),
        )

    def get_scores(
        self,
        symbol: str,
        article_ids: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[SentimentScore]:
        symbol = self._normalize_symbol(symbol)
        clauses = ["ss.symbol = ?"]
        params: list[Any] = [symbol]
        if article_ids:
            placeholders = ",".join(["?"] * len(article_ids))
            clauses.append(f"ss.article_id IN ({placeholders})")
            params.extend(article_ids)
        if start:
            clauses.append("COALESCE(na.available_at, na.published_at) >= ?")
            params.append(as_utc_naive(ensure_utc(start)))
        if end:
            clauses.append("COALESCE(na.available_at, na.published_at) <= ?")
            params.append(as_utc_naive(ensure_utc(end)))
        with self._connection() as con:
            if con is None:
                return []
            rows = rows_to_dicts(
                con.execute(
                    f"""
                    SELECT ss.id, ss.article_id, ss.symbol, ss.label, ss.score, ss.positive,
                           ss.neutral, ss.negative, ss.model, ss.model_version,
                           ss.prompt_version, ss.explanation, ss.created_at
                    FROM sentiment_scores ss
                    LEFT JOIN news_articles na ON na.id = ss.article_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY COALESCE(na.available_at, na.published_at, ss.created_at) DESC
                    """,
                    params,
                )
            )
        return [SentimentScore(**row) for row in rows]

    def summary(self) -> list[DatasetSummaryRow]:
        with self._connection() as con:
            if con is None:
                return []
            symbols = self._symbols(con)
            news = {row["symbol"]: row for row in self._news_summary(con)}
            sentiment = {row["symbol"]: row for row in self._sentiment_summary(con)}
            bars = self._bars_summary(con)

        rows: list[DatasetSummaryRow] = []
        for symbol in symbols:
            news_row = news.get(symbol, {})
            sentiment_row = sentiment.get(symbol, {})
            bar_rows = bars.get(symbol, {})
            news_count = int(news_row.get("news_count") or 0)
            sentiment_count = int(sentiment_row.get("sentiment_count") or 0)
            coverage = round((sentiment_count / news_count) * 100, 2) if news_count else 0.0
            bar_coverages = [
                DatasetBarCoverage(
                    timeframe=timeframe,
                    count=int(bar_rows.get(timeframe, {}).get("count") or 0),
                    start=bar_rows.get(timeframe, {}).get("start"),
                    end=bar_rows.get(timeframe, {}).get("end"),
                )
                for timeframe in TIMEFRAMES
            ]
            rows.append(
                DatasetSummaryRow(
                    symbol=symbol,
                    news_count=news_count,
                    news_start=news_row.get("news_start"),
                    news_end=news_row.get("news_end"),
                    sentiment_count=sentiment_count,
                    sentiment_coverage_pct=coverage,
                    bars=bar_coverages,
                    has_news=news_count > 0,
                    has_sentiment=sentiment_count > 0,
                    has_ohlcv=any(item.count > 0 for item in bar_coverages),
                )
            )
        return sorted(rows, key=lambda row: row.symbol)

    def count_articles(self, symbol: str, start: datetime, end: datetime) -> int:
        symbol = self._normalize_symbol(symbol)
        with self._connection() as con:
            if con is None:
                return 0
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM news_articles na
                JOIN news_article_symbols nas ON nas.article_id = na.id
                WHERE nas.symbol = ? AND na.published_at BETWEEN ? AND ?
                """,
                [symbol, as_utc_naive(start), as_utc_naive(end)],
            ).fetchone()
        return int(row[0]) if row else 0

    def count_articles_by_day(self, symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        symbol = self._normalize_symbol(symbol)
        with self._connection() as con:
            if con is None:
                return []
            return rows_to_dicts(
                con.execute(
                    """
                    SELECT CAST(CAST(na.published_at AS DATE) AS TEXT) AS date, COUNT(*) AS count
                    FROM news_articles na
                    JOIN news_article_symbols nas ON nas.article_id = na.id
                    WHERE nas.symbol = ? AND na.published_at BETWEEN ? AND ?
                    GROUP BY CAST(na.published_at AS DATE)
                    ORDER BY CAST(na.published_at AS DATE) DESC
                    """,
                    [symbol, as_utc_naive(start), as_utc_naive(end)],
                )
            )

    def market_data_summary(self, symbol: str, start: datetime, end: datetime) -> MarketDataFetchSummary:
        symbol = self._normalize_symbol(symbol)
        with self._connection() as con:
            if con is None:
                rows: list[dict[str, Any]] = []
            else:
                rows = rows_to_dicts(
                    con.execute(
                        """
                        SELECT timeframe, COUNT(*) AS total
                        FROM bars
                        WHERE symbol = ? AND timestamp BETWEEN ? AND ?
                        GROUP BY timeframe
                        """,
                        [symbol, as_utc_naive(start), as_utc_naive(end)],
                    )
                )
        totals = {row["timeframe"]: int(row["total"] or 0) for row in rows}
        return MarketDataFetchSummary(
            symbol=symbol,
            start=start,
            end=end,
            timeframes=[
                MarketDataTimeframeSummary(
                    timeframe=timeframe,
                    total=totals.get(timeframe, 0),
                    fetched=0,
                    new=0,
                    existing=totals.get(timeframe, 0),
                    failed_windows=0,
                )
                for timeframe in TIMEFRAMES
            ],
        )

    @contextmanager
    def _connection(self) -> Iterator[duckdb.DuckDBPyConnection | None]:
        if not self.db_path.exists():
            yield None
            return
        try:
            con = duckdb.connect(str(self.db_path), read_only=True)
        except duckdb.IOException:
            yield None
            return
        try:
            yield con
        finally:
            con.close()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        value = symbol.strip().upper()
        if "/" not in value and any(item.symbol.startswith(f"{value}/") for item in CRYPTO_SYMBOLS):
            return f"{value}/USD"
        return value

    @staticmethod
    def _article_from_row(row: dict[str, Any]) -> NewsArticle:
        raw_symbols = row.get("raw_symbols") or "[]"
        if isinstance(raw_symbols, str):
            row["raw_symbols"] = json.loads(raw_symbols)
        return NewsArticle(**row)

    @staticmethod
    def _daily_stats(
        start: datetime,
        end: datetime,
        by_day: list[dict[str, Any]],
    ) -> NewsFetchDailyStats:
        start_date = start.date()
        end_date = (end - timedelta(microseconds=1)).date() if end > start else end.date()
        day_count = (end_date - start_date).days + 1
        if day_count <= 0:
            return NewsFetchDailyStats()
        counts = {str(row["date"]): int(row["count"]) for row in by_day}
        days = [
            NewsFetchDayCount(
                date=(start_date + timedelta(days=offset)).isoformat(),
                count=counts.get((start_date + timedelta(days=offset)).isoformat(), 0),
            )
            for offset in range(day_count)
        ]
        max_day = max(days, key=lambda item: (item.count, item.date))
        min_day = min(days, key=lambda item: (item.count, item.date))
        average = round(sum(item.count for item in days) / len(days), 2)
        return NewsFetchDailyStats(max=max_day, min=min_day, average=average)

    @staticmethod
    def _symbols(con: duckdb.DuckDBPyConnection) -> list[str]:
        rows = con.execute(
            """
            SELECT symbol FROM bars
            UNION
            SELECT symbol FROM news_article_symbols
            UNION
            SELECT symbol FROM sentiment_scores
            ORDER BY symbol
            """
        ).fetchall()
        return [str(row[0]).upper() for row in rows]

    @staticmethod
    def _news_summary(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        return rows_to_dicts(
            con.execute(
                """
                SELECT nas.symbol,
                       COUNT(DISTINCT na.id) AS news_count,
                       MIN(na.published_at) AS news_start,
                       MAX(na.published_at) AS news_end
                FROM news_articles na
                JOIN news_article_symbols nas ON nas.article_id = na.id
                GROUP BY nas.symbol
                """
            )
        )

    @staticmethod
    def _sentiment_summary(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        return rows_to_dicts(
            con.execute(
                """
                SELECT symbol,
                       COUNT(DISTINCT article_id) AS sentiment_count
                FROM sentiment_scores
                GROUP BY symbol
                """
            )
        )

    @staticmethod
    def _bars_summary(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, dict[str, Any]]]:
        rows = rows_to_dicts(
            con.execute(
                """
                SELECT symbol,
                       timeframe,
                       COUNT(*) AS count,
                       MIN(timestamp) AS start,
                       MAX(timestamp) AS end
                FROM bars
                GROUP BY symbol, timeframe
                """
            )
        )
        result: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            symbol = str(row["symbol"]).upper()
            timeframe = str(row["timeframe"])
            result.setdefault(symbol, {})[timeframe] = row
        return result


def crypto_db_path(settings: Settings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.root_dir / "data" / "crypto" / "crypto.duckdb"
