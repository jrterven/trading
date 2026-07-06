from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.schemas import BacktestRequest, Bar
from backend.sample_data import generate_bars
from backend.services.backtesting import BacktestService
from backend.services.backtesting import simulate_long_only


def test_simulate_long_only_generates_trade_and_metrics():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=80)
    bars = generate_bars("AAPL", "1Day", start, end)
    entries = [False] * len(bars)
    exits = [False] * len(bars)
    entries[5] = True
    exits[20] = True

    result = simulate_long_only(
        bars=bars,
        entries=entries,
        exits=exits,
        initial_cash=10000,
        commission_pct=0.001,
        run_id="run-1",
        symbol="AAPL",
    )

    assert result["metrics"]["trade_count"] == 1
    assert result["trades"][0].entry_price == bars[5].close
    assert result["trades"][0].exit_price == bars[20].close
    assert len(result["equity_curve"]) == len(bars)
    assert {marker.marker_type for marker in result["markers"]} == {"buy", "sell"}


def test_simulate_long_only_uses_position_size_and_stop_loss():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [
        Bar(
            symbol="AAPL",
            timeframe="1Day",
            timestamp=start,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1000,
        ),
        Bar(
            symbol="AAPL",
            timeframe="1Day",
            timestamp=start + timedelta(days=1),
            open=100,
            high=101,
            low=94,
            close=96,
            volume=1000,
        ),
    ]

    result = simulate_long_only(
        bars=bars,
        entries=[True, False],
        exits=[False, False],
        initial_cash=10000,
        commission_pct=0,
        position_size_cash=2000,
        stop_loss_pct=5,
        run_id="run-1",
        symbol="AAPL",
    )

    assert result["metrics"]["trade_count"] == 1
    assert result["trades"][0].quantity == 20
    assert result["trades"][0].exit_price == 95
    assert result["markers"][-1].label == "Stop"
    assert result["metrics"]["final_equity"] == 9900


@pytest.mark.asyncio
async def test_backtest_service_runs_user_strategy_in_sandbox():
    code = """
def run(ctx):
    n = len(ctx.candles)
    entries = [False] * n
    exits = [False] * n
    if n > 4:
        entries[1] = True
        exits[3] = True
    return {"entries": entries, "exits": exits, "markers": []}
"""
    run = await BacktestService().run(
        BacktestRequest(
            symbol="AAPL",
            timeframe="1Day",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 2, 1, tzinfo=UTC),
            code=code,
            strategy_name="sandbox test",
        )
    )

    assert run.status == "completed"
    assert run.metrics["trade_count"] == 1
    assert len(run.trades) == 1
