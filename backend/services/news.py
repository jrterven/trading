from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..config import Settings, get_settings
from ..db import as_utc_naive, connection, rows_to_dicts
from ..providers.alpaca import AlpacaProvider, ProviderError
from ..schemas import NewsArticle
from ..time_utils import ensure_utc, utc_now


class NewsService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.alpaca = AlpacaProvider(self.settings)

    async def fetch_and_store(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        include_rss: bool = True,
        limit: int = 30,
    ) -> list[NewsArticle]:
        symbol = symbol.upper()
        start = ensure_utc(start) if start else utc_now() - timedelta(days=14)
        end = ensure_utc(end) if end else utc_now()
        articles: list[NewsArticle] = []

        try:
            articles.extend(await self.alpaca.fetch_news(symbol, start, end, limit=limit))
        except ProviderError:
            articles = []

        unique = {article.id: article for article in articles}
        self.save_articles(list(unique.values()))
        return self.get_articles(symbol, start=start, end=end, limit=limit)

    def get_articles(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
    ) -> list[NewsArticle]:
        symbol = symbol.upper()
        start = ensure_utc(start) if start else datetime(1970, 1, 1)
        end = ensure_utc(end) if end else utc_now() + timedelta(days=1)
        with connection(self.settings) as con:
            rows = rows_to_dicts(
                con.execute(
                    """
                    SELECT id, source, symbol, headline, summary, url, author,
                           published_at, content, raw_symbols
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

    def save_articles(self, articles: list[NewsArticle]) -> None:
        if not articles:
            return
        with connection(self.settings) as con:
            for article in articles:
                con.execute("DELETE FROM news_articles WHERE id = ?", [article.id])
            con.executemany(
                """
                INSERT INTO news_articles
                (id, source, symbol, headline, summary, url, author, published_at,
                 content, raw_symbols, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
                """,
                [
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
                    ]
                    for article in articles
                ],
            )
