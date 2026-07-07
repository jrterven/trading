from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export an OHLCV + news sentiment training dataset from Trading Lab DuckDB."
    )
    parser.add_argument("--db", default="data/trading.duckdb", help="Path to DuckDB database.")
    parser.add_argument("--symbol", default="AAPL", help="Ticker symbol to export.")
    parser.add_argument("--timeframe", default="1Day", help="Bar timeframe, e.g. 1Day or 1Hour.")
    parser.add_argument("--start", default=None, help="Optional inclusive start timestamp/date.")
    parser.add_argument("--end", default=None, help="Optional inclusive end timestamp/date.")
    parser.add_argument(
        "--lookback-bars",
        type=int,
        default=5,
        help="Rolling window size for trailing news/sentiment features.",
    )
    parser.add_argument(
        "--output",
        default="data/training_dataset.csv",
        help="Output path ending in .csv or .parquet.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    output_path = Path(args.output)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        bars = load_bars(con, args.symbol, args.timeframe, args.start, args.end)
        news = load_daily_news_features(con, args.symbol, args.start, args.end)
    finally:
        con.close()

    if bars.empty:
        raise SystemExit("No bars found for the requested symbol/timeframe/range.")

    dataset = build_dataset(bars, news, args.lookback_bars)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".parquet":
        dataset.to_parquet(output_path, index=False)
    else:
        dataset.to_csv(output_path, index=False)
    print(f"Exported {len(dataset):,} rows to {output_path}")


def load_bars(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    clauses = ["symbol = ?", "timeframe = ?"]
    params: list[object] = [symbol.upper(), timeframe]
    if start:
        clauses.append("timestamp >= ?")
        params.append(start)
    if end:
        clauses.append("timestamp <= ?")
        params.append(end)
    return con.execute(
        f"""
        SELECT symbol, timeframe, timestamp, open, high, low, close, volume, source
        FROM bars
        WHERE {' AND '.join(clauses)}
        ORDER BY timestamp
        """,
        params,
    ).fetchdf()


def load_daily_news_features(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    clauses = ["nas.symbol = ?"]
    params: list[object] = [symbol.upper()]
    if start:
        clauses.append("na.available_at >= ?")
        params.append(start)
    if end:
        clauses.append("na.available_at <= ?")
        params.append(end)
    return con.execute(
        f"""
        SELECT
            CAST(COALESCE(na.available_at, na.published_at) AS DATE) AS feature_date,
            COUNT(*) AS news_count,
            SUM(CASE WHEN nas.relation_type = 'direct' THEN 1 ELSE 0 END) AS direct_news_count,
            SUM(CASE WHEN nas.relation_type = 'indirect' THEN 1 ELSE 0 END) AS indirect_news_count,
            AVG(COALESCE(ss.positive, 0)) AS avg_positive,
            AVG(COALESCE(ss.neutral, 0)) AS avg_neutral,
            AVG(COALESCE(ss.negative, 0)) AS avg_negative,
            AVG(
                CASE
                    WHEN ss.label = 'positive' THEN ss.score
                    WHEN ss.label = 'negative' THEN -ss.score
                    ELSE 0
                END
            ) AS avg_signed_sentiment
        FROM news_articles na
        JOIN news_article_symbols nas ON nas.article_id = na.id
        LEFT JOIN sentiment_scores ss
          ON ss.article_id = na.id
         AND ss.symbol = nas.symbol
        WHERE {' AND '.join(clauses)}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    ).fetchdf()


def build_dataset(bars: pd.DataFrame, news: pd.DataFrame, lookback_bars: int) -> pd.DataFrame:
    dataset = bars.copy()
    dataset["timestamp"] = pd.to_datetime(dataset["timestamp"])
    dataset["feature_date"] = dataset["timestamp"].dt.date

    if news.empty:
        news = pd.DataFrame(
            columns=[
                "feature_date",
                "news_count",
                "direct_news_count",
                "indirect_news_count",
                "avg_positive",
                "avg_neutral",
                "avg_negative",
                "avg_signed_sentiment",
            ]
        )
    else:
        news = news.copy()
        news["feature_date"] = pd.to_datetime(news["feature_date"]).dt.date

    dataset = dataset.merge(news, on="feature_date", how="left")
    feature_columns = [
        "news_count",
        "direct_news_count",
        "indirect_news_count",
        "avg_positive",
        "avg_neutral",
        "avg_negative",
        "avg_signed_sentiment",
    ]
    dataset[feature_columns] = dataset[feature_columns].fillna(0)

    rolling_columns = ["news_count", "avg_signed_sentiment", "avg_positive", "avg_negative"]
    for column in rolling_columns:
        dataset[f"{column}_roll_{lookback_bars}"] = (
            dataset[column].rolling(lookback_bars, min_periods=1).mean()
        )

    dataset["return_1"] = dataset["close"].pct_change()
    dataset["future_return_1"] = dataset["close"].shift(-1) / dataset["close"] - 1
    return dataset.drop(columns=["feature_date"])


if __name__ == "__main__":
    main()
