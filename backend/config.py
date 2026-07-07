from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is optional outside uvicorn[standard]
    load_dotenv = None


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    duckdb_path: Path
    alpaca_api_key: str | None
    alpaca_secret_key: str | None
    alpaca_data_feed: str
    alpaca_data_base_url: str
    alpaca_trading_base_url: str
    rss_feeds: tuple[str, ...]
    ollama_base_url: str
    ollama_model: str
    strategy_timeout_seconds: int
    allowed_origins: tuple[str, ...]

    @property
    def has_alpaca_credentials(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    root_dir = Path(__file__).resolve().parents[1]
    if load_dotenv is not None:
        load_dotenv(root_dir / ".env")
    data_dir = root_dir / "data"
    duckdb_path = Path(os.getenv("DUCKDB_PATH", data_dir / "trading.duckdb"))
    if not duckdb_path.is_absolute():
        duckdb_path = root_dir / duckdb_path

    return Settings(
        root_dir=root_dir,
        data_dir=data_dir,
        duckdb_path=duckdb_path,
        alpaca_api_key=os.getenv("ALPACA_API_KEY") or None,
        alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY") or None,
        alpaca_data_feed=os.getenv("ALPACA_DATA_FEED", "iex"),
        alpaca_data_base_url=os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets"),
        alpaca_trading_base_url=os.getenv(
            "ALPACA_TRADING_BASE_URL", "https://paper-api.alpaca.markets"
        ),
        rss_feeds=_split_csv(
            os.getenv(
                "RSS_FEEDS",
                "https://finance.yahoo.com/news/rssindex,"
                "https://feeds.marketwatch.com/marketwatch/topstories/",
            )
        ),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "gpt-oss:20b"),
        strategy_timeout_seconds=int(os.getenv("STRATEGY_TIMEOUT_SECONDS", "8")),
        allowed_origins=_split_csv(
            os.getenv(
                "ALLOWED_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,"
                "http://localhost:5174,http://127.0.0.1:5174,"
                "http://localhost:5175,http://127.0.0.1:5175",
            )
        ),
    )
