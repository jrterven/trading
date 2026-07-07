from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..schemas import Bar, NewsArticle, SymbolResult
from ..time_utils import ensure_utc, isoformat_utc


class ProviderError(RuntimeError):
    pass


class AlpacaProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def headers(self) -> dict[str, str]:
        if not self.settings.has_alpaca_credentials:
            return {}
        return {
            "APCA-API-KEY-ID": self.settings.alpaca_api_key or "",
            "APCA-API-SECRET-KEY": self.settings.alpaca_secret_key or "",
        }

    async def search_symbols(self, query: str | None = None) -> list[SymbolResult]:
        if not self.settings.has_alpaca_credentials:
            return []
        url = f"{self.settings.alpaca_trading_base_url}/v2/assets"
        params = {"status": "active", "asset_class": "us_equity"}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=self.headers, params=params)
        if response.status_code >= 400:
            raise ProviderError(f"Alpaca assets error {response.status_code}: {response.text[:200]}")
        needle = (query or "").upper().strip()
        symbols: list[SymbolResult] = []
        for item in response.json():
            symbol = str(item.get("symbol", "")).upper()
            name = str(item.get("name") or symbol)
            if needle and needle not in symbol and needle not in name.upper():
                continue
            symbols.append(
                SymbolResult(
                    symbol=symbol,
                    name=name,
                    exchange=item.get("exchange"),
                    tradable=bool(item.get("tradable", True)),
                )
            )
            if len(symbols) >= 25:
                break
        return symbols

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        limit: int = 10000,
    ) -> list[Bar]:
        if not self.settings.has_alpaca_credentials:
            return []

        url = f"{self.settings.alpaca_data_base_url}/v2/stocks/bars"
        params = {
            "symbols": symbol.upper(),
            "timeframe": timeframe,
            "start": isoformat_utc(start),
            "end": isoformat_utc(end),
            "adjustment": "raw",
            "feed": self.settings.alpaca_data_feed,
            "limit": str(limit),
        }
        bars: list[Bar] = []
        page_token: str | None = None
        async with httpx.AsyncClient(timeout=30) as client:
            for _ in range(100):
                page_params = dict(params)
                if page_token:
                    page_params["page_token"] = page_token
                response = await client.get(url, headers=self.headers, params=page_params)
                if response.status_code >= 400:
                    raise ProviderError(f"Alpaca bars error {response.status_code}: {response.text[:240]}")
                payload = response.json()
                raw_bars = payload.get("bars", {}).get(symbol.upper(), [])
                bars.extend(self._bar_from_alpaca(symbol.upper(), timeframe, raw) for raw in raw_bars)
                page_token = payload.get("next_page_token")
                if not page_token:
                    break
        return bars

    async def fetch_news(
        self,
        symbol: str,
        start: datetime | None,
        end: datetime | None,
        limit: int = 50,
    ) -> list[NewsArticle]:
        if not self.settings.has_alpaca_credentials:
            return []

        url = f"{self.settings.alpaca_data_base_url}/v1beta1/news"
        params: dict[str, Any] = self._news_params(symbol, limit)
        if start:
            params["start"] = isoformat_utc(start)
        if end:
            params["end"] = isoformat_utc(end)
        articles: list[NewsArticle] = []
        page_token: str | None = None
        async with httpx.AsyncClient(timeout=30) as client:
            for _ in range(20):
                page_params = dict(params)
                if page_token:
                    page_params["page_token"] = page_token
                response = await client.get(url, headers=self.headers, params=page_params)
                if response.status_code >= 400:
                    raise ProviderError(f"Alpaca news error {response.status_code}: {response.text[:240]}")
                payload = response.json()
                articles.extend(
                    self._news_from_alpaca(symbol.upper(), item) for item in payload.get("news", [])
                )
                page_token = payload.get("next_page_token")
                if not page_token:
                    break
        return articles

    @staticmethod
    def _news_params(symbol: str, limit: int) -> dict[str, Any]:
        return {
            "symbols": symbol.upper(),
            "limit": min(max(limit, 1), 50),
            "include_content": "true",
            "sort": "desc",
        }

    async def get_account(self) -> dict[str, Any]:
        if not self.settings.has_alpaca_credentials:
            raise ProviderError("Alpaca no esta configurado.")

        url = f"{self.settings.alpaca_trading_base_url}/v2/account"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=self.headers)
        if response.status_code >= 400:
            raise ProviderError(f"Alpaca account error {response.status_code}: {response.text[:240]}")
        return response.json()

    async def get_positions(self) -> list[dict[str, Any]]:
        if not self.settings.has_alpaca_credentials:
            raise ProviderError("Alpaca no esta configurado.")

        url = f"{self.settings.alpaca_trading_base_url}/v2/positions"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=self.headers)
        if response.status_code >= 400:
            raise ProviderError(f"Alpaca positions error {response.status_code}: {response.text[:240]}")
        return response.json()

    async def place_order(self, symbol: str, side: str, quantity: float) -> dict[str, Any]:
        if not self.settings.has_alpaca_credentials:
            raise ProviderError("Alpaca no esta configurado.")

        url = f"{self.settings.alpaca_trading_base_url}/v2/orders"
        payload = {
            "symbol": symbol.upper(),
            "qty": f"{quantity:g}",
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, headers=self.headers, json=payload)
        if response.status_code >= 400:
            raise ProviderError(f"Alpaca order error {response.status_code}: {response.text[:240]}")
        return response.json()

    @staticmethod
    def _bar_from_alpaca(symbol: str, timeframe: str, raw: dict[str, Any]) -> Bar:
        timestamp = datetime.fromisoformat(str(raw["t"]).replace("Z", "+00:00"))
        return Bar(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=ensure_utc(timestamp),
            open=float(raw["o"]),
            high=float(raw["h"]),
            low=float(raw["l"]),
            close=float(raw["c"]),
            volume=int(raw.get("v", 0)),
            source="alpaca",
        )

    @staticmethod
    def _news_from_alpaca(symbol: str, raw: dict[str, Any]) -> NewsArticle:
        url = raw.get("url")
        article_id = str(raw.get("id") or hashlib.sha1(str(url or raw).encode()).hexdigest())
        published_raw = raw.get("created_at") or raw.get("updated_at")
        published_at = datetime.fromisoformat(str(published_raw).replace("Z", "+00:00"))
        symbols = [str(item).upper() for item in raw.get("symbols", [])]
        return NewsArticle(
            id=f"alpaca:{article_id}",
            source="alpaca",
            symbol=symbol,
            headline=str(raw.get("headline") or "Untitled"),
            summary=raw.get("summary"),
            url=url,
            author=raw.get("author"),
            published_at=ensure_utc(published_at),
            available_at=ensure_utc(published_at),
            content=raw.get("content"),
            raw_symbols=symbols or [symbol],
        )
