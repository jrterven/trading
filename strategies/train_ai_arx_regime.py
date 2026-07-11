from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


TIMEFRAME = "1Day"
TRAIN_START = "2025-01-01"
TRAIN_END = "2026-01-01"
FEATURE_WARMUP_DAYS = 220
NEWS_LOOKBACK_SHORT_DAYS = 7
NEWS_LOOKBACK_LONG_DAYS = 30
TARGET_5D_BPS = 75.0
TARGET_10D_BPS = 125.0
MIN_TRAIN_BARS_PER_SYMBOL = 180
RETURN_LAGS = tuple(range(1, 21))
FEATURE_COLUMNS = [
    *[f"return_lag_{lag}" for lag in RETURN_LAGS],
    "return_5",
    "return_10",
    "return_20",
    "return_60",
    "return_120",
    "volatility_10",
    "volatility_20",
    "volatility_60",
    "range_pct",
    "sma_10_gap",
    "sma_20_gap",
    "sma_50_gap",
    "sma_100_gap",
    "sma_20_slope_10",
    "sma_50_slope_20",
    "range_position_20",
    "range_position_60",
    "range_position_120",
    "dist_high_20",
    "dist_high_60",
    "dist_high_120",
    "dist_low_20",
    "dist_low_60",
    "dist_low_120",
    "drawdown_20",
    "drawdown_60",
    "drawdown_120",
    "breakout_20",
    "breakout_60",
    "breakdown_20",
    "volume_ratio_20",
    "volume_ratio_60",
    "rsi_14",
    "regime_score",
    "news_count_7d",
    "direct_news_count_7d",
    "avg_signed_sentiment_7d",
    "sentiment_intensity_7d",
    "news_count_30d",
    "direct_news_count_30d",
    "avg_signed_sentiment_30d",
    "sentiment_intensity_30d",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the AI ARX Regime strategy on 2025 Trading Lab data."
    )
    parser.add_argument("--db", default="data/trading.duckdb", help="Path to the DuckDB file.")
    parser.add_argument(
        "--output",
        default="strategies/ai_arx_regime.py",
        help="Strategy file to write with embedded model weights.",
    )
    parser.add_argument(
        "--model-json",
        default="strategies/ai_arx_regime_model.json",
        help="Metadata/model JSON output path.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Optional symbols. Defaults to every 1Day symbol with enough 2025 bars.",
    )
    parser.add_argument("--epochs", type=int, default=250, help="Training epochs per model.")
    parser.add_argument("--learning-rate", type=float, default=0.025, help="Gradient step size.")
    parser.add_argument("--l2", type=float, default=0.08, help="L2 regularization strength.")
    parser.add_argument("--log-every", type=int, default=50, help="Print metrics every N epochs.")
    parser.add_argument(
        "--target-5d-bps",
        type=float,
        default=TARGET_5D_BPS,
        help="Positive label threshold for 5-day return, in basis points.",
    )
    parser.add_argument(
        "--target-10d-bps",
        type=float,
        default=TARGET_10D_BPS,
        help="Positive label threshold for 10-day return, in basis points.",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(f"[train-ai-arx-regime] {message}", flush=True)


def discover_symbols(con: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    rows = con.execute(
        """
        SELECT symbol, COUNT(*) AS bars
        FROM bars
        WHERE timeframe = ?
          AND timestamp >= ?
          AND timestamp < ?
        GROUP BY 1
        HAVING COUNT(*) >= ?
        ORDER BY 1
        """,
        [TIMEFRAME, TRAIN_START, TRAIN_END, MIN_TRAIN_BARS_PER_SYMBOL],
    ).fetchdf()
    return tuple(rows["symbol"].astype(str).str.upper().tolist())


def load_bars(
    con: duckdb.DuckDBPyConnection,
    symbols: tuple[str, ...],
    timeframe: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    placeholders = ", ".join(["?"] * len(symbols))
    warmup_start = str(pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=FEATURE_WARMUP_DAYS))
    rows = con.execute(
        f"""
        SELECT symbol, timeframe, timestamp, open, high, low, close, volume, source
        FROM bars
        WHERE symbol IN ({placeholders})
          AND timeframe = ?
          AND timestamp >= ?
          AND timestamp < ?
        ORDER BY symbol, timestamp
        """,
        [*symbols, timeframe, warmup_start, end],
    ).fetchdf()
    rows["timestamp"] = pd.to_datetime(rows["timestamp"], utc=True)
    return rows


def load_news_sentiment(
    con: duckdb.DuckDBPyConnection,
    symbols: tuple[str, ...],
    start: str,
    end: str,
) -> pd.DataFrame:
    placeholders = ", ".join(["?"] * len(symbols))
    warmup_start = str(pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=NEWS_LOOKBACK_LONG_DAYS))
    rows = con.execute(
        f"""
        SELECT
            nas.symbol,
            na.id AS article_id,
            COALESCE(na.available_at, na.published_at) AS available_at,
            nas.relation_type,
            COALESCE(ss.label, 'neutral') AS label,
            COALESCE(ss.score, 0) AS score,
            COALESCE(ss.positive, 0) AS positive,
            COALESCE(ss.neutral, 0) AS neutral,
            COALESCE(ss.negative, 0) AS negative
        FROM news_articles na
        JOIN news_article_symbols nas ON nas.article_id = na.id
        LEFT JOIN sentiment_scores ss
          ON ss.article_id = na.id
         AND ss.symbol = nas.symbol
        WHERE nas.symbol IN ({placeholders})
          AND COALESCE(na.available_at, na.published_at) >= ?
          AND COALESCE(na.available_at, na.published_at) < ?
        ORDER BY nas.symbol, available_at
        """,
        [*symbols, warmup_start, end],
    ).fetchdf()
    if rows.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "article_id",
                "available_at",
                "relation_type",
                "label",
                "score",
                "positive",
                "neutral",
                "negative",
            ]
        )
    rows["available_at"] = pd.to_datetime(rows["available_at"], utc=True)
    return rows


