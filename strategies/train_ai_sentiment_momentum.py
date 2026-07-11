from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


SYMBOLS = ("AAPL", "GOOGL", "TSLA")
TIMEFRAME = "1Day"
TRAIN_START = "2025-01-01"
TRAIN_END = "2026-01-01"
NEWS_LOOKBACK_DAYS = 7
TARGET_RETURN_BPS = 20.0
FEATURE_COLUMNS = [
    "return_1",
    "return_3",
    "return_5",
    "return_10",
    "sma_5_gap",
    "sma_10_gap",
    "sma_20_gap",
    "volatility_5",
    "volatility_10",
    "range_pct",
    "volume_ratio_5",
    "volume_ratio_20",
    "momentum_5",
    "rsi_14",
    "news_count",
    "direct_news_count",
    "avg_positive",
    "avg_negative",
    "avg_signed_sentiment",
    "sentiment_intensity",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the AI Sentiment Momentum strategy on 2025 Trading Lab data."
    )
    parser.add_argument("--db", default="data/trading.duckdb", help="Path to the DuckDB file.")
    parser.add_argument(
        "--output",
        default="strategies/ai_sentiment_momentum.py",
        help="Strategy file to write with embedded model weights.",
    )
    parser.add_argument(
        "--model-json",
        default="strategies/ai_sentiment_momentum_model.json",
        help="Metadata/model JSON output path.",
    )
    parser.add_argument("--epochs", type=int, default=900, help="Training epochs.")
    parser.add_argument("--learning-rate", type=float, default=0.035, help="Gradient step size.")
    parser.add_argument("--l2", type=float, default=0.015, help="L2 regularization strength.")
    parser.add_argument(
        "--log-every",
        type=int,
        default=50,
        help="Print training metrics every N epochs.",
    )
    parser.add_argument(
        "--target-return-bps",
        type=float,
        default=TARGET_RETURN_BPS,
        help="Positive label threshold for next-bar return, in basis points.",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(f"[train-ai-sentiment] {message}", flush=True)


def load_bars(
    con: duckdb.DuckDBPyConnection,
    symbols: tuple[str, ...],
    timeframe: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    placeholders = ", ".join(["?"] * len(symbols))
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
        [*symbols, timeframe, start, end],
    ).fetchdf()
    rows["timestamp"] = pd.to_datetime(rows["timestamp"], utc=True)
    return rows


def load_news_sentiment(
    con: duckdb.DuckDBPyConnection,
    symbols: tuple[str, ...],
    start: str,
    end: str,
    lookback_days: int,
) -> pd.DataFrame:
    placeholders = ", ".join(["?"] * len(symbols))
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
        [
            *symbols,
            str(pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=lookback_days)),
            end,
        ],
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


def add_news_features(
    candles: pd.DataFrame,
    news: pd.DataFrame,
    lookback_days: int,
) -> pd.DataFrame:
    enriched_parts: list[pd.DataFrame] = []
    for symbol, symbol_candles in candles.groupby("symbol", sort=False):
        symbol_candles = symbol_candles.sort_values("timestamp").copy()
        symbol_news = news[news["symbol"] == symbol].copy()
        if not symbol_news.empty:
            symbol_news["signed_sentiment"] = signed_sentiment(symbol_news)

        rows: list[dict[str, float]] = []
        for timestamp in symbol_candles["timestamp"]:
            cutoff = pd.Timestamp(timestamp)
            start = cutoff - pd.Timedelta(days=lookback_days)
            if symbol_news.empty:
                window = symbol_news
            else:
                window = symbol_news[
                    (symbol_news["available_at"] <= cutoff) & (symbol_news["available_at"] > start)
                ]
            if window.empty:
                rows.append(
                    {
                        "news_count": 0.0,
                        "direct_news_count": 0.0,
                        "avg_positive": 0.0,
                        "avg_negative": 0.0,
                        "avg_signed_sentiment": 0.0,
                        "sentiment_intensity": 0.0,
                    }
                )
                continue
            rows.append(
                {
                    "news_count": float(len(window)),
                    "direct_news_count": float(window["relation_type"].eq("direct").sum()),
                    "avg_positive": float(window["positive"].astype(float).mean()),
                    "avg_negative": float(window["negative"].astype(float).mean()),
                    "avg_signed_sentiment": float(window["signed_sentiment"].mean()),
                    "sentiment_intensity": float(window["signed_sentiment"].abs().mean()),
                }
            )
        news_features = pd.DataFrame(rows, index=symbol_candles.index)
        enriched_parts.append(pd.concat([symbol_candles, news_features], axis=1))
    return pd.concat(enriched_parts).sort_values(["symbol", "timestamp"])


