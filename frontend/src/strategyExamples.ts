import { templateStrategy } from './defaultStrategy';

export interface StrategyExample {
  id: string;
  name: string;
  description: string;
  code: string;
}

export const strategyExamples: StrategyExample[] = [
  {
    id: 'template',
    name: 'Template',
    description: 'Minimal documented starter script for a new strategy.',
    code: templateStrategy,
  },
  {
    id: 'sma-crossover',
    name: 'SMA crossover',
    description: 'Fast/slow simple moving-average trend following.',
    code: `"""
SMA Crossover

This is a classic trend-following strategy. It compares a fast simple moving
average against a slower simple moving average:

- Enter long when the fast average crosses above the slow average.
- Exit when the fast average crosses below the slow average.

The idea is to participate in sustained upward trends while avoiding periods
where price momentum is weaker. This type of strategy usually works better in
trending markets and can suffer during sideways/choppy markets.

Trading Lab contract:
- Define def run(ctx).
- Return entries and exits as boolean arrays/Series aligned to ctx.candles.
- Optional markers are drawn on the chart.
- Optional debug is saved with the backtest result.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "SMA crossover"
VERSION = "1.0"
DESCRIPTION = "Long-only moving average crossover with optional news-risk markers."


def crossover_up(fast: pd.Series, slow: pd.Series) -> pd.Series:
    # A crossover happens only on the bar where the relationship changes.
    # This avoids buying every bar where fast is already above slow.
    return (fast > slow) & (fast.shift(1) <= slow.shift(1))


def crossover_down(fast: pd.Series, slow: pd.Series) -> pd.Series:
    # Symmetric exit signal: fast average loses momentum versus slow average.
    return (fast < slow) & (fast.shift(1) >= slow.shift(1))


def run(ctx):
    # ctx.candles is a pandas DataFrame with the loaded candles:
    # timestamp, open, high, low, close, volume, symbol, timeframe, source.
    candles = ctx.candles.copy()

    # Use each candle close to calculate the signals.
    close = candles["close"]

    # Fast and slow moving averages.
    # In 5Min, 10 candles = 50 minutes and 25 candles = 125 minutes.
    # In 1Day, they are 10 and 25 trading days.
    fast = close.rolling(10).mean()
    slow = close.rolling(25).mean()

    # Buy when the fast average crosses above the slow average.
    entries = crossover_up(fast, slow)

    # Sell when the fast average crosses below the slow average.
    # The engine can also close through Stop % or Take % from the UI.
    exits = crossover_down(fast, slow)

    markers = []

    # Example: if there is strong negative news sentiment, draw an
    # informational marker at the end of the series.
    if len(getattr(ctx, "sentiment", [])) > 0:
        recent_negative = ctx.sentiment[
            (ctx.sentiment["label"] == "negative") & (ctx.sentiment["score"] > 0.55)
        ]
        if len(recent_negative) > 0:
            markers.append({
                "timestamp": candles["timestamp"].iloc[-1],
                "type": "news",
                "label": "News risk",
                "color": "#d64545",
            })

    return {
        "entries": entries,
        "exits": exits,
        "markers": markers,
        "debug": {
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "bars": int(len(candles)),
            "entry_count": int(np.asarray(entries.fillna(False)).sum()),
            "exit_count": int(np.asarray(exits.fillna(False)).sum()),
        },
    }
`,
  },
  {
    id: 'ema-crossover',
    name: 'EMA crossover',
    description: 'Fast/slow exponential moving-average trend following.',
    code: `"""
EMA Crossover

This is a trend-following strategy similar to an SMA crossover, but it uses
exponential moving averages. EMAs react faster to recent price changes because
newer candles receive more weight.

- Enter long when the fast EMA crosses above the slow EMA.
- Exit when the fast EMA crosses below the slow EMA.

Common interpretation:
- 12/26 EMA is a popular short/medium momentum pair.
- Faster reaction can help catch moves earlier.
- The tradeoff is more false signals in noisy markets.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "EMA crossover"
VERSION = "1.0"


def crossed_above(fast: pd.Series, slow: pd.Series) -> pd.Series:
    # Detect only the transition bar, not every bar where fast > slow.
    return (fast > slow) & (fast.shift(1) <= slow.shift(1))


def crossed_below(fast: pd.Series, slow: pd.Series) -> pd.Series:
    # Exit when momentum weakens and the fast EMA falls below the slow EMA.
    return (fast < slow) & (fast.shift(1) >= slow.shift(1))


def run(ctx):
    # ctx.candles is indexed by timestamp and includes OHLCV data.
    candles = ctx.candles.copy()
    close = candles["close"]

    # EMAs respond faster than simple moving averages.
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()

    entries = crossed_above(fast, slow)
    exits = crossed_below(fast, slow)

    return {
        "entries": entries,
        "exits": exits,
        "markers": [],
        "debug": {
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "entry_count": int(np.asarray(entries.fillna(False)).sum()),
            "exit_count": int(np.asarray(exits.fillna(False)).sum()),
        },
    }
`,
  },
  {
    id: 'rsi-mean-reversion',
    name: 'RSI mean reversion',
    description: 'Buys oversold RSI and exits after RSI normalizes.',
    code: `"""
RSI Mean Reversion

RSI estimates whether price has moved too far too quickly. This example buys
when RSI is oversold and exits when RSI returns to a more neutral zone.

- Enter long when RSI < 30.
- Exit when RSI > 50.

Common interpretation:
- RSI below 30 often means short-term selling pressure is stretched.
- This is a mean-reversion idea, not a trend-following idea.
- It can work poorly during strong downtrends because "oversold" can stay
  oversold for a long time.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "RSI mean reversion"
VERSION = "1.0"


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    # Split price changes into gains and losses.
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()

    # Replace zero losses to avoid division by zero.
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def run(ctx):
    candles = ctx.candles.copy()
    close = candles["close"]
    indicator = rsi(close, 14)

    entries = indicator < 30
    exits = indicator > 50

    return {
        "entries": entries,
        "exits": exits,
        "markers": [],
        "debug": {
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "latest_rsi": None if indicator.dropna().empty else float(indicator.dropna().iloc[-1]),
            "entry_count": int(np.asarray(entries.fillna(False)).sum()),
        },
    }
`,
  },
  {
    id: 'bollinger-mean-reversion',
    name: 'Bollinger mean reversion',
    description: 'Buys below the lower band and exits near the midline.',
    code: `"""
Bollinger Band Mean Reversion

Bollinger Bands compare price against a rolling average plus/minus a multiple
of recent volatility. This example assumes that a move below the lower band is
temporarily stretched and may revert toward the moving average.

- Enter long when close < lower Bollinger Band.
- Exit when close > middle band.

Common interpretation:
- Good for testing pullback/reversion behavior.
- Can perform badly during sharp selloffs, where price keeps walking down the
  lower band.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "Bollinger mean reversion"
VERSION = "1.0"


def run(ctx):
    candles = ctx.candles.copy()
    close = candles["close"]

    window = 20
    middle = close.rolling(window).mean()
    volatility = close.rolling(window).std()
    lower = middle - (2 * volatility)

    entries = close < lower
    exits = close > middle

    return {
        "entries": entries,
        "exits": exits,
        "markers": [],
        "debug": {
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "window": window,
            "entry_count": int(np.asarray(entries.fillna(False)).sum()),
        },
    }
`,
  },
  {
    id: 'macd-momentum',
    name: 'MACD momentum',
    description: 'Uses MACD line/signal crossovers for momentum entries.',
    code: `"""
MACD Momentum

MACD is the difference between a fast EMA and a slow EMA. It attempts to measure
momentum. A signal line, usually a 9-period EMA of MACD, is used to detect
momentum turns.

- Enter long when MACD crosses above its signal line.
- Exit when MACD crosses below its signal line.

Common interpretation:
- Positive crossovers suggest improving bullish momentum.
- Signals can lag because they are based on moving averages.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "MACD momentum"
VERSION = "1.0"


def run(ctx):
    candles = ctx.candles.copy()
    close = candles["close"]

    # Standard MACD parameters: 12 EMA, 26 EMA, 9 EMA signal.
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd = ema_12 - ema_26
    signal = macd.ewm(span=9, adjust=False).mean()

    entries = (macd > signal) & (macd.shift(1) <= signal.shift(1))
    exits = (macd < signal) & (macd.shift(1) >= signal.shift(1))

    return {
        "entries": entries,
        "exits": exits,
        "markers": [],
        "debug": {
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "latest_macd": None if macd.dropna().empty else float(macd.dropna().iloc[-1]),
            "entry_count": int(np.asarray(entries.fillna(False)).sum()),
        },
    }
`,
  },
  {
    id: 'donchian-breakout',
    name: 'Donchian breakout',
    description: 'Trend breakout above recent highs, exits on downside channel break.',
    code: `"""
Donchian Breakout

Donchian channels track the highest high and lowest low over a lookback window.
This strategy buys strength when price breaks above the previous channel high
and exits when price breaks below a shorter downside channel.

- Enter long when close > prior 20-bar high.
- Exit when close < prior 10-bar low.

Common interpretation:
- This is a breakout/trend-following strategy.
- It often has many small losses and depends on occasional large trends.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "Donchian breakout"
VERSION = "1.0"


def run(ctx):
    candles = ctx.candles.copy()
    high = candles["high"]
    low = candles["low"]
    close = candles["close"]

    entry_window = 20
    exit_window = 10

    # shift(1) prevents look-ahead bias: today's signal only uses prior bars.
    upper = high.rolling(entry_window).max().shift(1)
    lower = low.rolling(exit_window).min().shift(1)

    entries = close > upper
    exits = close < lower

    return {
        "entries": entries,
        "exits": exits,
        "markers": [],
        "debug": {
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "entry_window": entry_window,
            "exit_window": exit_window,
            "entry_count": int(np.asarray(entries.fillna(False)).sum()),
        },
    }
`,
  },
  {
    id: 'sentiment-filtered-sma',
    name: 'Sentiment filtered SMA',
    description: 'SMA crossover that avoids entries when recent news sentiment is negative.',
    code: `"""
Sentiment-Filtered SMA Crossover

This strategy starts with a standard SMA crossover but adds a news-aware filter.
If there is strong negative sentiment available at the signal timestamp, the
entry is blocked and a yellow marker is added to the chart.

- Base entry: fast SMA crosses above slow SMA.
- Base exit: fast SMA crosses below slow SMA.
- Filter: block entries when recent available sentiment is negative.

Important:
- ctx.sentiment_until(timestamp) only returns sentiment tied to news available
  up to that timestamp, which helps avoid look-ahead bias.
- Sentiment filtering can reduce bad entries, but it can also skip profitable
  trades if the news signal is noisy.
"""

import numpy as np
import pandas as pd


STRATEGY_NAME = "Sentiment filtered SMA"
VERSION = "1.0"


def recent_negative_sentiment(ctx, timestamp, score_threshold: float = 0.55) -> bool:
    # Use only sentiment that would have been available at this candle.
    sentiment = ctx.sentiment_until(timestamp)
    if not hasattr(sentiment, "empty") or sentiment.empty:
        return False

    recent = sentiment[
        (sentiment["label"] == "negative") &
        (sentiment["score"] >= score_threshold)
    ]
    return len(recent) > 0


def run(ctx):
    candles = ctx.candles.copy()
    close = candles["close"]

    fast = close.rolling(10).mean()
    slow = close.rolling(25).mean()
    raw_entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))

    entries = raw_entries.copy()
    markers = []
    blocked_count = 0

    # Review each raw entry and block it when negative news risk is present.
    for index, row in candles.iterrows():
        if not bool(raw_entries.loc[index]):
            continue

        if recent_negative_sentiment(ctx, row["timestamp"]):
            entries.loc[index] = False
            blocked_count += 1
            markers.append({
                "timestamp": row["timestamp"],
                "type": "news",
                "label": "Blocked by news",
                "color": "#d6a419",
            })

    return {
        "entries": entries,
        "exits": exits,
        "markers": markers,
        "debug": {
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "raw_entries": int(np.asarray(raw_entries.fillna(False)).sum()),
            "blocked_by_news": blocked_count,
            "final_entries": int(np.asarray(entries.fillna(False)).sum()),
        },
    }
`,
  },
];
