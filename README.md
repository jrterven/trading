# Trading Lab

Local web platform for researching trading strategies on US stocks/ETFs with candlestick data, company news, sentiment analysis, Python strategy code, and backtesting.

The historical stock/ETF and cryptocurrency datasets are also available as standalone downloads. You can query them with SQL or Python and export them to CSV or Parquet without installing or running Trading Lab.

## Public Datasets

**[Download trading.duckdb and crypto.duckdb from pCloud](https://u.pcloud.link/publink/show?code=kZH4n4JZxvPDaHEN5CmTdmEonWGArQ6XpozX).**

Each file is a self-contained DuckDB database with OHLCV candles (open, high, low, close, volume), news articles, article-to-symbol relationships, precomputed FinBERT sentiment, and download coverage records. Reading the downloaded data requires no Alpaca account, API keys, backend, frontend, or model downloads.

### What is in each file?

Inventory checked on **2026-09-25** against the local files; pCloud reports the same filenames and byte sizes. Counts describe this snapshot, not a live feed. Date ranges below are global first/last dates in UTC, **not a guarantee of complete coverage for every symbol or timeframe**.

| Content | `trading.duckdb` | `crypto.duckdb` |
| --- | --- | --- |
| Market | 38 US stock/ETF symbols, including AAPL, NVDA, SPY, QQQ | 20 USD crypto pairs, including BTC/USD, ETH/USD, SOL/USD |
| File size | 5,466,763,264 bytes (5.09 GiB) | 3,326,357,504 bytes (3.10 GiB) |
| OHLCV candles (`bars`) | 63,214,001 rows | 39,755,471 rows |
| Candle date range | 2017-01-03 to 2026-07-21 | 2021-01-01 to 2026-07-01 |
| Timeframes | `1Min`, `5Min`, `15Min`, `1Hour`, `1Day` | `1Min`, `5Min`, `15Min`, `1Hour`, `1Day` |
| Unique news articles (`news_articles`) | 253,514; 2014-11-07 to 2026-07-01 | 30,595; 2022-01-02 to 2026-07-01 |
| Article-to-symbol links (`news_article_symbols`) | 368,483 | 52,468 |
| Sentiment records (`sentiment_scores`) | 367,878; `ProsusAI/finbert` | 52,468; `ProsusAI/finbert` |
| Download records | 53,495 bar windows; 128,280 news windows | 14,160 bar windows; 1,340 news windows |
| Candle schema differences | Integer `volume` (`BIGINT`) | Fractional `volume` (`DOUBLE`), plus `trade_count` and `vwap` |
| Other tables | Empty app tables: `strategies`, `backtest_runs`, `trades`, `markers`, `paper_orders` | No app tables |

Both datasets were collected through Alpaca. Candle `source` is `alpaca`; news `source` is `alpaca` in the stock file and `benzinga` in the crypto file. News counts are unique articles; links and sentiment are per article/symbol, so one article can contribute multiple records.

Coverage varies substantially: CVX candles end in August 2017, while some crypto pairs only begin in 2026. Stock download logs include failed windows. Use the coverage query/script below before choosing a research period. See the [data guide](docs/DATABASE_USAGE.md) for all symbols, table definitions, joins, and timestamp conventions.

### Download and open the data independently

1. Open the [public pCloud folder](https://u.pcloud.link/publink/show?code=kZH4n4JZxvPDaHEN5CmTdmEonWGArQ6XpozX) and download either file or the whole folder. The individual `.duckdb` files are ready to open; they do not need decompression or an import step.
2. If you download the folder as a ZIP, extract it with your archive manager, or run the command below with your actual ZIP filename. Keep enough disk space for the archive and the extracted databases (about 8.19 GiB combined), plus any exports.

   ```bash
   python3 -m zipfile -e Trading.zip ./datasets
   ```

3. Locate `trading.duckdb` and `crypto.duckdb` inside the extracted folder. They can live anywhere; replace the paths in the examples with their actual locations.
4. Create a small Python environment. The standalone examples and script use only `duckdb` (tested with Python 3.12 and DuckDB 1.5.4):

   ```bash
   python3 -m venv .venv-data
   source .venv-data/bin/activate
   # Windows PowerShell: .venv-data\Scripts\Activate.ps1
   python -m pip install duckdb==1.5.4
   ```

Save this as `example.py` next to your downloaded `crypto.duckdb`, then run `python example.py`:

```python
import duckdb

with duckdb.connect("crypto.duckdb", read_only=True) as con:
    print(con.execute("SHOW TABLES").fetchall())
    rows = con.execute("""
        SELECT timestamp, open, high, low, close, volume
        FROM bars
        WHERE symbol = ? AND timeframe = ?
          AND timestamp >= ? AND timestamp < ?
        ORDER BY timestamp
        LIMIT 10
    """, ["BTC/USD", "1Day", "2025-01-01", "2026-01-01"]).fetchall()
    for row in rows:
        print(row)
```

For stocks, use `trading.duckdb` and a ticker such as `AAPL`. Timestamps are stored as timezone-naive UTC. The example uses an inclusive start and exclusive end. No repository clone is needed for this example.

### Inspect and extract to CSV or Parquet

Download or copy just [`scripts/read_dataset.py`](scripts/read_dataset.py) into your working folder. It runs independently with the same single dependency and opens the source database read-only. These examples assume the script and databases are in the current directory:

```bash
# List every table, its row count, and column types.
python read_dataset.py --db trading.duckdb inspect

# Also show the actual first/last candle and row count for each symbol/timeframe.
python read_dataset.py --db crypto.duckdb inspect --coverage

# Extract an entire table without loading it into a Python DataFrame.
python read_dataset.py --db trading.duckdb export \
  --table news_articles --output exports/stock_news.parquet

# Extract a selected series to CSV. Keep the slash in crypto symbols.
python read_dataset.py --db crypto.duckdb export \
  --sql "SELECT * FROM bars WHERE symbol = 'BTC/USD' AND timeframe = '1Day' AND timestamp >= '2025-01-01' AND timestamp < '2026-01-01' ORDER BY timestamp" \
  --output exports/btc_daily_2025.csv
```

The extension selects CSV (with a header) or Zstandard-compressed Parquet. The script creates output directories and refuses to overwrite existing files. Parquet preserves column types and is usually much smaller than CSV; neither pandas nor PyArrow is required for these exports. Prefer filtered queries for the large `bars` tables. If you cloned this repository, use `python scripts/read_dataset.py` with `--db data/trading.duckdb` or `--db data/crypto/crypto.duckdb` instead.

For direct SQL exports, full-database extraction, and news/sentiment joins, see [Using the datasets](docs/DATABASE_USAGE.md).

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

Trading Lab stores stock/ETF data in `data/trading.duckdb` by default (overridable with `DUCKDB_PATH`) and crypto data in `data/crypto/crypto.duckdb`. To use the downloads in the app, place each file at the corresponding path before starting the services. For standalone use, the files can stay anywhere; see [Public Datasets](#public-datasets) and the [data guide](docs/DATABASE_USAGE.md).

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