def calculate_features(candles: pd.DataFrame, news: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for _, symbol_candles in candles.groupby("symbol", sort=False):
        df = symbol_candles.sort_values("timestamp").copy()
        close = df["close"].astype(float)
        volume = df["volume"].astype(float).replace(0, np.nan)
        returns = close.pct_change()

        df["return_1"] = returns
        df["return_3"] = close / close.shift(3) - 1.0
        df["return_5"] = close / close.shift(5) - 1.0
        df["return_10"] = close / close.shift(10) - 1.0
        df["sma_5_gap"] = close / close.rolling(5, min_periods=2).mean() - 1.0
        df["sma_10_gap"] = close / close.rolling(10, min_periods=3).mean() - 1.0
        df["sma_20_gap"] = close / close.rolling(20, min_periods=5).mean() - 1.0
        df["volatility_5"] = returns.rolling(5, min_periods=3).std()
        df["volatility_10"] = returns.rolling(10, min_periods=5).std()
        df["range_pct"] = (df["high"].astype(float) - df["low"].astype(float)) / close
        df["volume_ratio_5"] = volume / volume.rolling(5, min_periods=2).mean() - 1.0
        df["volume_ratio_20"] = volume / volume.rolling(20, min_periods=5).mean() - 1.0
        df["momentum_5"] = returns.rolling(5, min_periods=3).mean()

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0) / 100.0
        df["future_return_1"] = close.shift(-1) / close - 1.0
        parts.append(df)

    featured = pd.concat(parts).sort_values(["symbol", "timestamp"])
    featured = add_news_features(featured, news, lookback_days)
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
        "class balance: "
        f"positive_rate={positive_rate:.3f}, pos_weight={pos_weight:.3f}, "
        f"neg_weight={neg_weight:.3f}"
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
                "epoch "
                f"{epoch:04d}/{epochs} "
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
    for threshold in np.arange(0.45, 0.76, 0.01):
        metrics = binary_metrics(y_val, probabilities, float(threshold))
        score = metrics["f1"] - max(0.0, metrics["signal_rate"] - 0.35) * 0.25
        if metrics["signal_rate"] < 0.03:
            score -= 0.20
        if score > best_score:
            best_score = score
            best_threshold = float(threshold)
            best_metrics = metrics
    return round(best_threshold, 2), best_metrics


