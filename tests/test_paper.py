from __future__ import annotations

import pytest

from backend.schemas import PaperOrderRequest
from backend.services.paper import PaperService


class FakeAlpaca:
    async def get_account(self):
        return {
            "portfolio_value": "100432.15",
            "cash": "50300.50",
            "buying_power": "201202.00",
            "currency": "USD",
            "trading_blocked": False,
        }

    async def get_positions(self):
        return [
            {
                "symbol": "AAPL",
                "qty": "2.5",
                "avg_entry_price": "200.00",
                "current_price": "210.00",
                "market_value": "525.00",
                "unrealized_pl": "25.00",
            }
        ]

    async def place_order(self, symbol: str, side: str, quantity: float):
        return {
            "id": "order-1",
            "symbol": symbol,
            "side": side,
            "qty": str(quantity),
            "filled_avg_price": "210.12",
            "status": "filled",
            "created_at": "2026-07-06T15:00:00Z",
        }


@pytest.mark.asyncio
async def test_paper_portfolio_uses_alpaca_account_and_positions():
    service = PaperService()
    service.alpaca = FakeAlpaca()

    portfolio = await service.portfolio()

    assert portfolio["equity"] == 100432.15
    assert portfolio["cash"] == 50300.50
    assert portfolio["buying_power"] == 201202.00
    assert portfolio["positions"] == [
        {
            "symbol": "AAPL",
            "quantity": 2.5,
            "avg_cost": 200.0,
            "last_price": 210.0,
            "market_value": 525.0,
            "unrealized_pnl": 25.0,
        }
    ]


@pytest.mark.asyncio
async def test_paper_order_maps_alpaca_order_response():
    service = PaperService()
    service.alpaca = FakeAlpaca()

    order = await service.place_order(PaperOrderRequest(symbol="aapl", side="buy", quantity=1.25))

    assert order.id == "order-1"
    assert order.symbol == "AAPL"
    assert order.side == "buy"
    assert order.quantity == 1.25
    assert order.price == 210.12
    assert order.status == "filled"
