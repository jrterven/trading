export const templateStrategy = `"""
Trading Lab Strategy Template

Use this file as a starting point for a new strategy.

Required contract:
- Define def run(ctx).
- Return a dictionary with entries and exits.
- entries and exits must be boolean arrays or pandas Series aligned to ctx.candles.

Available context:
- ctx.symbol: selected ticker, for example "AAPL".
- ctx.timeframe: selected timeframe, for example "1Day" or "5Min".
- ctx.candles: pandas DataFrame with timestamp, open, high, low, close, volume,
  symbol, timeframe, and source.
- ctx.news: pandas DataFrame with news available for the selected symbol/range.
- ctx.sentiment: pandas DataFrame with sentiment scores for those news articles.
- ctx.news_until(timestamp): news available up to a candle timestamp.
- ctx.sentiment_until(timestamp): sentiment available up to a candle timestamp.

Optional return fields:
- markers: list of dictionaries drawn on the chart.
- debug: any JSON-serializable object saved with the backtest result.

Notes:
- The backtest engine handles capital, position size, commission, stop loss,
  and take profit from the UI.
- Avoid look-ahead bias. Do not use future candles/news to decide past entries.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "New strategy"
VERSION = "0.1"


def run(ctx):
    candles = ctx.candles.copy()
    close = candles["close"]

    # TODO: Replace this with your own indicator logic.
    # This placeholder does not open trades.
    entries = pd.Series(False, index=candles.index)
    exits = pd.Series(False, index=candles.index)

    # Optional chart annotations. Example marker shape:
    # markers.append({
    #     "timestamp": candles["timestamp"].iloc[-1],
    #     "type": "note",
    #     "label": "My marker",
    #     "color": "#0f766e",
    # })
    markers = []

    return {
        "entries": entries,
        "exits": exits,
        "markers": markers,
        "debug": {
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "bars": int(len(candles)),
            "latest_close": None if close.empty else float(close.iloc[-1]),
            "entry_count": int(np.asarray(entries.fillna(False)).sum()),
            "exit_count": int(np.asarray(exits.fillna(False)).sum()),
        },
    }
`;

export const defaultStrategy = templateStrategy;
