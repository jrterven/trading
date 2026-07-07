from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Literal

from ..config import Settings, get_settings
from ..db import as_utc_naive, connection, rows_to_dicts
from ..providers.alpaca import AlpacaProvider, ProviderError
from ..schemas import (
    MarketDataFetchSummary,
    NewsArticle,
    NewsFetchDailyStats,
    NewsFetchDayCount,
    NewsFetchResponse,
    NewsFetchSummary,
)
from ..time_utils import ensure_utc, utc_now
from .market_data import DEFAULT_HISTORICAL_TIMEFRAMES, MarketDataService

RelationFilter = Literal["all", "direct", "indirect"]

CLASSIFIER_MODEL = "rules-news-relevance"
CLASSIFIER_VERSION = "2026-07-07"
PROVIDER = "alpaca"
WINDOW_SIZE = timedelta(days=1)

COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("AAPL", "Apple", "iPhone", "Mac", "iPad"),
    "MSFT": ("MSFT", "Microsoft", "Azure", "Windows", "OpenAI"),
    "NVDA": ("NVDA", "Nvidia", "GPU", "AI chip"),
    "TSLA": ("TSLA", "Tesla", "EV", "Model Y"),
    "AMZN": ("AMZN", "Amazon", "AWS", "Prime"),
    "META": ("META", "Meta", "Facebook", "Instagram"),
    "GOOGL": ("GOOGL", "GOOG", "Alphabet", "Google", "YouTube"),
    "JPM": ("JPM", "JPMorgan", "Chase"),
    "SPY": ("SPY", "S&P 500", "broad market"),
    "QQQ": ("QQQ", "Nasdaq 100", "technology index"),
}

INDIRECT_TERMS = {
    "supplier",
    "supply chain",
    "semiconductor",
    "chip",
    "chips",
    "regulation",
    "regulatory",
    "antitrust",
    "rates",
    "inflation",
    "consumer demand",
    "market selloff",
    "technology sector",
    "tech sector",
    "competitor",
}


