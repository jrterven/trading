from __future__ import annotations

import hashlib
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from ..sample_data import COMPANY_ALIASES
from ..schemas import NewsArticle
from ..time_utils import ensure_utc, utc_now


def article_mentions_symbol(symbol: str, title: str, summary: str | None = None) -> bool:
    symbol = symbol.upper()
    text = f"{title} {summary or ''}".upper()
    aliases = [symbol, *COMPANY_ALIASES.get(symbol, ())]
    return any(_contains_alias(text, alias.upper()) for alias in aliases)


def _contains_alias(text: str, alias: str) -> bool:
    pattern = rf"(?<![A-Z0-9]){re.escape(alias)}(?![A-Z0-9])"
    return re.search(pattern, text) is not None


async def fetch_rss_news(symbol: str, feed_urls: tuple[str, ...], limit: int = 30) -> list[NewsArticle]:
    articles: list[NewsArticle] = []
    if not feed_urls:
        return articles
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for feed_url in feed_urls:
            try:
                response = await client.get(feed_url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            parsed = feedparser.parse(response.text)
            for entry in parsed.entries:
                title = str(entry.get("title") or "Untitled")
                summary = _clean_summary(entry.get("summary") or entry.get("description"))
                if not article_mentions_symbol(symbol, title, summary):
                    continue
                published_at = _parse_entry_date(entry)
                url = entry.get("link")
                article_id = hashlib.sha1(f"rss:{feed_url}:{url or title}".encode()).hexdigest()
                articles.append(
                    NewsArticle(
                        id=f"rss:{article_id}",
                        source=str(parsed.feed.get("title") or feed_url),
                        symbol=symbol.upper(),
                        headline=title,
                        summary=summary,
                        url=url,
                        author=entry.get("author"),
                        published_at=published_at,
                        content=summary,
                        raw_symbols=[symbol.upper()],
                    )
                )
                if len(articles) >= limit:
                    return articles
    return articles


def _clean_summary(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).replace("\n", " ").split())


def _parse_entry_date(entry: Any) -> datetime:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if not value:
            continue
        try:
            return ensure_utc(parsedate_to_datetime(value))
        except (TypeError, ValueError):
            continue
    return utc_now()
