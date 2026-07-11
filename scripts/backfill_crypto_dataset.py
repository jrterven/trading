from __future__ import annotations

import argparse
import calendar
import hashlib
import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pandas as pd
from transformers import pipeline

PROVIDER = "alpaca"
BAR_PARAMS_VERSION = "crypto-bars:v1"
NEWS_PARAMS_VERSION = "crypto-news:v1"
SENTIMENT_MODEL = "ProsusAI/finbert"
MODEL_VERSION = "2026-07-08"
DEFAULT_DB_PATH = "data/crypto/crypto.duckdb"
DEFAULT_SYMBOLS = (
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "XRP/USD",
    "DOGE/USD",
    "ADA/USD",
    "AVAX/USD",
    "LINK/USD",
    "LTC/USD",
    "BCH/USD",
    "DOT/USD",
    "UNI/USD",
    "AAVE/USD",
    "SHIB/USD",
    "PEPE/USD",
    "BONK/USD",
    "ARB/USD",
    "FIL/USD",
    "GRT/USD",
    "CRV/USD",
)
DEFAULT_TIMEFRAMES = ("1Min", "5Min", "15Min", "1Hour", "1Day")
WINDOW_SIZES = {
    "1Min": timedelta(days=7),
    "5Min": timedelta(days=30),
    "15Min": timedelta(days=30),
    "1Hour": timedelta(days=30),
    "1Day": timedelta(days=365),
}
CRYPTO_ALIASES = {
    "BTC": ("BTC", "BTCUSD", "Bitcoin"),
    "ETH": ("ETH", "ETHUSD", "Ethereum", "Ether"),
    "SOL": ("SOL", "SOLUSD", "Solana"),
    "XRP": ("XRP", "XRPUSD", "Ripple"),
    "DOGE": ("DOGE", "DOGEUSD", "Dogecoin"),
    "ADA": ("ADA", "ADAUSD", "Cardano"),
    "AVAX": ("AVAX", "AVAXUSD", "Avalanche"),
    "LINK": ("LINK", "LINKUSD", "Chainlink"),
    "LTC": ("LTC", "LTCUSD", "Litecoin"),
    "BCH": ("BCH", "BCHUSD", "Bitcoin Cash"),
    "DOT": ("DOT", "DOTUSD", "Polkadot"),
    "UNI": ("UNI", "UNIUSD", "Uniswap"),
    "AAVE": ("AAVE", "AAVEUSD", "Aave"),
    "SHIB": ("SHIB", "SHIBUSD", "Shiba Inu"),
    "PEPE": ("PEPE", "PEPEUSD", "Pepe"),
    "BONK": ("BONK", "BONKUSD", "Bonk"),
    "ARB": ("ARB", "ARBUSD", "Arbitrum"),
    "FIL": ("FIL", "FILUSD", "Filecoin"),
    "GRT": ("GRT", "GRTUSD", "The Graph"),
    "CRV": ("CRV", "CRVUSD", "Curve"),
}

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS bars (
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        open DOUBLE NOT NULL,
        high DOUBLE NOT NULL,
        low DOUBLE NOT NULL,
        close DOUBLE NOT NULL,
        volume DOUBLE NOT NULL,
        trade_count BIGINT,
        vwap DOUBLE,
        source TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS bars_unique ON bars(symbol, timeframe, timestamp)",
    """
    CREATE TABLE IF NOT EXISTS bars_fetch_coverage (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        start_at TIMESTAMP NOT NULL,
        end_at TIMESTAMP NOT NULL,
        status TEXT NOT NULL,
        fetched_at TIMESTAMP NOT NULL,
        params_hash TEXT NOT NULL,
        bar_count BIGINT NOT NULL,
        error TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS bars_fetch_coverage_lookup
    ON bars_fetch_coverage(provider, symbol, timeframe, start_at, end_at, status)
    """,
    """
    CREATE TABLE IF NOT EXISTS news_articles (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        provider_id TEXT,
        headline TEXT NOT NULL,
        summary TEXT,
        content TEXT,
        url TEXT,
        author TEXT,
        published_at TIMESTAMP NOT NULL,
        available_at TIMESTAMP NOT NULL,
        raw_symbols TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_article_symbols (
        article_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        relevance_score DOUBLE NOT NULL,
        relation_reason TEXT,
        classifier_model TEXT NOT NULL,
        classifier_version TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS news_article_symbols_unique
    ON news_article_symbols(article_id, symbol)
    """,
    """
    CREATE TABLE IF NOT EXISTS news_fetch_coverage (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        symbol TEXT NOT NULL,
        start_at TIMESTAMP NOT NULL,
        end_at TIMESTAMP NOT NULL,
        status TEXT NOT NULL,
        fetched_at TIMESTAMP NOT NULL,
        params_hash TEXT NOT NULL,
        article_count BIGINT NOT NULL,
        error TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS news_fetch_coverage_lookup
    ON news_fetch_coverage(provider, symbol, start_at, end_at, status)
    """,
    """
    CREATE TABLE IF NOT EXISTS sentiment_scores (
        id TEXT PRIMARY KEY,
        article_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        label TEXT NOT NULL,
        score DOUBLE NOT NULL,
        positive DOUBLE NOT NULL,
        neutral DOUBLE NOT NULL,
        negative DOUBLE NOT NULL,
        model TEXT NOT NULL,
        model_version TEXT,
        prompt_version TEXT,
        explanation TEXT,
        created_at TIMESTAMP NOT NULL
    )
    """,
)


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill a separate DuckDB crypto dataset with Alpaca OHLCV, news, and FinBERT sentiment."
    )
    parser.add_argument("--db", default=os.getenv("CRYPTO_DUCKDB_PATH", DEFAULT_DB_PATH))
    parser.add_argument("--start", default=os.getenv("START_DATE", "2021-01-01"))
    parser.add_argument("--end", default=os.getenv("END_DATE", "2026-07-01"))
    parser.add_argument("--chunk-months", type=int, default=int(os.getenv("CHUNK_MONTHS", "1")))
    parser.add_argument("--symbols", nargs="*", default=split_env("CRYPTO_SYMBOLS") or list(DEFAULT_SYMBOLS))
    parser.add_argument(
        "--timeframes",
        nargs="*",
        default=split_env("CRYPTO_TIMEFRAMES") or list(DEFAULT_TIMEFRAMES),
    )
    parser.add_argument("--bar-limit", type=int, default=int(os.getenv("BAR_LIMIT", "10000")))
    parser.add_argument("--news-limit", type=int, default=int(os.getenv("NEWS_LIMIT", "50")))
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("MAX_PAGES", "500")))
    parser.add_argument("--retries", type=int, default=int(os.getenv("RETRIES", "4")))
    parser.add_argument("--sleep", type=float, default=float(os.getenv("SLEEP_SECONDS", "0.5")))
    parser.add_argument("--alpaca-data-base-url", default=os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets"))
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    return parser.parse_args()


def split_env(name: str) -> list[str] | None:
    value = os.getenv(name)
    if not value:
        return None
    return [item.strip() for item in value.replace(",", " ").split() if item.strip()]


def main() -> None:
    load_dotenv()
    args = parse_args()
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper()), format="[%(asctime)s] %(message)s")
    headers = alpaca_headers()
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        init_db(con)
        scorer = FinbertScorer()
        windows = build_month_windows(args.start, args.end, args.chunk_months)
        logging.info("crypto_backfill_start db=%s symbols=%s windows=%s timeframes=%s", db_path, args.symbols, len(windows), args.timeframes)
        for symbol in normalize_symbols(args.symbols):
            logging.info("===== SYMBOL %s windows=%s =====", symbol, len(windows))
            for index, window in enumerate(windows, start=1):
                logging.info("[%s %s/%s] window %s -> %s", symbol, index, len(windows), isoformat(window.start), isoformat(window.end))
                bar_summary = backfill_bars(con, args, headers, symbol, window)
                news_new, news_total = backfill_news(con, args, headers, symbol, window)
                scored = backfill_sentiment(con, scorer, symbol, window)
                logging.info(
                    "[%s %s/%s] bars=%s news_total=%s news_new=%s sentiment_scored=%s",
                    symbol,
                    index,
                    len(windows),
                    bar_summary,
                    news_total,
                    news_new,
                    scored,
                )
                if args.sleep > 0:
                    time.sleep(args.sleep)
        logging.info("crypto_backfill_done db=%s", db_path)
    finally:
        con.close()


