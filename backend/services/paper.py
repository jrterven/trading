from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from ..config import Settings, get_settings
from ..providers.alpaca import AlpacaProvider, ProviderError
from ..schemas import PaperOrder, PaperOrderRequest
from ..time_utils import ensure_utc, utc_now


class PaperService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.alpaca = AlpacaProvider(self.settings)

    async def place_order(self, request: PaperOrderRequest) -> PaperOrder:
        try:
            raw_order = await self.alpaca.place_order(
                request.symbol,
                request.side,
                request.quantity,
            )
        except ProviderError as exc:
            raise ValueError(str(exc)) from exc
        return self._order_from_alpaca(raw_order)

    async def portfolio(self) -> dict[str, Any]:
        try:
            account, raw_positions = await asyncio.gather(
                self.alpaca.get_account(),
                self.alpaca.get_positions(),
            )
        except ProviderError as exc:
            raise ValueError(str(exc)) from exc

        positions = [self._position_from_alpaca(position) for position in raw_positions]
        positions.sort(key=lambda item: item["symbol"])
        equity = self._float(account.get("portfolio_value") or account.get("equity"))

        return {
            "positions": positions,
            "orders": [],
            "market_value": round(equity, 2),
            "equity": round(equity, 2),
            "cash": round(self._float(account.get("cash")), 2),
            "buying_power": round(self._float(account.get("buying_power")), 2),
            "currency": account.get("currency", "USD"),
            "trading_blocked": bool(account.get("trading_blocked", False)),
        }

    @classmethod
    def _order_from_alpaca(cls, raw: dict[str, Any]) -> PaperOrder:
        created_at = cls._datetime(
            raw.get("created_at")
            or raw.get("submitted_at")
            or raw.get("updated_at")
            or raw.get("filled_at")
        )
        return PaperOrder(
            id=str(raw.get("id") or ""),
            symbol=str(raw.get("symbol") or "").upper(),
            side=raw.get("side"),
            quantity=cls._float(raw.get("qty")),
            price=cls._float(raw.get("filled_avg_price") or raw.get("limit_price")),
            status=str(raw.get("status") or "unknown"),
            created_at=created_at,
        )

    @classmethod
    def _position_from_alpaca(cls, raw: dict[str, Any]) -> dict[str, Any]:
        quantity = cls._float(raw.get("qty"))
        avg_cost = cls._float(raw.get("avg_entry_price"))
        last_price = cls._float(raw.get("current_price"))
        market_value = cls._float(raw.get("market_value"))
        unrealized_pnl = cls._float(raw.get("unrealized_pl"))
        return {
            "symbol": str(raw.get("symbol") or "").upper(),
            "quantity": round(quantity, 6),
            "avg_cost": round(avg_cost, 2),
            "last_price": round(last_price, 2),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
        }

    @staticmethod
    def _float(value: Any) -> float:
        if value in (None, ""):
            return 0.0
        return float(value)

    @staticmethod
    def _datetime(value: Any) -> datetime:
        if not value:
            return utc_now()
        if isinstance(value, datetime):
            return ensure_utc(value)
        return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
