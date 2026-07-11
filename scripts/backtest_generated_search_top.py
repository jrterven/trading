from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from backend.services.sandbox import run_strategy_subprocess
from backend.services.backtesting import simulate_long_only
from backend.schemas import Bar


ASSETS = ("AMD", "AMZN", "GOOGL", "NVDA", "AAPL", "META", "TSLA", "NFLX")


def parse_args():
    parser = argparse.ArgumentParser(description="Backtest the generated top strategy.")
    parser.add_argument("--db", default="data/trading.duckdb")
    parser.add_argument("--strategy", default="strategies/generated_search_top.py")
    parser.add_argument("--warmup-start", default="2025-01-01")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-06-30 23:59:59")
    return parser.parse_args()


def main():
    args = parse_args()
    code = Path(args.strategy).read_text(encoding="utf-8")
    con = duckdb.connect(args.db, read_only=True)
    results = {}
    try:
        for symbol in ASSETS:
            candles = con.execute(
                """
                SELECT symbol, timeframe, timestamp, open, high, low, close, volume, source
                FROM bars
                WHERE symbol = ? AND timeframe = '1Day'
                  AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp
                """,
                [symbol, args.warmup_start, args.end],
            ).fetchdf()
            payload = {
                "symbol": symbol,
                "timeframe": "1Day",
                "candles": candles.to_dict("records"),
                "news": [],
                "sentiment": [],
            }
            output = run_strategy_subprocess(code, payload, timeout_seconds=60)
            timestamps = pd.to_datetime(candles["timestamp"], utc=True)
            test_mask = (timestamps >= pd.Timestamp(args.start, tz="UTC")) & (
                timestamps <= pd.Timestamp(args.end, tz="UTC")
            )
            test_candles = candles.loc[test_mask].copy()
            test_entries = [value for value, keep in zip(output["entries"], test_mask.tolist()) if keep]
            test_exits = [value for value, keep in zip(output["exits"], test_mask.tolist()) if keep]
            bars = [Bar(**row) for row in test_candles.to_dict("records")]
            simulation = simulate_long_only(
                bars=bars,
                entries=test_entries,
                exits=test_exits,
                initial_cash=10_000,
                commission_pct=0.001,
                position_size_cash=None,
                stop_loss_pct=None,
                take_profit_pct=None,
                run_id="generated-local",
                symbol=symbol,
            )
            results[symbol] = simulation["metrics"]
    finally:
        con.close()
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