class NewsService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.alpaca = AlpacaProvider(self.settings)
        self.market_data = MarketDataService(self.settings)

    async def fetch_and_store(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        include_rss: bool = True,
        limit: int = 30,
        relation_type: RelationFilter = "all",
    ) -> list[NewsArticle]:
        result = await self.fetch_and_store_with_summary(
            symbol=symbol,
            start=start,
            end=end,
            include_rss=include_rss,
            limit=limit,
            relation_type=relation_type,
        )
        return result.articles

    async def fetch_and_store_with_summary(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        include_rss: bool = True,
        limit: int = 30,
        relation_type: RelationFilter = "all",
    ) -> NewsFetchResponse:
        symbol = symbol.upper()
        start = ensure_utc(start) if start else utc_now() - timedelta(days=14)
        end = ensure_utc(end) if end else utc_now()
        if not self.settings.has_alpaca_credentials:
            articles = self.get_articles(
                symbol,
                start=start,
                end=end,
                limit=limit,
                relation_type=relation_type,
            )
            return NewsFetchResponse(
                articles=articles,
                summary=self._build_summary(symbol, start, end, articles, fetched=0, new=0),
            )
        fetched = 0
        new = 0
        for window_start, window_end in self._missing_windows(symbol, start, end):
            try:
                articles = await self.alpaca.fetch_news(
                    symbol,
                    window_start,
                    window_end,
                    limit=50,
                )
                fetched += len(articles)
                new += self.save_articles(articles, requested_symbol=symbol)
                self._save_coverage(symbol, window_start, window_end, "completed", len(articles))
            except ProviderError as exc:
                self._save_coverage(symbol, window_start, window_end, "failed", 0, str(exc))

        market_data = await self.market_data.fetch_and_store_range(
            symbol=symbol,
            start=start,
            end=end,
            timeframes=DEFAULT_HISTORICAL_TIMEFRAMES,
        )
        articles = self.get_articles(
            symbol,
            start=start,
            end=end,
            limit=limit,
            relation_type=relation_type,
        )
        return NewsFetchResponse(
            articles=articles,
            summary=self._build_summary(
                symbol,
                start,
                end,
                articles,
                fetched=fetched,
                new=new,
                market_data=market_data,
            ),
        )

    def get_articles(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
        relation_type: RelationFilter = "all",
    ) -> list[NewsArticle]:
        symbol = symbol.upper()
        start = ensure_utc(start) if start else datetime(1970, 1, 1)
        end = ensure_utc(end) if end else utc_now() + timedelta(days=1)
        clauses = ["nas.symbol = ?", "na.source = 'alpaca'", "na.published_at BETWEEN ? AND ?"]
        params: list[Any] = [symbol, as_utc_naive(start), as_utc_naive(end)]
        if relation_type != "all":
            clauses.append("nas.relation_type = ?")
            params.append(relation_type)
        params.append(limit)
        with connection(self.settings) as con:
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
            if not rows and relation_type in {"all", "direct"}:
                rows = rows_to_dicts(
                    con.execute(
                        """
                        SELECT id, source, symbol, headline, summary, url, author,
                               published_at, COALESCE(available_at, published_at) AS available_at,
                               content, raw_symbols, 'direct' AS relation_type, 1.0 AS relevance_score,
                               'legacy symbol match' AS relation_reason,
                               'legacy' AS classifier_model, 'legacy' AS classifier_version
                        FROM news_articles
                        WHERE symbol = ? AND source = 'alpaca' AND published_at BETWEEN ? AND ?
                        ORDER BY published_at DESC
                        LIMIT ?
                        """,
                        [symbol, as_utc_naive(start), as_utc_naive(end), limit],
                    )
                )
        articles: list[NewsArticle] = []
        for row in rows:
            row["raw_symbols"] = json.loads(row["raw_symbols"] or "[]")
            articles.append(NewsArticle(**row))
        return articles

    def save_articles(self, articles: list[NewsArticle], requested_symbol: str | None = None) -> int:
        if not articles:
            return 0
        requested_symbol = (requested_symbol or articles[0].symbol).upper()
        new_count = 0
        with connection(self.settings) as con:
            for article in articles:
                is_new_relation = (
                    con.execute(
                        """
                        SELECT 1 FROM news_article_symbols
                        WHERE article_id = ? AND symbol = ?
                        LIMIT 1
                        """,
                        [article.id, requested_symbol],
                    ).fetchone()
                    is None
                )
                relation = classify_relation(article, requested_symbol)
                available_at = article.available_at or article.published_at
                con.execute(
                    """
                    INSERT INTO news_articles
                    (id, source, symbol, headline, summary, url, author, published_at,
                     content, raw_symbols, available_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
                    ON CONFLICT (id) DO UPDATE SET
                        source = excluded.source,
                        headline = excluded.headline,
                        summary = excluded.summary,
                        url = excluded.url,
                        author = excluded.author,
                        published_at = excluded.published_at,
                        content = excluded.content,
                        raw_symbols = excluded.raw_symbols,
                        available_at = excluded.available_at
                    """,
                    [
                        article.id,
                        article.source,
                        article.symbol,
                        article.headline,
                        article.summary,
                        article.url,
                        article.author,
                        as_utc_naive(article.published_at),
                        article.content,
                        json.dumps(article.raw_symbols),
                        as_utc_naive(available_at),
                    ],
                )
                con.execute(
                    """
                    INSERT INTO news_article_symbols
                    (article_id, symbol, relation_type, relevance_score, relation_reason,
                     classifier_model, classifier_version, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp, current_timestamp)
                    ON CONFLICT (article_id, symbol) DO UPDATE SET
                        relation_type = excluded.relation_type,
                        relevance_score = excluded.relevance_score,
                        relation_reason = excluded.relation_reason,
                        classifier_model = excluded.classifier_model,
                        classifier_version = excluded.classifier_version,
                        updated_at = now()
                    """,
                    [
                        article.id,
                        requested_symbol,
                        relation["relation_type"],
                        relation["relevance_score"],
                        relation["relation_reason"],
                        CLASSIFIER_MODEL,
                        CLASSIFIER_VERSION,
                    ],
                )
                if is_new_relation:
                    new_count += 1
        return new_count

    def _build_summary(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        articles: list[NewsArticle],
        fetched: int,
        new: int,
        market_data: MarketDataFetchSummary | None = None,
    ) -> NewsFetchSummary:
        total = self.count_articles(symbol, start, end)
        daily = self._daily_stats(start, end, self.count_articles_by_day(symbol, start, end))
        existing = max(total - new, 0)
        return NewsFetchSummary(
            total=total,
            fetched=fetched,
            existing=existing,
            new=new,
            daily=daily,
            market_data=market_data,
        )

    def count_articles(self, symbol: str, start: datetime, end: datetime) -> int:
        with connection(self.settings) as con:
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM news_articles na
                JOIN news_article_symbols nas ON nas.article_id = na.id
                WHERE nas.symbol = ? AND na.source = 'alpaca'
                  AND na.published_at BETWEEN ? AND ?
                """,
                [symbol.upper(), as_utc_naive(start), as_utc_naive(end)],
            ).fetchone()
        return int(row[0]) if row else 0

    def count_articles_by_day(self, symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        with connection(self.settings) as con:
            return rows_to_dicts(
                con.execute(
                    """
                    SELECT CAST(CAST(na.published_at AS DATE) AS TEXT) AS date, COUNT(*) AS count
                    FROM news_articles na
                    JOIN news_article_symbols nas ON nas.article_id = na.id
                    WHERE nas.symbol = ? AND na.source = 'alpaca'
                      AND na.published_at BETWEEN ? AND ?
                    GROUP BY CAST(na.published_at AS DATE)
                    ORDER BY CAST(na.published_at AS DATE) DESC
                    """,
                    [symbol.upper(), as_utc_naive(start), as_utc_naive(end)],
                )
            )

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
        days: list[NewsFetchDayCount] = []
        for offset in range(day_count):
            date = start_date + timedelta(days=offset)
            days.append(NewsFetchDayCount(date=date.isoformat(), count=counts.get(date.isoformat(), 0)))
        max_day = max(days, key=lambda item: (item.count, item.date))
        min_day = min(days, key=lambda item: (item.count, item.date))
        average = round(sum(item.count for item in days) / len(days), 2)
        return NewsFetchDailyStats(max=max_day, min=min_day, average=average)

    def _missing_windows(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        windows: list[tuple[datetime, datetime]] = []
        current = start
        while current < end:
            window_end = min(current + WINDOW_SIZE, end)
            if not self._coverage_exists(symbol, current, window_end):
                windows.append((current, window_end))
            current = window_end
        return windows

    def _coverage_exists(self, symbol: str, start: datetime, end: datetime) -> bool:
        with connection(self.settings) as con:
            row = con.execute(
                """
                SELECT 1
                FROM news_fetch_coverage
                WHERE provider = ? AND symbol = ? AND status = 'completed'
                  AND params_hash = ?
                  AND start_at <= ? AND end_at >= ?
                LIMIT 1
                """,
                [
                    PROVIDER,
                    symbol.upper(),
                    self._params_hash(),
                    as_utc_naive(start),
                    as_utc_naive(end),
                ],
            ).fetchone()
        return row is not None

    def _save_coverage(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        status: str,
        article_count: int,
        error: str | None = None,
    ) -> None:
        coverage_id = hashlib.sha1(
            f"{PROVIDER}:{symbol.upper()}:{start.isoformat()}:{end.isoformat()}:{self._params_hash()}".encode()
        ).hexdigest()
        with connection(self.settings) as con:
            con.execute(
                """
                INSERT INTO news_fetch_coverage
                (id, provider, symbol, start_at, end_at, status, fetched_at, params_hash,
                 article_count, error)
                VALUES (?, ?, ?, ?, ?, ?, current_timestamp, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    status = excluded.status,
                    fetched_at = excluded.fetched_at,
                    article_count = excluded.article_count,
                    error = excluded.error
                """,
                [
                    coverage_id,
                    PROVIDER,
                    symbol.upper(),
                    as_utc_naive(start),
                    as_utc_naive(end),
                    status,
                    self._params_hash(),
                    article_count,
                    error,
                ],
            )

    @staticmethod
    def _params_hash() -> str:
        return hashlib.sha1(b"alpaca-news:v1:include_content=true").hexdigest()


def classify_relation(article: NewsArticle, requested_symbol: str) -> dict[str, str | float]:
    symbol = requested_symbol.upper()
    raw_symbols = {item.upper() for item in article.raw_symbols}
    text = " ".join(
        item for item in [article.headline, article.summary, article.content] if item
    ).lower()
    aliases = COMPANY_ALIASES.get(symbol, (symbol,))
    if symbol in raw_symbols:
        return {
            "relation_type": "direct",
            "relevance_score": 1.0,
            "relation_reason": "Alpaca tagged the article with the requested ticker.",
        }
    for alias in aliases:
        if alias.lower() in text:
            return {
                "relation_type": "direct",
                "relevance_score": 0.92,
                "relation_reason": f"The article text mentions {alias}.",
            }
    if any(term in text for term in INDIRECT_TERMS):
        return {
            "relation_type": "indirect",
            "relevance_score": 0.55,
            "relation_reason": "The article includes market, sector, supplier, or regulatory terms.",
        }
    return {
        "relation_type": "indirect",
        "relevance_score": 0.35,
        "relation_reason": "The article was returned for the ticker but did not explicitly mention it.",
    }