def render_strategy(model: dict[str, object]) -> str:
    return f'''"""
AI Sentiment Momentum

Generated by strategies/train_ai_sentiment_momentum.py.
The model is a small logistic-regression classifier trained on 2025 daily data
for AAPL, GOOGL, and TSLA.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "AI Sentiment Momentum"
VERSION = "0.1"
DESCRIPTION = "Long-only AI strategy using price momentum, volatility, volume, and trailing news sentiment."
FEATURE_COLUMNS = {json.dumps(FEATURE_COLUMNS, indent=4)}
FEATURE_MEANS = np.array({json.dumps(model["feature_means"])}, dtype=float)
FEATURE_STDS = np.array({json.dumps(model["feature_stds"])}, dtype=float)
MODEL_WEIGHTS = np.array({json.dumps(model["weights"])}, dtype=float)
MODEL_BIAS = {model["bias"]:.12f}
ENTRY_THRESHOLD = {model["entry_threshold"]:.4f}
EXIT_THRESHOLD = {model["exit_threshold"]:.4f}
NEWS_LOOKBACK_DAYS = {model["news_lookback_days"]}
TARGET_RETURN_BPS = {model["target_return_bps"]:.2f}


def _signed_sentiment(sentiment):
    labels = sentiment["label"].fillna("neutral")
    scores = sentiment["score"].fillna(0.0).astype(float)
    return np.select(
        [labels.eq("positive"), labels.eq("negative")],
        [scores, -scores],
        default=0.0,
    )


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
        start = cutoff - pd.Timedelta(days=NEWS_LOOKBACK_DAYS)
        if news.empty or "available_at" not in news:
            window_news = news.iloc[0:0]
        else:
            window_news = news[
                (news["available_at"] <= cutoff) & (news["available_at"] > start)
            ]
        if window_news.empty:
            rows.append({{
                "news_count": 0.0,
                "direct_news_count": 0.0,
                "avg_positive": 0.0,
                "avg_negative": 0.0,
                "avg_signed_sentiment": 0.0,
                "sentiment_intensity": 0.0,
            }})
            continue
        article_ids = set(window_news["id"].dropna().tolist())
        window_sentiment = sentiment[sentiment["article_id"].isin(article_ids)]
        if window_sentiment.empty:
            rows.append({{
                "news_count": float(len(window_news)),
                "direct_news_count": float(window_news["relation_type"].eq("direct").sum()),
                "avg_positive": 0.0,
                "avg_negative": 0.0,
                "avg_signed_sentiment": 0.0,
                "sentiment_intensity": 0.0,
            }})
            continue
        rows.append({{
            "news_count": float(len(window_news)),
            "direct_news_count": float(window_news["relation_type"].eq("direct").sum()),
            "avg_positive": float(window_sentiment["positive"].astype(float).mean()),
            "avg_negative": float(window_sentiment["negative"].astype(float).mean()),
            "avg_signed_sentiment": float(window_sentiment["signed_sentiment"].mean()),
            "sentiment_intensity": float(window_sentiment["signed_sentiment"].abs().mean()),
        }})
    return pd.DataFrame(rows, index=candles.index)


def _calculate_features(candles, news, sentiment):
    df = candles.copy()
    df["_strategy_timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("_strategy_timestamp")
    df["timestamp"] = df["_strategy_timestamp"]
    close = df["close"].astype(float)
    volume = df["volume"].astype(float).replace(0, np.nan)
    returns = close.pct_change()

    features = pd.DataFrame(index=df.index)
    features["return_1"] = returns
    features["return_3"] = close / close.shift(3) - 1.0
    features["return_5"] = close / close.shift(5) - 1.0
    features["return_10"] = close / close.shift(10) - 1.0
    features["sma_5_gap"] = close / close.rolling(5, min_periods=2).mean() - 1.0
    features["sma_10_gap"] = close / close.rolling(10, min_periods=3).mean() - 1.0
    features["sma_20_gap"] = close / close.rolling(20, min_periods=5).mean() - 1.0
    features["volatility_5"] = returns.rolling(5, min_periods=3).std()
    features["volatility_10"] = returns.rolling(10, min_periods=5).std()
    features["range_pct"] = (df["high"].astype(float) - df["low"].astype(float)) / close
    features["volume_ratio_5"] = volume / volume.rolling(5, min_periods=2).mean() - 1.0
    features["volume_ratio_20"] = volume / volume.rolling(20, min_periods=5).mean() - 1.0
    features["momentum_5"] = returns.rolling(5, min_periods=3).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
    rs = gain / loss.replace(0, np.nan)
    features["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0) / 100.0

    features = pd.concat([features, _news_features(df, news, sentiment)], axis=1)
    return features[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _sigmoid(values):
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def run(ctx):
    candles = ctx.candles.copy()
    if candles.empty:
        return {{"entries": [], "exits": [], "markers": [], "debug": {{"reason": "no candles"}}}}

    features = _calculate_features(candles, ctx.news, ctx.sentiment)
    x_values = ((features.values - FEATURE_MEANS) / FEATURE_STDS).astype(float)
    probabilities = pd.Series(
        _sigmoid(x_values @ MODEL_WEIGHTS + MODEL_BIAS),
        index=candles.index,
        name="ai_probability",
    )

    trend_filter = features["sma_5_gap"] > -0.015
    volatility_filter = features["volatility_10"] < 0.055
    entries = (probabilities >= ENTRY_THRESHOLD) & trend_filter & volatility_filter
    exits = (probabilities <= EXIT_THRESHOLD) | (features["return_3"] < -0.035)

    entries = entries.fillna(False)
    exits = exits.fillna(False)
    if len(entries):
        entries.iloc[:20] = False

    markers = []
    high_confidence = probabilities[probabilities >= max(ENTRY_THRESHOLD + 0.08, 0.65)]
    for timestamp, probability in high_confidence.tail(8).items():
        markers.append({{
            "timestamp": timestamp,
            "type": "signal",
            "label": f"AI {{probability:.0%}}",
            "color": "#2563eb",
        }})

    return {{
        "entries": entries,
        "exits": exits,
        "markers": markers,
        "debug": {{
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "model": "logistic_regression_numpy",
            "trained_symbols": {json.dumps(model["symbols"])},
            "training_start": "{model["training_start"]}",
            "training_end": "{model["training_end"]}",
            "target_return_bps": TARGET_RETURN_BPS,
            "entry_threshold": ENTRY_THRESHOLD,
            "exit_threshold": EXIT_THRESHOLD,
            "bars": int(len(candles)),
            "entry_count": int(entries.sum()),
            "exit_count": int(exits.sum()),
            "latest_probability": float(probabilities.iloc[-1]),
            "mean_probability": float(probabilities.mean()),
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
        bars = load_bars(con, SYMBOLS, TIMEFRAME, TRAIN_START, TRAIN_END)
        news = load_news_sentiment(con, SYMBOLS, TRAIN_START, TRAIN_END, NEWS_LOOKBACK_DAYS)
    finally:
        con.close()

    if bars.empty:
        raise SystemExit("No bars found for the requested training range.")

    log(
        "loaded "
        f"{len(bars):,} bars and {len(news):,} news/sentiment rows "
        f"for {', '.join(SYMBOLS)}"
    )
    for symbol, count in bars.groupby("symbol").size().items():
        log(f"{symbol}: {count:,} training candles")

    dataset = calculate_features(bars, news, NEWS_LOOKBACK_DAYS)
    target_threshold = args.target_return_bps / 10_000.0
    dataset = dataset.dropna(subset=["future_return_1"]).copy()
    dataset["target"] = (dataset["future_return_1"] > target_threshold).astype(int)

    usable = dataset[dataset["timestamp"] >= pd.Timestamp(TRAIN_START, tz="UTC")].copy()
    usable = usable.sort_values("timestamp")
    split_timestamp = pd.Timestamp("2025-11-01", tz="UTC")
    train_rows = usable[usable["timestamp"] < split_timestamp]
    val_rows = usable[usable["timestamp"] >= split_timestamp]
    if len(train_rows) < 50 or len(val_rows) < 20:
        raise SystemExit("Not enough rows to train and validate the model.")

    x_train_raw = train_rows[FEATURE_COLUMNS].to_numpy(dtype=float)
    y_train = train_rows["target"].to_numpy(dtype=float)
    x_val_raw = val_rows[FEATURE_COLUMNS].to_numpy(dtype=float)
    y_val = val_rows["target"].to_numpy(dtype=float)

    means = x_train_raw.mean(axis=0)
    stds = x_train_raw.std(axis=0)
    stds = np.where(stds < 1e-8, 1.0, stds)
    x_train = (x_train_raw - means) / stds
    x_val = (x_val_raw - means) / stds

    log(
        "dataset ready: "
        f"train_rows={len(train_rows):,}, val_rows={len(val_rows):,}, "
        f"features={len(FEATURE_COLUMNS)}, target=next_return>{args.target_return_bps:.1f}bps"
    )
    log(
        "validation window: "
        f"{val_rows['timestamp'].min().date()} to {val_rows['timestamp'].max().date()}"
    )

    weights, bias = train_logistic_regression(
        x_train=x_train,
        y_train=y_train,
        x_val=x_val,
        y_val=y_val,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        l2=args.l2,
        log_every=args.log_every,
    )

    val_probabilities = sigmoid(x_val @ weights + bias)
    entry_threshold, threshold_metrics = choose_threshold(y_val, val_probabilities)
    exit_threshold = max(0.35, entry_threshold - 0.12)
    log(
        "selected thresholds: "
        f"entry={entry_threshold:.2f}, exit={exit_threshold:.2f}, "
        f"val_f1={threshold_metrics['f1']:.3f}, "
        f"val_precision={threshold_metrics['precision']:.3f}, "
        f"val_recall={threshold_metrics['recall']:.3f}, "
        f"signal_rate={threshold_metrics['signal_rate']:.3f}"
    )

    model = {
        "strategy_name": "AI Sentiment Momentum",
        "model": "logistic_regression_numpy",
        "symbols": list(SYMBOLS),
        "timeframe": TIMEFRAME,
        "training_start": TRAIN_START,
        "training_end": "2025-12-31",
        "validation_start": str(val_rows["timestamp"].min().date()),
        "validation_end": str(val_rows["timestamp"].max().date()),
        "news_lookback_days": NEWS_LOOKBACK_DAYS,
        "target_return_bps": float(args.target_return_bps),
        "feature_columns": FEATURE_COLUMNS,
        "feature_means": means.round(12).tolist(),
        "feature_stds": stds.round(12).tolist(),
        "weights": weights.round(12).tolist(),
        "bias": float(round(bias, 12)),
        "entry_threshold": float(entry_threshold),
        "exit_threshold": float(exit_threshold),
        "validation_metrics": threshold_metrics,
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