def signed_sentiment(sentiment: pd.DataFrame) -> pd.Series:
    labels = sentiment["label"].fillna("neutral")
    scores = sentiment["score"].fillna(0.0).astype(float)
    return np.select(
        [labels.eq("positive"), labels.eq("negative")],
        [scores, -scores],
        default=0.0,
    )


def aggregate_news_window(window: pd.DataFrame, suffix: str) -> dict[str, float]:
    if window.empty:
        return {
            f"news_count_{suffix}": 0.0,
            f"direct_news_count_{suffix}": 0.0,
            f"avg_signed_sentiment_{suffix}": 0.0,
            f"sentiment_intensity_{suffix}": 0.0,
        }
    return {
        f"news_count_{suffix}": float(len(window)),
        f"direct_news_count_{suffix}": float(window["relation_type"].eq("direct").sum()),
        f"avg_signed_sentiment_{suffix}": float(window["signed_sentiment"].mean()),
        f"sentiment_intensity_{suffix}": float(window["signed_sentiment"].abs().mean()),
    }


def add_news_features(candles: pd.DataFrame, news: pd.DataFrame) -> pd.DataFrame:
    enriched_parts: list[pd.DataFrame] = []
    for symbol, symbol_candles in candles.groupby("symbol", sort=False):
        symbol_candles = symbol_candles.sort_values("timestamp").copy()
        symbol_news = news[news["symbol"] == symbol].copy()
        if not symbol_news.empty:
            symbol_news["signed_sentiment"] = signed_sentiment(symbol_news)

        rows: list[dict[str, float]] = []
        for timestamp in symbol_candles["timestamp"]:
            cutoff = pd.Timestamp(timestamp)
            if symbol_news.empty:
                short_window = symbol_news
                long_window = symbol_news
            else:
                short_start = cutoff - pd.Timedelta(days=NEWS_LOOKBACK_SHORT_DAYS)
                long_start = cutoff - pd.Timedelta(days=NEWS_LOOKBACK_LONG_DAYS)
                short_window = symbol_news[
                    (symbol_news["available_at"] <= cutoff)
                    & (symbol_news["available_at"] > short_start)
                ]
                long_window = symbol_news[
                    (symbol_news["available_at"] <= cutoff)
                    & (symbol_news["available_at"] > long_start)
                ]
            row = aggregate_news_window(short_window, "7d")
            row.update(aggregate_news_window(long_window, "30d"))
            rows.append(row)
        news_features = pd.DataFrame(rows, index=symbol_candles.index)
        enriched_parts.append(pd.concat([symbol_candles, news_features], axis=1))
    return pd.concat(enriched_parts).sort_values(["symbol", "timestamp"])


def safe_range_position(close: pd.Series, low: pd.Series, high: pd.Series) -> pd.Series:
    width = (high - low).replace(0, np.nan)
    return ((close - low) / width).clip(0.0, 1.0)


