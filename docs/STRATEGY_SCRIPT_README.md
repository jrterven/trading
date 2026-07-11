# Trading Lab Strategy Script Contract

Trading Lab runs strategies as complete Python scripts. A script can include imports, constants, metadata, helper functions, classes, and debug prints. The required entrypoint is still:

```python
def run(ctx):
    ...
```

The backtest engine imports the script in an isolated subprocess, builds `ctx`, calls `run(ctx)`, and reads the returned dictionary.

## Required Structure

A valid strategy file should follow this shape:

```python
import numpy as np
import pandas as pd


STRATEGY_NAME = "My strategy"
VERSION = "0.1"
DESCRIPTION = "Short human-readable description."


def helper_function(candles: pd.DataFrame) -> pd.Series:
    ...


def run(ctx):
    candles = ctx.candles.copy()

    entries = ...
    exits = ...

    return {
        "entries": entries,
        "exits": exits,
        "markers": [],
        "debug": {},
    }
```

Only `run(ctx)` is required. Everything else is optional.

## Available Context

Inside `run(ctx)`, the platform provides:

- `ctx.symbol`: selected ticker, for example `"AAPL"`.
- `ctx.timeframe`: selected timeframe, for example `"1Day"` or `"5Min"`.
- `ctx.candles`: pandas DataFrame with `timestamp`, `open`, `high`, `low`, `close`, `volume`, `symbol`, `timeframe`, and `source`.
- `ctx.news`: pandas DataFrame with news available for the selected symbol and range.
- `ctx.sentiment`: pandas DataFrame with sentiment scores for the selected news.
- `ctx.news_until(timestamp)`: news available up to a candle timestamp.
- `ctx.sentiment_until(timestamp)`: sentiment available up to a candle timestamp.

Use `ctx.news_until(...)` and `ctx.sentiment_until(...)` when making candle-by-candle decisions to avoid look-ahead bias.

## Required Return Values

`run(ctx)` must return a dictionary with:

- `entries`: boolean pandas Series, list, NumPy array, or compatible array aligned to `ctx.candles`.
- `exits`: boolean pandas Series, list, NumPy array, or compatible array aligned to `ctx.candles`.

Optional return fields:

- `markers`: list of chart marker dictionaries.
- `debug`: JSON-serializable object stored with the backtest result.

The UI controls capital, position size, stop loss, take profit, commission, and timeout. Do not hard-code those unless the strategy is intentionally doing its own research calculation.

## Logs And Debugging

You can use `print()` inside the script. Standard output and standard error are captured with the backtest result.

Use `debug` for structured values that should be saved:

```python
return {
    "entries": entries,
    "exits": exits,
    "debug": {
        "entry_count": int(entries.sum()),
        "latest_close": float(close.iloc[-1]),
    },
}
```

## Example Strategy

This is the platform template strategy. It is intentionally minimal and does not open trades until you replace the TODO logic.

```python
"""
Trading Lab Strategy Template

Use this file as a starting point for a new strategy.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "New strategy"
VERSION = "0.1"
DESCRIPTION = "Minimal empty strategy template."


def run(ctx):
    candles = ctx.candles.copy()
    close = candles["close"]

    # Replace this block with your own signal logic.
    # entries/exits must stay aligned to candles.index.
    entries = pd.Series(False, index=candles.index)
    exits = pd.Series(False, index=candles.index)

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
```

## Loading External Files

In the Strategy tab, use the upload button to load a local `.py` file into the editor. Loading a file only changes the editor content in your browser. It does not save the strategy or run a backtest until you click Save or Backtest.

Only `.py` files are accepted.

## Practical Rules

- Keep `entries` and `exits` the same length and order as `ctx.candles`.
- Avoid future data: do not use future candles, news, or sentiment to decide past entries.
- Prefer pandas or NumPy vectorized operations for speed.
- Return plain JSON-compatible values inside `debug`.
- Use the Strategy tab runtime panel to check which Python executable, packages, CUDA status, and timeout are active.
- Backtests do not place Alpaca orders. Paper/live orders are handled separately.
