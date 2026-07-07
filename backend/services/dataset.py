from __future__ import annotations

from ..config import Settings, get_settings
from ..db import connection, rows_to_dicts
from ..schemas import DatasetBarCoverage, DatasetSummaryRow

TIMEFRAMES = ("1Min", "5Min", "15Min", "1Hour", "1Day")


class DatasetService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def summary(self) -> list[DatasetSummaryRow]:
        symbols = self._symbols()
        news = {row["symbol"]: row for row in self._news_summary()}
        sentiment = {row["symbol"]: row for row in self._sentiment_summary()}
        bars = self._bars_summary()

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

    def _symbols(self) -> list[str]:
        with connection(self.settings) as con:
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

    def _news_summary(self) -> list[dict]:
        with connection(self.settings) as con:
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

    def _sentiment_summary(self) -> list[dict]:
        with connection(self.settings) as con:
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

    def _bars_summary(self) -> dict[str, dict[str, dict]]:
        with connection(self.settings) as con:
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
        result: dict[str, dict[str, dict]] = {}
        for row in rows:
            symbol = str(row["symbol"]).upper()
            timeframe = str(row["timeframe"])
            result.setdefault(symbol, {})[timeframe] = row
        return result