def load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def alpaca_headers() -> dict[str, str]:
    key = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("ALPACA_API_KEY and ALPACA_SECRET_KEY are required.")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def init_db(con: duckdb.DuckDBPyConnection) -> None:
    for statement in SCHEMA:
        con.execute(statement)


def build_month_windows(start_text: str, end_text: str, chunk_months: int) -> list[Window]:
    start_date = date.fromisoformat(start_text)
    end_exclusive = date.fromisoformat(end_text) + timedelta(days=1)
    current = start_date
    windows: list[Window] = []
    while current < end_exclusive:
        next_date = min(add_months(current, chunk_months), end_exclusive)
        windows.append(Window(as_utc(current), as_utc(next_date)))
        current = next_date
    return windows


def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def as_utc(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def normalize_symbols(symbols: list[str]) -> list[str]:
    return [symbol.strip().upper() for symbol in symbols if symbol.strip()]


def backfill_bars(
    con: duckdb.DuckDBPyConnection,
    args: argparse.Namespace,
    headers: dict[str, str],
    symbol: str,
    parent_window: Window,
) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for timeframe in args.timeframes:
        fetched = 0
        new = 0
        failed = 0
        for window in split_timeframe_windows(timeframe, parent_window):
            if coverage_exists(con, "bars_fetch_coverage", symbol, window, timeframe):
                continue
            try:
                bars = fetch_crypto_bars(args, headers, symbol, timeframe, window)
                fetched += len(bars)
                new += save_bars(con, symbol, timeframe, bars, window)
                save_bar_coverage(con, symbol, timeframe, window, "completed", len(bars))
            except Exception as exc:
                failed += 1
                save_bar_coverage(con, symbol, timeframe, window, "failed", 0, str(exc))
                logging.warning("bar_window_failed symbol=%s timeframe=%s start=%s end=%s error=%s", symbol, timeframe, isoformat(window.start), isoformat(window.end), exc)
        total = count_bars(con, symbol, timeframe, parent_window)
        summary[timeframe] = {"total": total, "fetched": fetched, "new": new, "failed": failed}
    return summary


def split_timeframe_windows(timeframe: str, parent: Window) -> list[Window]:
    step = WINDOW_SIZES.get(timeframe, timedelta(days=30))
    windows: list[Window] = []
    current = parent.start
    while current < parent.end:
        window_end = min(current + step, parent.end)
        windows.append(Window(current, window_end))
        current = window_end
    return windows


def fetch_crypto_bars(
    args: argparse.Namespace,
    headers: dict[str, str],
    symbol: str,
    timeframe: str,
    window: Window,
) -> list[dict[str, Any]]:
    url = f"{args.alpaca_data_base_url}/v1beta3/crypto/us/bars"
    params: dict[str, str] = {
        "symbols": symbol,
        "timeframe": timeframe,
        "start": isoformat(window.start),
        "end": isoformat(window.end),
        "limit": str(args.bar_limit),
    }
    bars: list[dict[str, Any]] = []
    for payload in paginated_get(args, headers, url, params):
        bars.extend(payload.get("bars", {}).get(symbol, []))
    return bars


def save_bars(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
    bars: list[dict[str, Any]],
    window: Window,
) -> int:
    rows: list[list[Any]] = []
    for bar in bars:
        timestamp = parse_timestamp(bar["t"])
        if timestamp < window.start or timestamp >= window.end:
            continue
        rows.append(
            [
                symbol,
                timeframe,
                naive_utc(timestamp),
                float(bar["o"]),
                float(bar["h"]),
                float(bar["l"]),
                float(bar["c"]),
                float(bar.get("v", 0.0)),
                int(bar["n"]) if bar.get("n") is not None else None,
                float(bar["vw"]) if bar.get("vw") is not None else None,
                PROVIDER,
            ]
        )
    if not rows:
        return 0

    before = count_bars(con, symbol, timeframe, window)
    frame = pd.DataFrame(
        rows,
        columns=[
            "symbol",
            "timeframe",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "trade_count",
            "vwap",
            "source",
        ],
    )
    con.register("incoming_bars", frame)
    try:
        con.execute(
            """
            INSERT INTO bars
            (symbol, timeframe, timestamp, open, high, low, close, volume, trade_count, vwap, source, created_at)
            SELECT symbol, timeframe, timestamp, open, high, low, close, volume,
                   trade_count, vwap, source, current_timestamp
            FROM incoming_bars
            ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                trade_count = excluded.trade_count,
                vwap = excluded.vwap,
                source = excluded.source
            """
        )
    finally:
        con.unregister("incoming_bars")
    after = count_bars(con, symbol, timeframe, window)
    return max(after - before, 0)


def backfill_news(
    con: duckdb.DuckDBPyConnection,
    args: argparse.Namespace,
    headers: dict[str, str],
    symbol: str,
    window: Window,
) -> tuple[int, int]:
    if coverage_exists(con, "news_fetch_coverage", symbol, window):
        return 0, count_news(con, symbol, window)
    try:
        articles = fetch_news(args, headers, symbol, window)
        new = save_news(con, symbol, articles, window)
        save_news_coverage(con, symbol, window, "completed", len(articles))
        return new, count_news(con, symbol, window)
    except Exception as exc:
        save_news_coverage(con, symbol, window, "failed", 0, str(exc))
        logging.warning("news_window_failed symbol=%s start=%s end=%s error=%s", symbol, isoformat(window.start), isoformat(window.end), exc)
        return 0, count_news(con, symbol, window)


def fetch_news(
    args: argparse.Namespace,
    headers: dict[str, str],
    symbol: str,
    window: Window,
) -> list[dict[str, Any]]:
    url = f"{args.alpaca_data_base_url}/v1beta1/news"
    params = {
        "symbols": symbol,
        "limit": str(min(max(args.news_limit, 1), 50)),
        "include_content": "true",
        "sort": "desc",
        "start": isoformat(window.start),
        "end": isoformat(window.end),
    }
    articles: list[dict[str, Any]] = []
    for payload in paginated_get(args, headers, url, params):
        articles.extend(payload.get("news", []))
    return articles


def save_news(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    articles: list[dict[str, Any]],
    window: Window,
) -> int:
    new_relations = 0
    for raw in articles:
        article_id = article_id_from_raw(raw)
        raw_symbols = [str(item).upper() for item in raw.get("symbols", [])]
        published_at = parse_timestamp(raw.get("created_at") or raw.get("updated_at"))
        if published_at < window.start or published_at >= window.end:
            continue
        relation = classify_relation(symbol, raw, raw_symbols)
        relation_exists = con.execute(
            """
            SELECT 1 FROM news_article_symbols
            WHERE article_id = ? AND symbol = ?
            LIMIT 1
            """,
            [article_id, symbol],
        ).fetchone() is not None
        con.execute(
            """
            INSERT INTO news_articles
            (id, source, provider_id, headline, summary, content, url, author,
             published_at, available_at, raw_symbols, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
            ON CONFLICT (id) DO UPDATE SET
                source = excluded.source,
                provider_id = excluded.provider_id,
                headline = excluded.headline,
                summary = excluded.summary,
                content = excluded.content,
                url = excluded.url,
                author = excluded.author,
                published_at = excluded.published_at,
                available_at = excluded.available_at,
                raw_symbols = excluded.raw_symbols
            """,
            [
                article_id,
                str(raw.get("source") or PROVIDER),
                str(raw.get("id") or ""),
                str(raw.get("headline") or "Untitled"),
                raw.get("summary"),
                raw.get("content"),
                raw.get("url"),
                raw.get("author"),
                naive_utc(published_at),
                naive_utc(published_at),
                json.dumps(raw_symbols),
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
                article_id,
                symbol,
                relation["relation_type"],
                relation["relevance_score"],
                relation["relation_reason"],
                "rules-crypto-relevance",
                MODEL_VERSION,
            ],
        )
        if not relation_exists:
            new_relations += 1
    return new_relations


def classify_relation(symbol: str, raw: dict[str, Any], raw_symbols: list[str]) -> dict[str, str | float]:
    base = symbol.split("/", 1)[0]
    slashless = symbol.replace("/", "")
    raw_set = {item.upper() for item in raw_symbols}
    if slashless in raw_set or symbol in raw_set or base in raw_set:
        return {
            "relation_type": "direct",
            "relevance_score": 1.0,
            "relation_reason": "Alpaca tagged the article with the requested crypto symbol.",
        }
    text = clean_text(" ".join(str(raw.get(key) or "") for key in ("headline", "summary", "content"))).lower()
    for alias in CRYPTO_ALIASES.get(base, (base, slashless)):
        if alias.lower() in text:
            return {
                "relation_type": "direct",
                "relevance_score": 0.92,
                "relation_reason": f"The article text mentions {alias}.",
            }
    return {
        "relation_type": "indirect",
        "relevance_score": 0.45,
        "relation_reason": "The article was returned for the crypto pair but did not explicitly mention it.",
    }


def backfill_sentiment(
    con: duckdb.DuckDBPyConnection,
    scorer: "FinbertScorer",
    symbol: str,
    window: Window,
) -> int:
    rows = con.execute(
        """
        SELECT na.id, na.headline, na.summary, na.content
        FROM news_articles na
        JOIN news_article_symbols nas ON nas.article_id = na.id
        LEFT JOIN sentiment_scores ss
          ON ss.article_id = na.id
         AND ss.symbol = nas.symbol
         AND ss.model = ?
        WHERE nas.symbol = ?
          AND na.published_at >= ?
          AND na.published_at < ?
          AND ss.article_id IS NULL
        ORDER BY na.published_at DESC
        """,
        [SENTIMENT_MODEL, symbol, naive_utc(window.start), naive_utc(window.end)],
    ).fetchall()
    scored = 0
    for article_id, headline, summary, content in rows:
        text = clean_text(" ".join(part for part in [headline, summary, content] if part))[:1800]
        probabilities = scorer.score(text)
        label = max(probabilities, key=probabilities.get)
        score_id = hashlib.sha1(f"{article_id}:{symbol}:{SENTIMENT_MODEL}:{MODEL_VERSION}".encode()).hexdigest()
        con.execute(
            """
            INSERT INTO sentiment_scores
            (id, article_id, symbol, label, score, positive, neutral, negative,
             model, model_version, prompt_version, explanation, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
            ON CONFLICT (id) DO UPDATE SET
                label = excluded.label,
                score = excluded.score,
                positive = excluded.positive,
                neutral = excluded.neutral,
                negative = excluded.negative,
                model = excluded.model,
                model_version = excluded.model_version,
                prompt_version = excluded.prompt_version,
                explanation = excluded.explanation,
                created_at = excluded.created_at
            """,
            [
                score_id,
                article_id,
                symbol,
                label,
                float(probabilities[label]),
                float(probabilities["positive"]),
                float(probabilities["neutral"]),
                float(probabilities["negative"]),
                SENTIMENT_MODEL,
                MODEL_VERSION,
                None,
                None,
            ],
        )
        scored += 1
    return scored


class FinbertScorer:
    def __init__(self) -> None:
        self.classifier = pipeline("text-classification", model=SENTIMENT_MODEL)

    def score(self, text: str) -> dict[str, float]:
        results = self.classifier(text or "No text.", truncation=True, top_k=None)
        if results and isinstance(results[0], list):
            results = results[0]
        probabilities = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
        for item in results:
            label = str(item["label"]).lower()
            if label in probabilities:
                probabilities[label] = float(item["score"])
        total = sum(probabilities.values()) or 1.0
        return {key: value / total for key, value in probabilities.items()}


def paginated_get(
    args: argparse.Namespace,
    headers: dict[str, str],
    url: str,
    params: dict[str, str],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    page_token: str | None = None
    with httpx.Client(timeout=60) as client:
        for page in range(args.max_pages):
            page_params = dict(params)
            if page_token:
                page_params["page_token"] = page_token
            payload = request_json(client, args, headers, url, page_params)
            payloads.append(payload)
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        else:
            raise RuntimeError(f"Reached max_pages={args.max_pages} for {url} params={params}")
    return payloads


def request_json(
    client: httpx.Client,
    args: argparse.Namespace,
    headers: dict[str, str],
    url: str,
    params: dict[str, str],
) -> dict[str, Any]:
    sleep_for = 2.0
    last_error = ""
    for attempt in range(1, args.retries + 1):
        response = client.get(url, headers=headers, params=params)
        if response.status_code < 400:
            return response.json()
        last_error = f"{response.status_code}: {response.text[:300]}"
        logging.warning("request_failed attempt=%s/%s url=%s error=%s", attempt, args.retries, url, last_error)
        time.sleep(sleep_for)
        sleep_for *= 2
    raise RuntimeError(f"Alpaca request failed: {last_error}")


def coverage_exists(
    con: duckdb.DuckDBPyConnection,
    table: str,
    symbol: str,
    window: Window,
    timeframe: str | None = None,
) -> bool:
    params_hash = bar_params_hash(timeframe) if timeframe else news_params_hash()
    if timeframe:
        row = con.execute(
            f"""
            SELECT 1 FROM {table}
            WHERE provider = ? AND symbol = ? AND timeframe = ? AND status = 'completed'
              AND params_hash = ? AND start_at <= ? AND end_at >= ?
            LIMIT 1
            """,
            [PROVIDER, symbol, timeframe, params_hash, naive_utc(window.start), naive_utc(window.end)],
        ).fetchone()
    else:
        row = con.execute(
            f"""
            SELECT 1 FROM {table}
            WHERE provider = ? AND symbol = ? AND status = 'completed'
              AND params_hash = ? AND start_at <= ? AND end_at >= ?
            LIMIT 1
            """,
            [PROVIDER, symbol, params_hash, naive_utc(window.start), naive_utc(window.end)],
        ).fetchone()
    return row is not None


def save_bar_coverage(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
    window: Window,
    status: str,
    count: int,
    error: str | None = None,
) -> None:
    params_hash = bar_params_hash(timeframe)
    coverage_id = hashlib.sha1(
        f"{PROVIDER}:{symbol}:{timeframe}:{window.start.isoformat()}:{window.end.isoformat()}:{params_hash}".encode()
    ).hexdigest()
    con.execute(
        """
        INSERT INTO bars_fetch_coverage
        (id, provider, symbol, timeframe, start_at, end_at, status, fetched_at, params_hash, bar_count, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            status = excluded.status,
            fetched_at = excluded.fetched_at,
            bar_count = excluded.bar_count,
            error = excluded.error
        """,
        [coverage_id, PROVIDER, symbol, timeframe, naive_utc(window.start), naive_utc(window.end), status, params_hash, count, error],
    )


def save_news_coverage(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    window: Window,
    status: str,
    count: int,
    error: str | None = None,
) -> None:
    params_hash = news_params_hash()
    coverage_id = hashlib.sha1(
        f"{PROVIDER}:{symbol}:{window.start.isoformat()}:{window.end.isoformat()}:{params_hash}".encode()
    ).hexdigest()
    con.execute(
        """
        INSERT INTO news_fetch_coverage
        (id, provider, symbol, start_at, end_at, status, fetched_at, params_hash, article_count, error)
        VALUES (?, ?, ?, ?, ?, ?, current_timestamp, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            status = excluded.status,
            fetched_at = excluded.fetched_at,
            article_count = excluded.article_count,
            error = excluded.error
        """,
        [coverage_id, PROVIDER, symbol, naive_utc(window.start), naive_utc(window.end), status, params_hash, count, error],
    )


def count_bars(con: duckdb.DuckDBPyConnection, symbol: str, timeframe: str, window: Window) -> int:
    row = con.execute(
        """
        SELECT COUNT(*) FROM bars
        WHERE symbol = ? AND timeframe = ? AND timestamp >= ? AND timestamp < ?
        """,
        [symbol, timeframe, naive_utc(window.start), naive_utc(window.end)],
    ).fetchone()
    return int(row[0]) if row else 0


def count_news(con: duckdb.DuckDBPyConnection, symbol: str, window: Window) -> int:
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM news_articles na
        JOIN news_article_symbols nas ON nas.article_id = na.id
        WHERE nas.symbol = ? AND na.published_at >= ? AND na.published_at < ?
        """,
        [symbol, naive_utc(window.start), naive_utc(window.end)],
    ).fetchone()
    return int(row[0]) if row else 0


def article_id_from_raw(raw: dict[str, Any]) -> str:
    raw_id = raw.get("id")
    if raw_id:
        return f"alpaca:{raw_id}"
    return "alpaca:" + hashlib.sha1(str(raw).encode()).hexdigest()


def bar_params_hash(timeframe: str | None) -> str:
    return hashlib.sha1(f"{BAR_PARAMS_VERSION}:provider={PROVIDER}:timeframe={timeframe}".encode()).hexdigest()


def news_params_hash() -> str:
    return hashlib.sha1(f"{NEWS_PARAMS_VERSION}:provider={PROVIDER}:include_content=true".encode()).hexdigest()


def parse_timestamp(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def clean_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


if __name__ == "__main__":
    main()
