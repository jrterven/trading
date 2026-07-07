# Trading Lab

Local web platform for researching trading strategies on US stocks/ETFs with candlestick data, company news, sentiment analysis, Python strategy code, and backtesting.

## Stack

- Backend: FastAPI, DuckDB, pandas/numpy, Alpaca market data and trading APIs.
- Frontend: React, TypeScript, Vite, Lightweight Charts, Monaco Editor.
- Local AI: optional FinBERT with `pip install -e ".[ai]"`; optional Ollama for news summaries.
- Backtesting: local long-only signal engine using `entries/exits`, executed in a subprocess with a timeout.
- Paper trading: Alpaca Paper Trading API. Backtests do not place paper or live orders.

## Setup

```bash
cp .env.example .env
conda env create -f environment.yml
conda activate trading-lab
npm install
```

For local FinBERT:

```bash
conda activate trading-lab
pip install -e ".[ai]"
```

For Ollama:

```bash
ollama pull gpt-oss:20b
```

## Run

Recommended:

```bash
./scripts/start_services.sh
```

Open `http://127.0.0.1:5173`.

To stop the backend and frontend:

```bash
./scripts/stop_services.sh
```

The scripts default to `CONDA_ENV=trading-lab`, backend port `8001`, and frontend port `5173`.
You can override them like this:

```bash
BACKEND_PORT=8002 FRONTEND_PORT=5174 ./scripts/start_services.sh
```

Manual mode, terminal 1:

```bash
conda activate trading-lab
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8001
```

Terminal 2:

```bash
conda activate trading-lab
VITE_API_URL=http://127.0.0.1:8001 VITE_WS_URL=ws://127.0.0.1:8001 npm run dev -- --host 127.0.0.1 --port 5173
```

If the backend runs on a different port:

```bash
VITE_API_URL=http://127.0.0.1:8001 VITE_WS_URL=ws://127.0.0.1:8001 npm run dev
```

The app uses Alpaca data only. Without `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`, market/news endpoints do not generate mock data.

## Local Database

Trading Lab stores OHLCV, news, sentiment, backtests, and dataset coverage in DuckDB. For external analysis or ML training, see [docs/DATABASE_USAGE.md](docs/DATABASE_USAGE.md).

## Strategy Contract

The editor expects a `run(ctx)` function:

```python
def run(ctx):
    candles = ctx.candles
    close = candles["close"]
    fast = close.rolling(10).mean()
    slow = close.rolling(25).mean()

    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))

    return {"entries": entries, "exits": exits, "markers": []}
```

`ctx.candles` is a DataFrame with `timestamp`, `open`, `high`, `low`, `close`, and `volume`.
`ctx.news` contains news articles, and `ctx.sentiment` is a DataFrame with article-level sentiment scores.

## Tests

```bash
conda activate trading-lab
pytest
npm test
npm run build
```

To update the environment after changes to `environment.yml`:

```bash
conda env update -f environment.yml --prune
```
