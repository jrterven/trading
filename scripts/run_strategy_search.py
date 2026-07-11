from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ASSETS = ("AMD", "AMZN", "GOOGL", "NVDA", "AAPL", "META", "TSLA", "NFLX")
TIMEFRAME = "1Day"
TRAIN_START = "2025-01-01"
TRAIN_END = "2026-01-01"
TEST_START = "2026-01-01"
TEST_END = "2026-07-01"
COMMISSION_PCT = 0.001
INITIAL_CASH = 10_000.0
MAX_ITERATIONS = 100
STOP_RETURN_PCT = 200.0
STOP_MAX_DRAWDOWN_PCT = 12.0

FEATURE_COLUMNS = [
    "return_1",
    "return_2",
    "return_3",
    "return_5",
    "return_10",
    "return_20",
    "return_40",
    "return_60",
    "volatility_5",
    "volatility_10",
    "volatility_20",
    "volatility_40",
    "range_pct",
    "sma_5_gap",
    "sma_10_gap",
    "sma_20_gap",
    "sma_50_gap",
    "sma_100_gap",
    "sma_20_slope_5",
    "sma_50_slope_10",
    "range_position_20",
    "range_position_60",
    "range_position_100",
    "dist_high_20",
    "dist_high_60",
    "dist_low_20",
    "dist_low_60",
    "drawdown_20",
    "drawdown_60",
    "breakout_20",
    "breakout_60",
    "breakdown_20",
    "volume_ratio_10",
    "volume_ratio_20",
    "volume_ratio_60",
    "rsi_14",
    "regime_score",
]


@dataclass(frozen=True)
class StrategyConfig:
    iteration: int
    name: str
    horizon: int
    target_bps: float
    entry_threshold: float
    exit_threshold: float
    l2: float
    epochs: int
    learning_rate: float
    trend_min: float
    min_range_position_60: float
    max_volatility_20: float
    stop_loss_pct: float | None
    trailing_stop_pct: float | None
    take_profit_pct: float | None
    max_hold_bars: int | None


def log(message: str) -> None:
    print(f"[strategy-search] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a 100-iteration per-asset strategy search on Trading Lab DuckDB data."
    )
    parser.add_argument("--db", default="data/trading.duckdb", help="Path to DuckDB database.")
    parser.add_argument(
        "--output-dir",
        default="outputs/strategy_search",
        help="Directory for JSON/CSV strategy search outputs.",
    )
    parser.add_argument(
        "--strategies-dir",
        default="strategies",
        help="Directory where the top generated strategy is saved.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=MAX_ITERATIONS,
        help="Maximum number of strategy variations to try.",
    )
    return parser.parse_args()


