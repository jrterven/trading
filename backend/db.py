from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from .config import Settings, get_settings


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
        volume BIGINT NOT NULL,
        source TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS bars_unique ON bars(symbol, timeframe, timestamp)",
    """
    CREATE TABLE IF NOT EXISTS news_articles (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        symbol TEXT NOT NULL,
        headline TEXT NOT NULL,
        summary TEXT,
        url TEXT,
        author TEXT,
        published_at TIMESTAMP NOT NULL,
        content TEXT,
        raw_symbols TEXT,
        created_at TIMESTAMP NOT NULL
    )
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
        explanation TEXT,
        created_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS strategies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        code TEXT NOT NULL,
        file_path TEXT,
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_runs (
        id TEXT PRIMARY KEY,
        strategy_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        start_at TIMESTAMP NOT NULL,
        end_at TIMESTAMP NOT NULL,
        status TEXT NOT NULL,
        initial_cash DOUBLE NOT NULL,
        commission_pct DOUBLE NOT NULL,
        metrics_json TEXT,
        equity_curve_json TEXT,
        error TEXT,
        created_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        entry_time TIMESTAMP NOT NULL,
        exit_time TIMESTAMP,
        entry_price DOUBLE NOT NULL,
        exit_price DOUBLE,
        quantity DOUBLE NOT NULL,
        pnl DOUBLE NOT NULL,
        return_pct DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS markers (
        id TEXT PRIMARY KEY,
        run_id TEXT,
        symbol TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        marker_type TEXT NOT NULL,
        label TEXT NOT NULL,
        color TEXT NOT NULL,
        price DOUBLE,
        source TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS paper_orders (
        id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity DOUBLE NOT NULL,
        price DOUBLE NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
)


def init_db(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    Path(settings.duckdb_path).parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(settings.duckdb_path)) as con:
        for statement in SCHEMA:
            con.execute(statement)
        _ensure_column(con, "strategies", "file_path", "TEXT")


def _ensure_column(con: duckdb.DuckDBPyConnection, table: str, column: str, column_type: str) -> None:
    columns = {row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()}
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


@contextmanager
def connection(settings: Settings | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    settings = settings or get_settings()
    init_db(settings)
    con = duckdb.connect(str(settings.duckdb_path))
    try:
        yield con
    finally:
        con.close()


def rows_to_dicts(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [description[0] for description in cursor.description or []]
    rows = cursor.fetchall()
    return [dict(zip(columns, row, strict=False)) for row in rows]


def as_utc_naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)
