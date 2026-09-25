# Using the Trading Lab Datasets

The two public files are ordinary, self-contained DuckDB databases. You can download just one, move it to any directory, and read it with DuckDB without installing Trading Lab, configuring `.env`, calling Alpaca, or downloading a sentiment model.

- <a href="https://u.pcloud.link/publink/show?code=kZH4n4JZxvPDaHEN5CmTdmEonWGArQ6XpozX" target="_blank" rel="noopener noreferrer"><strong>Public download folder ↗</strong></a>: `trading.duckdb` (stocks/ETFs) and `crypto.duckdb` (cryptocurrencies).
- **[Download, unzip, and quick start](#download-and-open-the-data-independently)**: snapshot sizes, counts, date ranges, and installation instructions.
- **[Standalone inspection/export script](../scripts/read_dataset.py)**: copy this single file alongside your databases; its only dependency is `duckdb`.

Examples below assume the downloaded files are in your current directory. Inside the repository, their usual locations are `data/trading.duckdb` and `data/crypto/crypto.duckdb`. `DUCKDB_PATH` configures the application's stock database; direct DuckDB connections and the standalone script use the path you supply.

## Download and open the data independently

On GitHub, use **Cmd + click** (macOS) or **Ctrl + click** (Windows/Linux) to open the download in another tab. GitHub removes the link’s `target` attribute; compatible HTML viewers honor it.

1. Open the <a href="https://u.pcloud.link/publink/show?code=kZH4n4JZxvPDaHEN5CmTdmEonWGArQ6XpozX" target="_blank" rel="noopener noreferrer">public pCloud folder ↗</a> and download either file or the whole folder. The individual `.duckdb` files are ready to open; they do not need decompression or an import step.
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

## Connect without the application

Install the tested DuckDB version in your own Python environment:

```bash
python -m pip install duckdb==1.5.4
```

```python
import duckdb

with duckdb.connect("trading.duckdb", read_only=True) as con:
    print(con.execute("SHOW TABLES").fetchall())
    print(con.execute("DESCRIBE bars").fetchall())
    print(con.execute("SELECT COUNT(*) FROM bars").fetchone())
```

Use `read_only=True` to prevent source database changes. It does **not** allow another process to write the same database concurrently: stop an app/backfill that holds a write connection, or use a separate download/snapshot. Point to an existing file; do not use the application's database initializer for standalone analysis.

If you already have the DuckDB CLI installed, you can run the SQL examples there:

```bash
duckdb -readonly trading.duckdb
```

## Snapshot contents and coverage

The [README comparison table](../README.md#what-is-in-each-file) describes the files inspected on **2026-09-25**. They are static snapshots. Counts and global date ranges do not imply that every expected candle is present.

### Symbols with candles

**Stocks and ETFs (38):**

```text
AAPL ABBV ADBE AMD AMZN AVGO BAC CRM CSCO CVX DIA GOOG GOOGL GS IBM INTC
IWM JNJ JPM LLY MA META MRK MS MSFT NFLX NVDA ORCL PFE PYPL QCOM QQQ SPY
TSLA UNH V WFC XOM
```

**Cryptocurrency pairs (20):**

```text
AAVE/USD ADA/USD ARB/USD AVAX/USD BCH/USD BONK/USD BTC/USD CRV/USD
DOGE/USD DOT/USD ETH/USD FIL/USD GRT/USD LINK/USD LTC/USD PEPE/USD
SHIB/USD SOL/USD UNI/USD XRP/USD
```

These are the symbols actually found in the files, not every asset supported by the data provider. Always retain `/USD` when querying crypto.

### Candles by timeframe

| Timeframe | Meaning | `trading.duckdb` rows | `crypto.duckdb` rows |
| --- | --- | ---: | ---: |
| `1Min` | One minute | 46,369,403 | 29,397,924 |
| `5Min` | Five minutes | 11,277,897 | 7,211,412 |
| `15Min` | Fifteen minutes | 4,266,862 | 2,490,930 |
| `1Hour` | One hour | 1,211,780 | 628,963 |
| `1Day` | One day | 88,059 | 26,242 |

Each timeframe is a separate series. Filter both `symbol` and `timeframe` before calculating returns or aggregating volume; adding rows across timeframes double-counts the underlying activity.

Stock candles span 2017-01-03 through 2026-07-21 globally, but most symbols end on July 1 and CVX ends on 2017-08-31. Crypto spans 2021-01-01 through 2026-07-01 globally; ADA/USD begins on 2026-02-13, and ARB/USD, BONK/USD, and FIL/USD begin on 2026-02-16. Other pairs also have different starting dates.

Inspect the actual coverage before choosing a period:

```sql
SELECT symbol, timeframe, COUNT(*) AS bar_count,
       MIN(timestamp) AS first_bar, MAX(timestamp) AS last_bar
FROM bars
GROUP BY symbol, timeframe
ORDER BY symbol, timeframe;
```

The equivalent script command is:

```bash
python read_dataset.py --db crypto.duckdb inspect --coverage
```

## Table reference

Both databases have the following six data tables:

| Table | One row represents | Stock rows | Crypto rows |
| --- | --- | ---: | ---: |
| `bars` | One symbol/timeframe/timestamp candle | 63,214,001 | 39,755,471 |
| `news_articles` | One article, keyed by `id` | 253,514 | 30,595 |
| `news_article_symbols` | One article-to-symbol relationship | 368,483 | 52,468 |
| `sentiment_scores` | One stored model result for an article/symbol | 367,878 | 52,468 |
| `bars_fetch_coverage` | One recorded candle download window/attempt | 53,495 | 14,160 |
| `news_fetch_coverage` | One recorded news download window/attempt | 128,280 | 1,340 |

`trading.duckdb` additionally contains empty application tables: `strategies`, `backtest_runs`, `trades`, `markers`, and `paper_orders`. They are not needed to use the market/news datasets. The crypto database does not contain these tables.

### `bars`: OHLCV candles

| Columns | Meaning |
| --- | --- |
| `symbol`, `timeframe`, `timestamp` | Unique candle key. Timestamps are stored as UTC in DuckDB `TIMESTAMP` columns without timezone metadata. |
| `open`, `high`, `low`, `close` | Price fields (`DOUBLE`); USD for these stock symbols and USD-quoted crypto pairs. |
| `volume` | Traded volume, not dollar notional. Stock file: `BIGINT`; crypto file: `DOUBLE`, preserving fractional quantities. |
| `source` | `alpaca` in both snapshots. |
| `created_at` | Local ingestion/storage time, not the candle's market time. |
| `trade_count`, `vwap` | **Crypto only**: provider trade count (`BIGINT`) and volume-weighted average price (`DOUBLE`); nullable. |

The stock downloader requests `adjustment=raw`; do not assume split/dividend-adjusted prices. The stock provider feed is configurable in the app, but `bars.source` only records `alpaca`, not the feed name. The snapshot alone does not establish consolidated-market coverage.

Treat timestamps as candle labels, not proof that the candle's final close was already known at that instant. Daily stock labels can be at 04:00/05:00 UTC rather than midnight UTC. Account for bar completion and market sessions in downstream analysis.

### `news_articles`: unique articles

Common columns are `id`, `source`, `headline`, `summary`, `content`, `url`, `author`, `published_at`, `available_at`, `raw_symbols`, and `created_at`.

- `id` is the join key within that database. Do not assume IDs are unique across both files.
- `published_at` is the publication timestamp. `available_at` is the stored availability timestamp; it equals `published_at` throughout these snapshots, so it is not a measured historical delivery time.
- `raw_symbols` contains provider symbols as JSON text. Use `news_article_symbols` for the dataset's normalized symbol relationships.
- `summary`, `content`, `url`, and `author` may be null. Content can contain provider HTML.
- The stock file has a legacy `symbol` column. The crypto file instead has `provider_id`. Use the relationship table for symbol filtering in either file.
- News was fetched through Alpaca. Stored `source` is `alpaca` for stocks and `benzinga` for crypto.

### `news_article_symbols`: article-to-symbol relationships

The unique key is `(article_id, symbol)`; join `article_id` to `news_articles.id`.

`relation_type`, `relevance_score`, and `relation_reason` describe the association. `classifier_model` and `classifier_version` identify the rules that produced it; `created_at` and `updated_at` record storage times. All stored relationships in these snapshots are `direct`, although the application schema also supports `indirect`.

One article may relate to multiple symbols. Count distinct article IDs when you want unique articles across symbols, and count relationship rows when you want per-symbol article occurrences.

### `sentiment_scores`: precomputed model outputs

Join to an article **and** its symbol using `(article_id, symbol)`.

- `id`: stored score identifier.
- `label`: `positive`, `neutral`, or `negative`.
- `score`: model probability of the selected label; not a signed return or trading signal.
- `positive`, `neutral`, `negative`: the three model probabilities.
- `model`: `ProsusAI/finbert` in both snapshots.
- `model_version`: stored pipeline version `2026-07-07` for stocks and `2026-07-08` for crypto; these are not Hugging Face commit hashes.
- `prompt_version`, `explanation`, `created_at`: optional prompt/explanation metadata and score computation time.

Use a `LEFT JOIN` because a news relationship may not have a sentiment result. There is one model/version in these files; if you add more scores later, choose a model/version before joining to avoid multiplying rows. These are model-generated annotations, not human sentiment labels.

### Download coverage tables

Both tables record `id`, `provider`, `symbol`, `start_at`, `end_at`, `status`, `fetched_at`, `params_hash`, and `error`. Candle coverage also includes `timeframe` and `bar_count`; news coverage includes `article_count`.

These are download logs, not market observations. Window counts can overlap and should not be summed as unique candle/article totals. A `completed` window is not proof of a continuous time series. The stock snapshot includes 215 failed bar records and 2 failed news records; the crypto snapshot has only completed records. Retries may cover a failed window, so inspect actual rows as well as the logs.

```sql
SELECT symbol, timeframe, start_at, end_at, error
FROM bars_fetch_coverage
WHERE status = 'failed'
ORDER BY symbol, start_at;
```

## Query candles and news

Use an inclusive start and exclusive end to include full days without relying on `23:59:59`:

```sql
SELECT timestamp, open, high, low, close, volume
FROM bars
WHERE symbol = 'AAPL' AND timeframe = '1Day'
  AND timestamp >= TIMESTAMP '2025-01-01'
  AND timestamp < TIMESTAMP '2026-01-01'
ORDER BY timestamp;
```

The same query works on `crypto.duckdb` with `symbol = 'BTC/USD'`.

News with sentiment, one row per matching article/symbol in these snapshots:

```sql
SELECT na.id, nas.symbol, na.published_at,
       COALESCE(na.available_at, na.published_at) AS available_at,
       na.headline, na.url, nas.relation_type,
       ss.label, ss.score, ss.positive, ss.neutral, ss.negative
FROM news_articles AS na
JOIN news_article_symbols AS nas ON nas.article_id = na.id
LEFT JOIN sentiment_scores AS ss
  ON ss.article_id = na.id AND ss.symbol = nas.symbol
WHERE nas.symbol = 'AAPL'
  AND COALESCE(na.available_at, na.published_at) >= TIMESTAMP '2025-01-01'
  AND COALESCE(na.available_at, na.published_at) < TIMESTAMP '2026-01-01'
ORDER BY available_at, na.id;
```

For crypto, change the connection path and use a pair such as `BTC/USD`; the joins stay the same. Avoid loading the entire `bars` table with `fetchall()` or into a DataFrame. Select a symbol, timeframe, date range, and only the columns you need, or export directly with DuckDB.

## Extract tables or query results

A `.duckdb` file is already a database; “extracting” it means exporting tables/query results, not unpacking it as an archive. Only the optional pCloud ZIP needs decompression.

### Standalone script

The script requires only Python and DuckDB. It does not import project code or read `.env`.

```bash
python read_dataset.py --help
python read_dataset.py --db trading.duckdb inspect
python read_dataset.py --db crypto.duckdb inspect --coverage

# Whole tables; --table retains every column, including crypto-only columns.
python read_dataset.py --db crypto.duckdb export \
  --table sentiment_scores --output exports/crypto_sentiment.parquet

# Filtered candles; --sql accepts one SELECT, including WITH queries.
python read_dataset.py --db trading.duckdb export \
  --sql "SELECT * FROM bars WHERE symbol = 'AAPL' AND timeframe = '1Day' ORDER BY timestamp" \
  --output exports/aapl_daily.csv
```

Use either `--table` or `--sql`. Outputs must end in `.csv` or `.parquet`; CSV includes a header, and Parquet uses Zstandard compression. Existing output files are rejected. DuckDB writes the result directly rather than materializing it in Python memory. Zero matching rows produce an empty result file with its column schema/header.

### Direct Python / SQL export

DuckDB can export without pandas or PyArrow:

```python
from pathlib import Path
import duckdb

Path("exports").mkdir(exist_ok=True)
with duckdb.connect("crypto.duckdb", read_only=True) as con:
    con.execute("""
        COPY (
            SELECT * FROM bars
            WHERE symbol = 'BTC/USD' AND timeframe = '1Day'
            ORDER BY timestamp
        ) TO 'exports/btc_daily.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
```

For CSV, change the filename to `.csv` and the options to `(FORMAT CSV, HEADER TRUE)`. Direct `COPY` can overwrite an existing file; the standalone script adds the existence check.

To export **every table**, use a new destination directory for each database. This writes table files plus SQL schema/load scripts; allow additional disk space, especially for CSV:

```python
import duckdb

with duckdb.connect("trading.duckdb", read_only=True) as con:
    con.execute("EXPORT DATABASE 'stock_export' (FORMAT PARQUET)")

with duckdb.connect("crypto.duckdb", read_only=True) as con:
    con.execute("EXPORT DATABASE 'crypto_export' (FORMAT PARQUET)")
```

To read an exported Parquet file, DuckDB alone is sufficient:

```python
import duckdb

with duckdb.connect() as con:
    print(con.execute("SELECT * FROM read_parquet('exports/btc_daily.parquet') LIMIT 5").fetchall())
```

For pandas workflows, optionally install `pandas` and call `.fetchdf()` on a filtered DuckDB query. Standalone querying and the exports above do not require it.

## Time alignment for research and ML

All stored timestamps in these tables use UTC without timezone metadata. Attach UTC explicitly when converting to tools that require timezone-aware timestamps.

Only use news available by the decision time, for example:

```sql
COALESCE(na.available_at, na.published_at) <= decision_timestamp
```

Also ensure a candle has finished before using its final OHLCV values. Do not join an entire day's news to a decision at the start of that same day. Because `available_at` equals publication time in these snapshots, add an explicit delivery/processing-lag assumption if your analysis needs one. `created_at` records later ingestion/scoring and is not historical news availability.

The repository also includes [`export_training_dataset.py`](../scripts/export_training_dataset.py), an optional feature-engineering example requiring **DuckDB and pandas** (plus a pandas Parquet engine such as PyArrow for its Parquet output):

```bash
python -m pip install duckdb==1.5.4 pandas
python scripts/export_training_dataset.py \
  --db trading.duckdb --symbol AAPL --timeframe 1Day \
  --output exports/aapl_training_daily.csv
```

It produces OHLCV, daily news counts, average sentiment, rolling features, `return_1`, and `future_return_1`. It joins news by calendar date, including news published later than a candle's timestamp, so its same-day features require realignment to your decision time before predictive evaluation. `future_return_1` is an example training target and must never be an input feature. Use the standalone raw-data exporter when you want to define the feature timing yourself.