def calculate_symbol_features(symbol_candles: pd.DataFrame) -> pd.DataFrame:
    df = symbol_candles.sort_values("timestamp").copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float).replace(0, np.nan)
    returns = close.pct_change()

    for lag in RETURN_LAGS:
        df[f"return_lag_{lag}"] = returns.shift(lag)

    for window in (5, 10, 20, 60, 120):
        df[f"return_{window}"] = close / close.shift(window) - 1.0

    df["volatility_10"] = returns.rolling(10, min_periods=5).std()
    df["volatility_20"] = returns.rolling(20, min_periods=8).std()
    df["volatility_60"] = returns.rolling(60, min_periods=20).std()
    df["range_pct"] = (high - low) / close

    sma_10 = close.rolling(10, min_periods=5).mean()
    sma_20 = close.rolling(20, min_periods=8).mean()
    sma_50 = close.rolling(50, min_periods=20).mean()
    sma_100 = close.rolling(100, min_periods=40).mean()
    df["sma_10_gap"] = close / sma_10 - 1.0
    df["sma_20_gap"] = close / sma_20 - 1.0
    df["sma_50_gap"] = close / sma_50 - 1.0
    df["sma_100_gap"] = close / sma_100 - 1.0
    df["sma_20_slope_10"] = sma_20 / sma_20.shift(10) - 1.0
    df["sma_50_slope_20"] = sma_50 / sma_50.shift(20) - 1.0

    previous_high_20 = high.rolling(20, min_periods=8).max().shift(1)
    previous_high_60 = high.rolling(60, min_periods=20).max().shift(1)
    previous_low_20 = low.rolling(20, min_periods=8).min().shift(1)
    for window in (20, 60, 120):
        rolling_high = high.rolling(window, min_periods=max(8, window // 3)).max()
        rolling_low = low.rolling(window, min_periods=max(8, window // 3)).min()
        df[f"range_position_{window}"] = safe_range_position(close, rolling_low, rolling_high)
        df[f"dist_high_{window}"] = close / rolling_high - 1.0
        df[f"dist_low_{window}"] = close / rolling_low - 1.0
        df[f"drawdown_{window}"] = close / rolling_high - 1.0

    df["breakout_20"] = (close > previous_high_20).astype(float)
    df["breakout_60"] = (close > previous_high_60).astype(float)
    df["breakdown_20"] = (close < previous_low_20).astype(float)
    df["volume_ratio_20"] = volume / volume.rolling(20, min_periods=8).mean() - 1.0
    df["volume_ratio_60"] = volume / volume.rolling(60, min_periods=20).mean() - 1.0

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0) / 100.0

    trend_checks = pd.concat(
        [
            (close > sma_50).astype(float),
            (sma_20 > sma_50).astype(float),
            (df["sma_50_slope_20"] > 0).astype(float),
            (df["range_position_60"] > 0.45).astype(float),
            (df["return_20"] > 0).astype(float),
        ],
        axis=1,
    )
    df["regime_score"] = trend_checks.sum(axis=1)
    df["future_return_5"] = close.shift(-5) / close - 1.0
    df["future_return_10"] = close.shift(-10) / close - 1.0
    return df


def calculate_features(candles: pd.DataFrame, news: pd.DataFrame) -> pd.DataFrame:
    parts = [
        calculate_symbol_features(symbol_candles)
        for _, symbol_candles in candles.groupby("symbol", sort=False)
    ]
    featured = pd.concat(parts).sort_values(["symbol", "timestamp"])
    featured = add_news_features(featured, news)
    featured[FEATURE_COLUMNS] = (
        featured[FEATURE_COLUMNS]
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .astype(float)
    )
    return featured


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def binary_metrics(y_true: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict[str, float]:
    predictions = probabilities >= threshold
    positives = y_true == 1
    true_positive = float(np.logical_and(predictions, positives).sum())
    false_positive = float(np.logical_and(predictions, ~positives).sum())
    false_negative = float(np.logical_and(~predictions, positives).sum())
    accuracy = float((predictions == positives).mean()) if len(y_true) else 0.0
    precision = true_positive / max(true_positive + false_positive, 1.0)
    recall = true_positive / max(true_positive + false_negative, 1.0)
    f1 = 2.0 * precision * recall / max(precision + recall, 1e-12)
    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "signal_rate": float(predictions.mean()) if len(predictions) else 0.0,
    }


def log_loss(y_true: np.ndarray, probabilities: np.ndarray, weights: np.ndarray, l2: float) -> float:
    probabilities = np.clip(probabilities, 1e-7, 1.0 - 1e-7)
    base_loss = -np.mean(
        y_true * np.log(probabilities) + (1.0 - y_true) * np.log(1.0 - probabilities)
    )
    return float(base_loss + 0.5 * l2 * np.sum(weights * weights))


def train_logistic_regression(
    name: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    epochs: int,
    learning_rate: float,
    l2: float,
    log_every: int,
) -> tuple[np.ndarray, float]:
    weights = np.zeros(x_train.shape[1], dtype=float)
    bias = 0.0
    positive_rate = float(y_train.mean())
    pos_weight = 0.5 / max(positive_rate, 1e-6)
    neg_weight = 0.5 / max(1.0 - positive_rate, 1e-6)
    sample_weights = np.where(y_train == 1, pos_weight, neg_weight)
    log(
        f"{name} class balance: positive_rate={positive_rate:.3f}, "
        f"pos_weight={pos_weight:.3f}, neg_weight={neg_weight:.3f}"
    )
    for epoch in range(1, epochs + 1):
        probabilities = sigmoid(x_train @ weights + bias)
        error = (probabilities - y_train) * sample_weights
        grad_w = (x_train.T @ error) / len(x_train) + l2 * weights
        grad_b = float(error.mean())
        weights -= learning_rate * grad_w
        bias -= learning_rate * grad_b
        if epoch == 1 or epoch % log_every == 0 or epoch == epochs:
            train_prob = sigmoid(x_train @ weights + bias)
            val_prob = sigmoid(x_val @ weights + bias) if len(x_val) else np.array([])
            train_loss = log_loss(y_train, train_prob, weights, l2)
            val_loss = log_loss(y_val, val_prob, weights, l2) if len(x_val) else 0.0
            train_metrics = binary_metrics(y_train, train_prob, 0.5)
            val_metrics = binary_metrics(y_val, val_prob, 0.5) if len(x_val) else {}
            log(
                f"{name} epoch {epoch:04d}/{epochs} "
                f"loss={train_loss:.4f} val_loss={val_loss:.4f} "
                f"acc={train_metrics['accuracy']:.3f} "
                f"val_acc={val_metrics.get('accuracy', 0.0):.3f} "
                f"val_precision={val_metrics.get('precision', 0.0):.3f} "
                f"val_recall={val_metrics.get('recall', 0.0):.3f} "
                f"grad_norm={np.linalg.norm(grad_w):.4f}"
            )
    return weights, bias


def choose_threshold(y_val: np.ndarray, probabilities: np.ndarray) -> tuple[float, dict[str, float]]:
    best_threshold = 0.55
    best_score = -math.inf
    best_metrics: dict[str, float] = {}
    for threshold in np.arange(0.45, 0.81, 0.01):
        metrics = binary_metrics(y_val, probabilities, float(threshold))
        score = metrics["f1"] - max(0.0, metrics["signal_rate"] - 0.45) * 0.20
        if metrics["signal_rate"] < 0.04:
            score -= 0.20
        if score > best_score:
            best_score = score
            best_threshold = float(threshold)
            best_metrics = metrics
    return round(best_threshold, 2), best_metrics


def render_strategy(model: dict[str, object]) -> str:
    feature_columns = json.dumps(FEATURE_COLUMNS, indent=4)
    symbols = json.dumps(model["symbols"])
    return f'''"""
AI ARX Regime

Generated by strategies/train_ai_arx_regime.py.
The model uses autoregressive returns, support/resistance, regime features,
volume, and trailing news sentiment.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "AI ARX Regime"
VERSION = "0.1"
DESCRIPTION = "Long-only ARX/regime strategy with 5-day and 10-day AI forecasts."
RETURN_LAGS = tuple(range(1, 21))
FEATURE_COLUMNS = {feature_columns}
FEATURE_MEANS = np.array({json.dumps(model["feature_means"])}, dtype=float)
FEATURE_STDS = np.array({json.dumps(model["feature_stds"])}, dtype=float)
MODEL_5D_WEIGHTS = np.array({json.dumps(model["model_5d"]["weights"])}, dtype=float)
MODEL_5D_BIAS = {model["model_5d"]["bias"]:.12f}
MODEL_10D_WEIGHTS = np.array({json.dumps(model["model_10d"]["weights"])}, dtype=float)
MODEL_10D_BIAS = {model["model_10d"]["bias"]:.12f}
ENTRY_THRESHOLD_5D = {model["model_5d"]["entry_threshold"]:.4f}
ENTRY_THRESHOLD_10D = {model["model_10d"]["entry_threshold"]:.4f}
EXIT_THRESHOLD_5D = {model["model_5d"]["exit_threshold"]:.4f}
EXIT_THRESHOLD_10D = {model["model_10d"]["exit_threshold"]:.4f}
NEWS_LOOKBACK_SHORT_DAYS = {NEWS_LOOKBACK_SHORT_DAYS}
NEWS_LOOKBACK_LONG_DAYS = {NEWS_LOOKBACK_LONG_DAYS}
TARGET_5D_BPS = {model["target_5d_bps"]:.2f}
TARGET_10D_BPS = {model["target_10d_bps"]:.2f}


def _sigmoid(values):
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def _signed_sentiment(sentiment):
    labels = sentiment["label"].fillna("neutral")
    scores = sentiment["score"].fillna(0.0).astype(float)
    return np.select(
        [labels.eq("positive"), labels.eq("negative")],
        [scores, -scores],
        default=0.0,
    )


def _aggregate_news_window(window, suffix):
    if window.empty:
        return {{
            f"news_count_{{suffix}}": 0.0,
            f"direct_news_count_{{suffix}}": 0.0,
            f"avg_signed_sentiment_{{suffix}}": 0.0,
            f"sentiment_intensity_{{suffix}}": 0.0,
        }}
    return {{
        f"news_count_{{suffix}}": float(len(window)),
        f"direct_news_count_{{suffix}}": float(window["relation_type"].eq("direct").sum()),
        f"avg_signed_sentiment_{{suffix}}": float(window["signed_sentiment"].mean()),
        f"sentiment_intensity_{{suffix}}": float(window["signed_sentiment"].abs().mean()),
    }}


def _news_features(candles, news, sentiment):
    if news is None or not hasattr(news, "empty") or news.empty:
        news = pd.DataFrame(columns=["id", "available_at", "relation_type"])
    else:
        news = news.copy()
    if sentiment is None or not hasattr(sentiment, "empty") or sentiment.empty:
        sentiment = pd.DataFrame(
            columns=["article_id", "label", "score", "positive", "neutral", "negative"]
        )
    else:
        sentiment = sentiment.copy()
    if "available_at" in news:
        news["available_at"] = pd.to_datetime(news["available_at"], utc=True, errors="coerce")
    if "id" not in news:
        news["id"] = None
    if "relation_type" not in news:
        news["relation_type"] = "direct"
    if "article_id" not in sentiment:
        sentiment["article_id"] = None
    for column in ["positive", "neutral", "negative", "score"]:
        if column not in sentiment:
            sentiment[column] = 0.0
    if "label" not in sentiment:
        sentiment["label"] = "neutral"
    if not sentiment.empty:
        sentiment["signed_sentiment"] = _signed_sentiment(sentiment)

    rows = []
    for timestamp in candles["timestamp"]:
        cutoff = pd.to_datetime(timestamp, utc=True)
        if news.empty or "available_at" not in news:
            short_news = news.iloc[0:0]
            long_news = news.iloc[0:0]
        else:
            short_start = cutoff - pd.Timedelta(days=NEWS_LOOKBACK_SHORT_DAYS)
            long_start = cutoff - pd.Timedelta(days=NEWS_LOOKBACK_LONG_DAYS)
            short_news = news[
                (news["available_at"] <= cutoff) & (news["available_at"] > short_start)
            ]
            long_news = news[
                (news["available_at"] <= cutoff) & (news["available_at"] > long_start)
            ]

        def attach_sentiment(news_window):
            if news_window.empty:
                return news_window.assign(signed_sentiment=pd.Series(dtype=float))
            article_ids = set(news_window["id"].dropna().tolist())
            window_sentiment = sentiment[sentiment["article_id"].isin(article_ids)]
            if window_sentiment.empty:
                return news_window.assign(signed_sentiment=0.0)
            signed_value = float(window_sentiment["signed_sentiment"].mean())
            intensity_value = float(window_sentiment["signed_sentiment"].abs().mean())
            out = news_window.copy()
            out["signed_sentiment"] = signed_value
            out["_sentiment_intensity"] = intensity_value
            return out

        short_window = attach_sentiment(short_news)
        long_window = attach_sentiment(long_news)
        row = _aggregate_news_window(short_window, "7d")
        row.update(_aggregate_news_window(long_window, "30d"))
        if "_sentiment_intensity" in short_window:
            row["sentiment_intensity_7d"] = float(short_window["_sentiment_intensity"].mean())
        if "_sentiment_intensity" in long_window:
            row["sentiment_intensity_30d"] = float(long_window["_sentiment_intensity"].mean())
        rows.append(row)
    return pd.DataFrame(rows, index=candles.index)


def _safe_range_position(close, low, high):
    width = (high - low).replace(0, np.nan)
    return ((close - low) / width).clip(0.0, 1.0)


def _calculate_features(candles, news, sentiment):
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
    for lag in RETURN_LAGS:
        features[f"return_lag_{{lag}}"] = returns.shift(lag)
    for window in (5, 10, 20, 60, 120):
        features[f"return_{{window}}"] = close / close.shift(window) - 1.0
    features["volatility_10"] = returns.rolling(10, min_periods=5).std()
    features["volatility_20"] = returns.rolling(20, min_periods=8).std()
    features["volatility_60"] = returns.rolling(60, min_periods=20).std()
    features["range_pct"] = (high - low) / close

    sma_10 = close.rolling(10, min_periods=5).mean()
    sma_20 = close.rolling(20, min_periods=8).mean()
    sma_50 = close.rolling(50, min_periods=20).mean()
    sma_100 = close.rolling(100, min_periods=40).mean()
    features["sma_10_gap"] = close / sma_10 - 1.0
    features["sma_20_gap"] = close / sma_20 - 1.0
    features["sma_50_gap"] = close / sma_50 - 1.0
    features["sma_100_gap"] = close / sma_100 - 1.0
    features["sma_20_slope_10"] = sma_20 / sma_20.shift(10) - 1.0
    features["sma_50_slope_20"] = sma_50 / sma_50.shift(20) - 1.0

    previous_high_20 = high.rolling(20, min_periods=8).max().shift(1)
    previous_high_60 = high.rolling(60, min_periods=20).max().shift(1)
    previous_low_20 = low.rolling(20, min_periods=8).min().shift(1)
    for window in (20, 60, 120):
        rolling_high = high.rolling(window, min_periods=max(8, window // 3)).max()
        rolling_low = low.rolling(window, min_periods=max(8, window // 3)).min()
        features[f"range_position_{{window}}"] = _safe_range_position(close, rolling_low, rolling_high)
        features[f"dist_high_{{window}}"] = close / rolling_high - 1.0
        features[f"dist_low_{{window}}"] = close / rolling_low - 1.0
        features[f"drawdown_{{window}}"] = close / rolling_high - 1.0
    features["breakout_20"] = (close > previous_high_20).astype(float)
    features["breakout_60"] = (close > previous_high_60).astype(float)
    features["breakdown_20"] = (close < previous_low_20).astype(float)
    features["volume_ratio_20"] = volume / volume.rolling(20, min_periods=8).mean() - 1.0
    features["volume_ratio_60"] = volume / volume.rolling(60, min_periods=20).mean() - 1.0

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
    rs = gain / loss.replace(0, np.nan)
    features["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0) / 100.0
    trend_checks = pd.concat(
        [
            (close > sma_50).astype(float),
            (sma_20 > sma_50).astype(float),
            (features["sma_50_slope_20"] > 0).astype(float),
            (features["range_position_60"] > 0.45).astype(float),
            (features["return_20"] > 0).astype(float),
        ],
        axis=1,
    )
    features["regime_score"] = trend_checks.sum(axis=1)
    features = pd.concat([features, _news_features(df, news, sentiment)], axis=1)
    return features[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).fillna(0.0)


def run(ctx):
    candles = ctx.candles.copy()
    if candles.empty:
        return {{"entries": [], "exits": [], "markers": [], "debug": {{"reason": "no candles"}}}}

    features = _calculate_features(candles, ctx.news, ctx.sentiment)
    x_values = ((features.values - FEATURE_MEANS) / FEATURE_STDS).astype(float)
    probability_5d = pd.Series(
        _sigmoid(x_values @ MODEL_5D_WEIGHTS + MODEL_5D_BIAS),
        index=features.index,
        name="probability_5d",
    )
    probability_10d = pd.Series(
        _sigmoid(x_values @ MODEL_10D_WEIGHTS + MODEL_10D_BIAS),
        index=features.index,
        name="probability_10d",
    )

    trend_ok = (
        (features["regime_score"] >= 3.0)
        & (features["sma_20_gap"] > -0.03)
        & (features["range_position_60"] > 0.28)
        & (features["breakdown_20"] < 0.5)
    )
    risk_ok = (features["volatility_20"] < 0.07) | (features["regime_score"] >= 4.0)
    entries = (
        (probability_5d >= ENTRY_THRESHOLD_5D)
        & (probability_10d >= ENTRY_THRESHOLD_10D)
        & trend_ok
        & risk_ok
    )
    exits = (
        (probability_5d <= EXIT_THRESHOLD_5D)
        | (probability_10d <= EXIT_THRESHOLD_10D)
        | (features["breakdown_20"] > 0.5)
        | ((features["sma_20_gap"] < -0.045) & (features["regime_score"] <= 2.0))
    )

    entries = entries.fillna(False)
    exits = exits.fillna(False)
    if len(entries):
        entries.iloc[:30] = False

    markers = []
    high_confidence = probability_5d[
        (probability_5d >= max(ENTRY_THRESHOLD_5D + 0.08, 0.65))
        & (probability_10d >= ENTRY_THRESHOLD_10D)
    ]
    for timestamp, probability in high_confidence.tail(8).items():
        markers.append({{
            "timestamp": timestamp,
            "type": "signal",
            "label": f"ARX {{probability:.0%}}",
            "color": "#2563eb",
        }})

    return {{
        "entries": entries,
        "exits": exits,
        "markers": markers,
        "debug": {{
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "model": "two_horizon_logistic_arx",
            "trained_symbols": {symbols},
            "training_start": "{model["training_start"]}",
            "training_end": "{model["training_end"]}",
            "target_5d_bps": TARGET_5D_BPS,
            "target_10d_bps": TARGET_10D_BPS,
            "entry_threshold_5d": ENTRY_THRESHOLD_5D,
            "entry_threshold_10d": ENTRY_THRESHOLD_10D,
            "exit_threshold_5d": EXIT_THRESHOLD_5D,
            "exit_threshold_10d": EXIT_THRESHOLD_10D,
            "bars": int(len(candles)),
            "entry_count": int(entries.sum()),
            "exit_count": int(exits.sum()),
            "latest_probability_5d": float(probability_5d.iloc[-1]),
            "latest_probability_10d": float(probability_10d.iloc[-1]),
            "latest_regime_score": float(features["regime_score"].iloc[-1]),
            "mean_probability_5d": float(probability_5d.mean()),
            "mean_probability_10d": float(probability_10d.mean()),
        }},
    }}
'''


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    log(f"loading bars from {db_path}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        symbols = tuple(symbol.upper() for symbol in args.symbols) if args.symbols else discover_symbols(con)
        if not symbols:
            raise SystemExit("No symbols with enough 2025 daily bars were found.")
        bars = load_bars(con, symbols, TIMEFRAME, TRAIN_START, TRAIN_END)
        news = load_news_sentiment(con, symbols, TRAIN_START, TRAIN_END)
    finally:
        con.close()

    if bars.empty:
        raise SystemExit("No bars found for the requested training range.")

    log(
        "loaded "
        f"{len(bars):,} bars and {len(news):,} news/sentiment rows "
        f"for {', '.join(symbols)}"
    )
    for symbol, count in bars[bars["timestamp"] >= pd.Timestamp(TRAIN_START, tz="UTC")].groupby(
        "symbol"
    ).size().items():
        log(f"{symbol}: {count:,} training candles")

    dataset = calculate_features(bars, news)
    dataset = dataset[
        (dataset["timestamp"] >= pd.Timestamp(TRAIN_START, tz="UTC"))
        & (dataset["timestamp"] < pd.Timestamp(TRAIN_END, tz="UTC"))
    ].copy()
    dataset = dataset.dropna(subset=["future_return_5", "future_return_10"]).copy()
    dataset["target_5d"] = (dataset["future_return_5"] > args.target_5d_bps / 10_000.0).astype(
        int
    )
    dataset["target_10d"] = (
        dataset["future_return_10"] > args.target_10d_bps / 10_000.0
    ).astype(int)

    split_timestamp = pd.Timestamp("2025-11-01", tz="UTC")
    dataset = dataset.sort_values("timestamp")
    train_rows = dataset[dataset["timestamp"] < split_timestamp]
    val_rows = dataset[dataset["timestamp"] >= split_timestamp]
    if len(train_rows) < 100 or len(val_rows) < 30:
        raise SystemExit("Not enough rows to train and validate the model.")

    x_train_raw = train_rows[FEATURE_COLUMNS].to_numpy(dtype=float)
    x_val_raw = val_rows[FEATURE_COLUMNS].to_numpy(dtype=float)
    means = x_train_raw.mean(axis=0)
    stds = x_train_raw.std(axis=0)
    stds = np.where(stds < 1e-8, 1.0, stds)
    x_train = (x_train_raw - means) / stds
    x_val = (x_val_raw - means) / stds

    y_train_5d = train_rows["target_5d"].to_numpy(dtype=float)
    y_val_5d = val_rows["target_5d"].to_numpy(dtype=float)
    y_train_10d = train_rows["target_10d"].to_numpy(dtype=float)
    y_val_10d = val_rows["target_10d"].to_numpy(dtype=float)

    log(
        "dataset ready: "
        f"train_rows={len(train_rows):,}, val_rows={len(val_rows):,}, "
        f"features={len(FEATURE_COLUMNS)}, "
        f"target_5d>{args.target_5d_bps:.1f}bps, "
        f"target_10d>{args.target_10d_bps:.1f}bps"
    )
    log(
        "validation window: "
        f"{val_rows['timestamp'].min().date()} to {val_rows['timestamp'].max().date()}"
    )

    weights_5d, bias_5d = train_logistic_regression(
        name="5d",
        x_train=x_train,
        y_train=y_train_5d,
        x_val=x_val,
        y_val=y_val_5d,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        l2=args.l2,
        log_every=args.log_every,
    )
    weights_10d, bias_10d = train_logistic_regression(
        name="10d",
        x_train=x_train,
        y_train=y_train_10d,
        x_val=x_val,
        y_val=y_val_10d,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        l2=args.l2,
        log_every=args.log_every,
    )

    val_prob_5d = sigmoid(x_val @ weights_5d + bias_5d)
    val_prob_10d = sigmoid(x_val @ weights_10d + bias_10d)
    threshold_5d, metrics_5d = choose_threshold(y_val_5d, val_prob_5d)
    threshold_10d, metrics_10d = choose_threshold(y_val_10d, val_prob_10d)
    exit_5d = max(0.35, threshold_5d - 0.14)
    exit_10d = max(0.35, threshold_10d - 0.14)
    log(
        "selected thresholds: "
        f"5d_entry={threshold_5d:.2f}, 10d_entry={threshold_10d:.2f}, "
        f"5d_exit={exit_5d:.2f}, 10d_exit={exit_10d:.2f}"
    )
    log(
        "validation metrics: "
        f"5d_f1={metrics_5d['f1']:.3f}, 5d_precision={metrics_5d['precision']:.3f}, "
        f"5d_recall={metrics_5d['recall']:.3f}, "
        f"10d_f1={metrics_10d['f1']:.3f}, 10d_precision={metrics_10d['precision']:.3f}, "
        f"10d_recall={metrics_10d['recall']:.3f}"
    )

    model = {
        "strategy_name": "AI ARX Regime",
        "model": "two_horizon_logistic_arx",
        "symbols": list(symbols),
        "timeframe": TIMEFRAME,
        "training_start": TRAIN_START,
        "training_end": "2025-12-31",
        "validation_start": str(val_rows["timestamp"].min().date()),
        "validation_end": str(val_rows["timestamp"].max().date()),
        "feature_columns": FEATURE_COLUMNS,
        "feature_means": means.round(12).tolist(),
        "feature_stds": stds.round(12).tolist(),
        "target_5d_bps": float(args.target_5d_bps),
        "target_10d_bps": float(args.target_10d_bps),
        "model_5d": {
            "weights": weights_5d.round(12).tolist(),
            "bias": float(round(bias_5d, 12)),
            "entry_threshold": float(threshold_5d),
            "exit_threshold": float(exit_5d),
            "validation_metrics": metrics_5d,
        },
        "model_10d": {
            "weights": weights_10d.round(12).tolist(),
            "bias": float(round(bias_10d, 12)),
            "entry_threshold": float(threshold_10d),
            "exit_threshold": float(exit_10d),
            "validation_metrics": metrics_10d,
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_strategy(model), encoding="utf-8")
    log(f"wrote strategy script: {output_path}")

    model_path = Path(args.model_json)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    log(f"wrote model metadata: {model_path}")


if __name__ == "__main__":
    main()