def generate_configs(iterations: int) -> list[StrategyConfig]:
    horizons = [3, 5, 7, 10, 15]
    target_bps = [0.0, 25.0, 50.0, 75.0, 125.0]
    entry_thresholds = [0.50, 0.54, 0.58, 0.62]
    exit_offsets = [0.08, 0.12, 0.16]
    l2_values = [0.01, 0.03, 0.08, 0.16]
    epoch_values = [60, 100, 160]
    learning_rates = [0.025, 0.035]
    trend_mins = [1.0, 2.0, 3.0, 4.0]
    range_positions = [0.15, 0.25, 0.35]
    max_vols = [0.04, 0.055, 0.075, 0.10]
    stop_losses = [None, 0.06, 0.08, 0.10, 0.12]
    trailing_stops = [None, 0.08, 0.12, 0.16]
    take_profits = [None, 0.18, 0.30, 0.50]
    max_holds = [None, 10, 20, 40]

    configs: list[StrategyConfig] = []
    for index in range(iterations):
        horizon = horizons[index % len(horizons)]
        entry = entry_thresholds[(index // 5) % len(entry_thresholds)]
        offset = exit_offsets[(index // 11) % len(exit_offsets)]
        exit_threshold = max(0.32, entry - offset)
        configs.append(
            StrategyConfig(
                iteration=index + 1,
                name=f"per_asset_arx_v{index + 1:03d}_h{horizon}_e{int(entry * 100)}",
                horizon=horizon,
                target_bps=target_bps[(index // 3) % len(target_bps)],
                entry_threshold=entry,
                exit_threshold=exit_threshold,
                l2=l2_values[(index // 7) % len(l2_values)],
                epochs=epoch_values[(index // 13) % len(epoch_values)],
                learning_rate=learning_rates[(index // 17) % len(learning_rates)],
                trend_min=trend_mins[(index // 19) % len(trend_mins)],
                min_range_position_60=range_positions[(index // 23) % len(range_positions)],
                max_volatility_20=max_vols[(index // 29) % len(max_vols)],
                stop_loss_pct=stop_losses[(index // 31) % len(stop_losses)],
                trailing_stop_pct=trailing_stops[(index // 37) % len(trailing_stops)],
                take_profit_pct=take_profits[(index // 41) % len(take_profits)],
                max_hold_bars=max_holds[(index // 43) % len(max_holds)],
            )
        )
    return configs


def load_bars(db_path: Path) -> dict[str, pd.DataFrame]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        placeholders = ", ".join(["?"] * len(ASSETS))
        rows = con.execute(
            f"""
            SELECT symbol, timeframe, timestamp, open, high, low, close, volume, source
            FROM bars
            WHERE timeframe = ?
              AND symbol IN ({placeholders})
              AND timestamp >= ?
              AND timestamp < ?
            ORDER BY symbol, timestamp
            """,
            [TIMEFRAME, *ASSETS, TRAIN_START, TEST_END],
        ).fetchdf()
    finally:
        con.close()
    if rows.empty:
        raise SystemExit("No bars found for requested assets/timeframe/range.")
    rows["timestamp"] = pd.to_datetime(rows["timestamp"], utc=True)
    result: dict[str, pd.DataFrame] = {}
    for symbol in ASSETS:
        symbol_rows = rows[rows["symbol"] == symbol].copy().sort_values("timestamp")
        if symbol_rows.empty:
            raise SystemExit(f"No bars found for {symbol}")
        result[symbol] = symbol_rows.reset_index(drop=True)
    return result


def safe_range_position(close: pd.Series, low: pd.Series, high: pd.Series) -> pd.Series:
    width = (high - low).replace(0, np.nan)
    return ((close - low) / width).clip(0.0, 1.0)


def calculate_features(candles: pd.DataFrame) -> pd.DataFrame:
    df = candles.copy().sort_values("timestamp")
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float).replace(0, np.nan)
    returns = close.pct_change()
    features = pd.DataFrame(index=df.index)

    features["return_1"] = returns
    for window in (2, 3, 5, 10, 20, 40, 60):
        features[f"return_{window}"] = close / close.shift(window) - 1.0
    for window in (5, 10, 20, 40):
        features[f"volatility_{window}"] = returns.rolling(window, min_periods=max(3, window // 2)).std()
    features["range_pct"] = (high - low) / close

    sma_5 = close.rolling(5, min_periods=2).mean()
    sma_10 = close.rolling(10, min_periods=4).mean()
    sma_20 = close.rolling(20, min_periods=8).mean()
    sma_50 = close.rolling(50, min_periods=20).mean()
    sma_100 = close.rolling(100, min_periods=40).mean()
    features["sma_5_gap"] = close / sma_5 - 1.0
    features["sma_10_gap"] = close / sma_10 - 1.0
    features["sma_20_gap"] = close / sma_20 - 1.0
    features["sma_50_gap"] = close / sma_50 - 1.0
    features["sma_100_gap"] = close / sma_100 - 1.0
    features["sma_20_slope_5"] = sma_20 / sma_20.shift(5) - 1.0
    features["sma_50_slope_10"] = sma_50 / sma_50.shift(10) - 1.0

    previous_high_20 = high.rolling(20, min_periods=8).max().shift(1)
    previous_high_60 = high.rolling(60, min_periods=20).max().shift(1)
    previous_low_20 = low.rolling(20, min_periods=8).min().shift(1)
    for window in (20, 60, 100):
        rolling_high = high.rolling(window, min_periods=max(8, window // 3)).max()
        rolling_low = low.rolling(window, min_periods=max(8, window // 3)).min()
        features[f"range_position_{window}"] = safe_range_position(close, rolling_low, rolling_high)
        if window in (20, 60):
            features[f"dist_high_{window}"] = close / rolling_high - 1.0
            features[f"dist_low_{window}"] = close / rolling_low - 1.0
            features[f"drawdown_{window}"] = close / rolling_high - 1.0

    features["breakout_20"] = (close > previous_high_20).astype(float)
    features["breakout_60"] = (close > previous_high_60).astype(float)
    features["breakdown_20"] = (close < previous_low_20).astype(float)
    features["volume_ratio_10"] = volume / volume.rolling(10, min_periods=4).mean() - 1.0
    features["volume_ratio_20"] = volume / volume.rolling(20, min_periods=8).mean() - 1.0
    features["volume_ratio_60"] = volume / volume.rolling(60, min_periods=20).mean() - 1.0

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
    rs = gain / loss.replace(0, np.nan)
    features["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0) / 100.0
    trend_checks = pd.concat(
        [
            (close > sma_20).astype(float),
            (close > sma_50).astype(float),
            (sma_20 > sma_50).astype(float),
            (features["sma_20_slope_5"] > 0).astype(float),
            (features["sma_50_slope_10"] > 0).astype(float),
        ],
        axis=1,
    )
    features["regime_score"] = trend_checks.sum(axis=1)
    features = features[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return pd.concat([df[["symbol", "timestamp", "open", "high", "low", "close", "volume"]], features], axis=1)


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def train_logistic(
    features: pd.DataFrame,
    config: StrategyConfig,
) -> dict[str, Any]:
    close = features["close"].astype(float)
    future_return = close.shift(-config.horizon) / close - 1.0
    train_mask = (
        (features["timestamp"] >= pd.Timestamp(TRAIN_START, tz="UTC"))
        & (features["timestamp"] < pd.Timestamp(TRAIN_END, tz="UTC"))
        & future_return.notna()
    )
    train_rows = features.loc[train_mask]
    if len(train_rows) < 80:
        raise ValueError("Not enough training rows")
    x_raw = train_rows[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = (future_return.loc[train_mask].to_numpy(dtype=float) > config.target_bps / 10_000.0).astype(float)
    means = x_raw.mean(axis=0)
    stds = np.where(x_raw.std(axis=0) < 1e-8, 1.0, x_raw.std(axis=0))
    x = (x_raw - means) / stds
    weights = np.zeros(x.shape[1], dtype=float)
    bias = 0.0
    positive_rate = float(y.mean())
    pos_weight = 0.5 / max(positive_rate, 1e-6)
    neg_weight = 0.5 / max(1.0 - positive_rate, 1e-6)
    sample_weights = np.where(y == 1, pos_weight, neg_weight)
    for _ in range(config.epochs):
        probabilities = sigmoid(x @ weights + bias)
        error = (probabilities - y) * sample_weights
        grad_w = (x.T @ error) / len(x) + config.l2 * weights
        grad_b = float(error.mean())
        weights -= config.learning_rate * grad_w
        bias -= config.learning_rate * grad_b
    return {
        "weights": weights.round(12).tolist(),
        "bias": float(round(bias, 12)),
        "means": means.round(12).tolist(),
        "stds": stds.round(12).tolist(),
        "positive_rate": positive_rate,
        "train_rows": int(len(train_rows)),
    }


def predict_probabilities(features: pd.DataFrame, model: dict[str, Any]) -> pd.Series:
    x_raw = features[FEATURE_COLUMNS].to_numpy(dtype=float)
    means = np.asarray(model["means"], dtype=float)
    stds = np.asarray(model["stds"], dtype=float)
    weights = np.asarray(model["weights"], dtype=float)
    bias = float(model["bias"])
    values = ((x_raw - means) / stds) @ weights + bias
    return pd.Series(sigmoid(values), index=features.index)


def build_signals(
    features: pd.DataFrame,
    probabilities: pd.Series,
    config: StrategyConfig,
) -> tuple[pd.Series, pd.Series]:
    test_mask = (features["timestamp"] >= pd.Timestamp(TEST_START, tz="UTC")) & (
        features["timestamp"] < pd.Timestamp(TEST_END, tz="UTC")
    )
    trend_ok = (
        (features["regime_score"] >= config.trend_min)
        & (features["range_position_60"] >= config.min_range_position_60)
        & (features["volatility_20"] <= config.max_volatility_20)
        & (features["breakdown_20"] < 0.5)
    )
    raw_entries = (probabilities >= config.entry_threshold) & trend_ok & test_mask
    raw_exits = (
        (probabilities <= config.exit_threshold)
        | (features["breakdown_20"] > 0.5)
        | ((features["sma_20_gap"] < -0.05) & (features["regime_score"] <= 2.0))
    ) & test_mask

    entries = pd.Series(False, index=features.index)
    exits = pd.Series(False, index=features.index)
    in_position = False
    entry_price = 0.0
    peak_price = 0.0
    held_bars = 0
    close = features["close"].astype(float)
    for index in features.index:
        if not bool(test_mask.loc[index]):
            continue
        price = float(close.loc[index])
        if not in_position and bool(raw_entries.loc[index]):
            entries.loc[index] = True
            in_position = True
            entry_price = price
            peak_price = price
            held_bars = 0
            continue
        if not in_position:
            continue
        held_bars += 1
        peak_price = max(peak_price, price)
        should_exit = bool(raw_exits.loc[index])
        if config.stop_loss_pct is not None and price <= entry_price * (1.0 - config.stop_loss_pct):
            should_exit = True
        if config.trailing_stop_pct is not None and price <= peak_price * (1.0 - config.trailing_stop_pct):
            should_exit = True
        if config.take_profit_pct is not None and price >= entry_price * (1.0 + config.take_profit_pct):
            should_exit = True
        if config.max_hold_bars is not None and held_bars >= config.max_hold_bars:
            should_exit = True
        if should_exit:
            exits.loc[index] = True
            in_position = False
            entry_price = 0.0
            peak_price = 0.0
            held_bars = 0
    return entries, exits


def simulate(
    features: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
) -> dict[str, float]:
    test_rows = features[
        (features["timestamp"] >= pd.Timestamp(TEST_START, tz="UTC"))
        & (features["timestamp"] < pd.Timestamp(TEST_END, tz="UTC"))
    ]
    cash = INITIAL_CASH
    quantity = 0.0
    trade_count = 0
    equity_curve: list[float] = []
    for index, row in test_rows.iterrows():
        price = float(row["close"])
        if quantity == 0.0 and bool(entries.loc[index]):
            quantity = cash / (price * (1.0 + COMMISSION_PCT))
            gross = quantity * price
            cash -= gross + gross * COMMISSION_PCT
            trade_count += 1
        elif quantity > 0.0 and bool(exits.loc[index]):
            gross = quantity * price
            cash += gross - gross * COMMISSION_PCT
            quantity = 0.0
        equity_curve.append(cash + quantity * price)

    if not equity_curve:
        equity_curve = [INITIAL_CASH]
    equities = np.asarray(equity_curve, dtype=float)
    returns = np.diff(equities) / equities[:-1] if len(equities) > 1 else np.asarray([])
    cumulative_return_pct = float((equities[-1] / INITIAL_CASH - 1.0) * 100.0)
    peak = np.maximum.accumulate(equities)
    drawdowns = (equities - peak) / peak
    max_drawdown_pct = float(abs(drawdowns.min()) * 100.0) if len(drawdowns) else 0.0
    sharpe = 0.0
    if len(returns) > 1 and float(np.std(returns)) > 0:
        sharpe = float((np.mean(returns) / np.std(returns)) * math.sqrt(252))
    return {
        "cumulative_return_pct": round(cumulative_return_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "sharpe": round(sharpe, 6),
        "trade_count": float(trade_count),
    }


def evaluate_config(
    config: StrategyConfig,
    feature_by_symbol: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    models: dict[str, dict[str, Any]] = {}
    metrics: dict[str, dict[str, float]] = {}
    for symbol, features in feature_by_symbol.items():
        model = train_logistic(features, config)
        probabilities = predict_probabilities(features, model)
        entries, exits = build_signals(features, probabilities, config)
        symbol_metrics = simulate(features, entries, exits)
        model["latest_probability"] = float(probabilities.iloc[-1])
        models[symbol] = model
        metrics[symbol] = symbol_metrics

    returns = [metrics[symbol]["cumulative_return_pct"] for symbol in ASSETS]
    drawdowns = [metrics[symbol]["max_drawdown_pct"] for symbol in ASSETS]
    sharpes = [metrics[symbol]["sharpe"] for symbol in ASSETS]
    meets = all(value > STOP_RETURN_PCT for value in returns) and all(
        value < STOP_MAX_DRAWDOWN_PCT for value in drawdowns
    )
    objective_score = (
        min(returns) * 2.0
        + float(np.mean(returns))
        + sum(1 for value in returns if value > 0) * 10.0
        - max(drawdowns) * 3.0
        + float(np.mean(sharpes)) * 2.0
    )
    return {
        "config": asdict(config),
        "models": models,
        "metrics": metrics,
        "summary": {
            "avg_return_pct": round(float(np.mean(returns)), 4),
            "min_return_pct": round(float(min(returns)), 4),
            "max_drawdown_pct": round(float(max(drawdowns)), 4),
            "avg_sharpe": round(float(np.mean(sharpes)), 6),
            "positive_asset_count": int(sum(1 for value in returns if value > 0)),
            "meets_stopping_conditions": bool(meets),
            "objective_score": round(float(objective_score), 6),
        },
    }


def flatten_result(result: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Strategy": result["config"]["name"],
        "Iteration": result["config"]["iteration"],
        "Horizon": result["config"]["horizon"],
        "TargetBps": result["config"]["target_bps"],
        "EntryThreshold": result["config"]["entry_threshold"],
        "ExitThreshold": result["config"]["exit_threshold"],
        "TrendMin": result["config"]["trend_min"],
        "StopLossPct": result["config"]["stop_loss_pct"],
        "TrailingStopPct": result["config"]["trailing_stop_pct"],
        "TakeProfitPct": result["config"]["take_profit_pct"],
        "MaxHoldBars": result["config"]["max_hold_bars"],
        "AvgReturnPct": result["summary"]["avg_return_pct"],
        "MinReturnPct": result["summary"]["min_return_pct"],
        "MaxDrawdownPct": result["summary"]["max_drawdown_pct"],
        "AvgSharpe": result["summary"]["avg_sharpe"],
        "PositiveAssetCount": result["summary"]["positive_asset_count"],
        "ObjectiveScore": result["summary"]["objective_score"],
        "MeetsStoppingConditions": result["summary"]["meets_stopping_conditions"],
    }
    for symbol in ASSETS:
        symbol_metrics = result["metrics"][symbol]
        row[f"{symbol}_ReturnPct"] = symbol_metrics["cumulative_return_pct"]
        row[f"{symbol}_MaxDrawdownPct"] = symbol_metrics["max_drawdown_pct"]
        row[f"{symbol}_Sharpe"] = symbol_metrics["sharpe"]
        row[f"{symbol}_Trades"] = symbol_metrics["trade_count"]
    return row


def render_strategy(result: dict[str, Any]) -> str:
    config = result["config"]
    models = result["models"]
    return f'''"""
Generated top strategy from scripts/run_strategy_search.py.

This strategy contains one independently trained 2025 model per asset.
It does not combine time-series samples across symbols.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "{config["name"]}"
VERSION = "search-top-0.1"
DESCRIPTION = "Per-asset autoregressive logistic model with technical regime exits."
FEATURE_COLUMNS = {json.dumps(FEATURE_COLUMNS, indent=4)}
MODELS = {json.dumps(models, indent=4)}
CONFIG = {json.dumps(config, indent=4)}


def _sigmoid(values):
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def _safe_range_position(close, low, high):
    width = (high - low).replace(0, np.nan)
    return ((close - low) / width).clip(0.0, 1.0)


def _calculate_features(candles):
    df = candles.copy()
    df["_strategy_timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("_strategy_timestamp")
    df["timestamp"] = df["_strategy_timestamp"]
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float).replace(0, np.nan)
    returns = close.pct_change()
    features = pd.DataFrame(index=df.index)
    features["return_1"] = returns
    for window in (2, 3, 5, 10, 20, 40, 60):
        features[f"return_{{window}}"] = close / close.shift(window) - 1.0
    for window in (5, 10, 20, 40):
        features[f"volatility_{{window}}"] = returns.rolling(window, min_periods=max(3, window // 2)).std()
    features["range_pct"] = (high - low) / close

    sma_5 = close.rolling(5, min_periods=2).mean()
    sma_10 = close.rolling(10, min_periods=4).mean()
    sma_20 = close.rolling(20, min_periods=8).mean()
    sma_50 = close.rolling(50, min_periods=20).mean()
    sma_100 = close.rolling(100, min_periods=40).mean()
    features["sma_5_gap"] = close / sma_5 - 1.0
    features["sma_10_gap"] = close / sma_10 - 1.0
    features["sma_20_gap"] = close / sma_20 - 1.0
    features["sma_50_gap"] = close / sma_50 - 1.0
    features["sma_100_gap"] = close / sma_100 - 1.0
    features["sma_20_slope_5"] = sma_20 / sma_20.shift(5) - 1.0
    features["sma_50_slope_10"] = sma_50 / sma_50.shift(10) - 1.0

    previous_high_20 = high.rolling(20, min_periods=8).max().shift(1)
    previous_high_60 = high.rolling(60, min_periods=20).max().shift(1)
    previous_low_20 = low.rolling(20, min_periods=8).min().shift(1)
    for window in (20, 60, 100):
        rolling_high = high.rolling(window, min_periods=max(8, window // 3)).max()
        rolling_low = low.rolling(window, min_periods=max(8, window // 3)).min()
        features[f"range_position_{{window}}"] = _safe_range_position(close, rolling_low, rolling_high)
        if window in (20, 60):
            features[f"dist_high_{{window}}"] = close / rolling_high - 1.0
            features[f"dist_low_{{window}}"] = close / rolling_low - 1.0
            features[f"drawdown_{{window}}"] = close / rolling_high - 1.0
    features["breakout_20"] = (close > previous_high_20).astype(float)
    features["breakout_60"] = (close > previous_high_60).astype(float)
    features["breakdown_20"] = (close < previous_low_20).astype(float)
    features["volume_ratio_10"] = volume / volume.rolling(10, min_periods=4).mean() - 1.0
    features["volume_ratio_20"] = volume / volume.rolling(20, min_periods=8).mean() - 1.0
    features["volume_ratio_60"] = volume / volume.rolling(60, min_periods=20).mean() - 1.0

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
    rs = gain / loss.replace(0, np.nan)
    features["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0) / 100.0
    trend_checks = pd.concat(
        [
            (close > sma_20).astype(float),
            (close > sma_50).astype(float),
            (sma_20 > sma_50).astype(float),
            (features["sma_20_slope_5"] > 0).astype(float),
            (features["sma_50_slope_10"] > 0).astype(float),
        ],
        axis=1,
    )
    features["regime_score"] = trend_checks.sum(axis=1)
    features = features[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return pd.concat([df[["timestamp", "close"]], features], axis=1)


def _predict(features, model):
    values = features[FEATURE_COLUMNS].to_numpy(dtype=float)
    means = np.asarray(model["means"], dtype=float)
    stds = np.asarray(model["stds"], dtype=float)
    weights = np.asarray(model["weights"], dtype=float)
    bias = float(model["bias"])
    return pd.Series(_sigmoid(((values - means) / stds) @ weights + bias), index=features.index)


def run(ctx):
    candles = ctx.candles.copy()
    if candles.empty:
        return {{"entries": [], "exits": [], "markers": [], "debug": {{"reason": "no candles"}}}}

    symbol = str(getattr(ctx, "symbol", candles["symbol"].iloc[0])).upper()
    model = MODELS.get(symbol)
    if model is None:
        empty = pd.Series(False, index=candles.index)
        return {{"entries": empty, "exits": empty, "markers": [], "debug": {{"reason": f"unsupported symbol {{symbol}}"}}}}

    features = _calculate_features(candles)
    probabilities = _predict(features, model)
    trend_ok = (
        (features["regime_score"] >= CONFIG["trend_min"])
        & (features["range_position_60"] >= CONFIG["min_range_position_60"])
        & (features["volatility_20"] <= CONFIG["max_volatility_20"])
        & (features["breakdown_20"] < 0.5)
    )
    raw_entries = probabilities >= CONFIG["entry_threshold"]
    raw_exits = (
        (probabilities <= CONFIG["exit_threshold"])
        | (features["breakdown_20"] > 0.5)
        | ((features["sma_20_gap"] < -0.05) & (features["regime_score"] <= 2.0))
    )

    entries = pd.Series(False, index=features.index)
    exits = pd.Series(False, index=features.index)
    in_position = False
    entry_price = 0.0
    peak_price = 0.0
    held_bars = 0
    close = features["close"].astype(float)
    for index in features.index:
        price = float(close.loc[index])
        if not in_position and bool(raw_entries.loc[index] and trend_ok.loc[index]):
            entries.loc[index] = True
            in_position = True
            entry_price = price
            peak_price = price
            held_bars = 0
            continue
        if not in_position:
            continue
        held_bars += 1
        peak_price = max(peak_price, price)
        should_exit = bool(raw_exits.loc[index])
        if CONFIG["stop_loss_pct"] is not None and price <= entry_price * (1.0 - CONFIG["stop_loss_pct"]):
            should_exit = True
        if CONFIG["trailing_stop_pct"] is not None and price <= peak_price * (1.0 - CONFIG["trailing_stop_pct"]):
            should_exit = True
        if CONFIG["take_profit_pct"] is not None and price >= entry_price * (1.0 + CONFIG["take_profit_pct"]):
            should_exit = True
        if CONFIG["max_hold_bars"] is not None and held_bars >= CONFIG["max_hold_bars"]:
            should_exit = True
        if should_exit:
            exits.loc[index] = True
            in_position = False
            entry_price = 0.0
            peak_price = 0.0
            held_bars = 0

    return {{
        "entries": entries.reindex(candles.index, fill_value=False),
        "exits": exits.reindex(candles.index, fill_value=False),
        "markers": [],
        "debug": {{
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "symbol": symbol,
            "model_train_rows": int(model.get("train_rows", 0)),
            "model_positive_rate": float(model.get("positive_rate", 0.0)),
            "latest_probability": float(probabilities.iloc[-1]),
            "entry_count": int(entries.sum()),
            "exit_count": int(exits.sum()),
        }},
    }}
'''


def render_backtest_script() -> str:
    return '''from __future__ import annotations

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
'''


def save_outputs(output_dir: Path, strategies_dir: Path, results: list[dict[str, Any]], top: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    strategies_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "strategy_search_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (output_dir / "top_strategy.json").write_text(json.dumps(top, indent=2), encoding="utf-8")

    rows = [flatten_result(result) for result in results]
    with (output_dir / "strategy_search_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    (strategies_dir / "generated_search_top.py").write_text(render_strategy(top), encoding="utf-8")
    (Path("scripts") / "backtest_generated_search_top.py").write_text(
        render_backtest_script(),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    output_dir = Path(args.output_dir)
    strategies_dir = Path(args.strategies_dir)
    bars_by_symbol = load_bars(db_path)
    feature_by_symbol = {symbol: calculate_features(rows) for symbol, rows in bars_by_symbol.items()}
    for symbol, rows in feature_by_symbol.items():
        train_rows = rows[(rows["timestamp"] >= pd.Timestamp(TRAIN_START, tz="UTC")) & (rows["timestamp"] < pd.Timestamp(TRAIN_END, tz="UTC"))]
        test_rows = rows[(rows["timestamp"] >= pd.Timestamp(TEST_START, tz="UTC")) & (rows["timestamp"] < pd.Timestamp(TEST_END, tz="UTC"))]
        log(f"{symbol}: train_rows={len(train_rows)}, test_rows={len(test_rows)}")

    configs = generate_configs(min(args.iterations, MAX_ITERATIONS))
    results: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for config in configs:
        result = evaluate_config(config, feature_by_symbol)
        results.append(result)
        if best is None or result["summary"]["objective_score"] > best["summary"]["objective_score"]:
            best = result
        summary = result["summary"]
        log(
            f"{config.iteration:03d}/{len(configs):03d} {config.name} "
            f"avg_return={summary['avg_return_pct']:.2f}% "
            f"min_return={summary['min_return_pct']:.2f}% "
            f"max_dd={summary['max_drawdown_pct']:.2f}% "
            f"positive_assets={summary['positive_asset_count']}/8 "
            f"score={summary['objective_score']:.2f}"
        )
        if summary["meets_stopping_conditions"]:
            log("stopping conditions satisfied")
            break

    if best is None:
        raise SystemExit("No strategy results were produced.")
    save_outputs(output_dir, strategies_dir, results, best)
    log(f"saved {len(results)} results to {output_dir}")
    log(f"top strategy: {best['config']['name']} summary={best['summary']}")


if __name__ == "__main__":
    main()
