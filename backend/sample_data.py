from __future__ import annotations

import hashlib
import math
import random
from datetime import UTC, datetime, timedelta

from .schemas import Bar, NewsArticle, SymbolResult
from .time_utils import ensure_utc, isoformat_utc, utc_now

COMMON_SYMBOLS = [
    SymbolResult(symbol="AAPL", name="Apple Inc.", exchange="NASDAQ"),
    SymbolResult(symbol="MSFT", name="Microsoft Corporation", exchange="NASDAQ"),
    SymbolResult(symbol="NVDA", name="NVIDIA Corporation", exchange="NASDAQ"),
    SymbolResult(symbol="TSLA", name="Tesla, Inc.", exchange="NASDAQ"),
    SymbolResult(symbol="AMZN", name="Amazon.com, Inc.", exchange="NASDAQ"),
    SymbolResult(symbol="META", name="Meta Platforms, Inc.", exchange="NASDAQ"),
    SymbolResult(symbol="GOOGL", name="Alphabet Inc.", exchange="NASDAQ"),
    SymbolResult(symbol="JPM", name="JPMorgan Chase & Co.", exchange="NYSE"),
    SymbolResult(symbol="SPY", name="SPDR S&P 500 ETF Trust", exchange="NYSEARCA"),
    SymbolResult(symbol="QQQ", name="Invesco QQQ Trust", exchange="NASDAQ"),
]

COMPANY_ALIASES = {
    "AAPL": ("Apple", "iPhone", "Mac"),
    "MSFT": ("Microsoft", "Azure", "Windows"),
    "NVDA": ("Nvidia", "GPU", "AI chips"),
    "TSLA": ("Tesla", "EV", "Model Y"),
    "AMZN": ("Amazon", "AWS", "Prime"),
    "META": ("Meta", "Facebook", "Instagram"),
    "GOOGL": ("Alphabet", "Google", "YouTube"),
    "JPM": ("JPMorgan", "Chase", "bank"),
    "SPY": ("S&P 500", "ETF", "broad market"),
    "QQQ": ("Nasdaq 100", "ETF", "technology index"),
}

BASE_PRICE = {
    "AAPL": 210,
    "MSFT": 455,
    "NVDA": 125,
    "TSLA": 260,
    "AMZN": 190,
    "META": 530,
    "GOOGL": 175,
    "JPM": 210,
    "SPY": 550,
    "QQQ": 480,
}

TIMEFRAME_STEPS = {
    "1Min": timedelta(minutes=1),
    "5Min": timedelta(minutes=5),
    "15Min": timedelta(minutes=15),
    "1Hour": timedelta(hours=1),
    "1Day": timedelta(days=1),
}


def search_symbols(query: str | None = None) -> list[SymbolResult]:
    if not query:
        return COMMON_SYMBOLS
    needle = query.upper().strip()
    return [
        symbol
        for symbol in COMMON_SYMBOLS
        if needle in symbol.symbol or needle in symbol.name.upper()
    ][:20]


def generate_bars(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    max_points: int = 1200,
) -> list[Bar]:
    symbol = symbol.upper()
    step = TIMEFRAME_STEPS.get(timeframe, timedelta(days=1))
    start = ensure_utc(start)
    end = ensure_utc(end)
    seed = int(hashlib.sha256(f"{symbol}:{timeframe}".encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    base = BASE_PRICE.get(symbol, 100 + seed % 300)

    stamps: list[datetime] = []
    current = start
    while current <= end and len(stamps) < max_points:
        if timeframe == "1Day":
            if current.weekday() < 5:
                stamps.append(current.replace(hour=21, minute=0, second=0, microsecond=0))
        else:
            stamps.append(current)
        current += step

    if not stamps:
        stamps = [end]

    bars: list[Bar] = []
    price = base
    for index, timestamp in enumerate(stamps):
        drift = math.sin(index / 18.0) * 0.006 + math.cos(index / 53.0) * 0.003
        shock = rng.gauss(0, 0.012 if timeframe == "1Day" else 0.003)
        open_price = price
        close_price = max(1.0, open_price * (1 + drift + shock))
        high_price = max(open_price, close_price) * (1 + abs(rng.gauss(0.004, 0.002)))
        low_price = min(open_price, close_price) * (1 - abs(rng.gauss(0.004, 0.002)))
        volume = int(abs(rng.gauss(1_800_000, 550_000)))
        if timeframe != "1Day":
            volume = max(10_000, volume // 120)
        bars.append(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                open=round(open_price, 2),
                high=round(high_price, 2),
                low=round(low_price, 2),
                close=round(close_price, 2),
                volume=volume,
                source="sample",
            )
        )
        price = close_price
    return bars


def generate_news(symbol: str, limit: int = 12) -> list[NewsArticle]:
    symbol = symbol.upper()
    aliases = COMPANY_ALIASES.get(symbol, (symbol,))
    company = aliases[0]
    now = utc_now()
    templates = [
        (
            "{company} reports revenue growth and raises expectations",
            "The company highlighted resilient demand and improving operating margins.",
        ),
        (
            "Analysts revise {company} price target ahead of earnings",
            "The market is watching cash flow, guidance, and competitive pressure.",
        ),
        (
            "{company} faces cost pressure and regulatory changes",
            "Investors are assessing the potential impact on future earnings.",
        ),
        (
            "{company} announces new strategic partnership",
            "The news could open expansion opportunities in new segments.",
        ),
        (
            "Unusual volume in {symbol} during the session",
            "Traders attribute the move to recent news and rebalancing.",
        ),
    ]
    articles: list[NewsArticle] = []
    for index in range(limit):
        title_template, summary = templates[index % len(templates)]
        published = now - timedelta(hours=6 * index + index)
        headline = title_template.format(company=company, symbol=symbol)
        article_id = hashlib.sha1(f"sample:{symbol}:{index}:{isoformat_utc(published)}".encode()).hexdigest()
        articles.append(
            NewsArticle(
                id=article_id,
                source="sample",
                symbol=symbol,
                headline=headline,
                summary=summary,
                url=None,
                author="Trading Lab",
                published_at=published,
                content=f"{headline}. {summary}",
                raw_symbols=[symbol],
            )
        )
    return articles


def default_date_window(days: int = 180) -> tuple[datetime, datetime]:
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=days)
    return start, end
