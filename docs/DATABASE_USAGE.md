# Trading Lab DuckDB Usage

This project stores market data, news, and sentiment locally in DuckDB. The default database file is:

```text
data/trading.duckdb
```

If `.env` sets `DUCKDB_PATH`, that value is used instead. Relative paths are resolved from the project root.

## Read The Database Externally

Install the Python dependencies from the project environment, then connect directly:

```python
import duckdb

con = duckdb.connect("data/trading.duckdb", read_only=True)
print(con.execute("select count(*) from bars").fetchone())
con.close()
```

Use `read_only=True` for training/export jobs so they do not lock or mutate the app database.

## Main Tables

### `bars`

OHLCV candles by ticker and timeframe.

Important columns:

- `symbol`: ticker, for example `AAPL`.
- `timeframe`: `1Min`, `5Min`, `15Min`, `1Hour`, `1Day`.
- `timestamp`: candle timestamp in UTC.
- `open`, `high`, `low`, `close`, `volume`: market data.
- `source`: usually `alpaca`.

Unique key:

```text
symbol, timeframe, timestamp
```

### `news_articles`

Unique global news articles.

Important columns:

- `id`: article id.
- `source`: provider, usually `alpaca`.
- `headline`, `summary`, `content`, `url`.
- `published_at`: article publication time.
- `available_at`: time the strategy/model should be allowed to see the article. For now it usually matches `published_at`.
- `raw_symbols`: JSON text with provider tickers.

### `news_article_symbols`

Relationship between articles and tickers.

Important columns:

- `article_id`
- `symbol`
- `relation_type`: `direct` or `indirect`.
- `relevance_score`
- `relation_reason`
- `classifier_model`, `classifier_version`

Use this table to select news for a specific ticker.

### `sentiment_scores`

Article-level sentiment by ticker.

Important columns:

- `article_id`
- `symbol`
- `label`: `positive`, `neutral`, or `negative`.
- `score`: probability of the selected label.
- `positive`, `neutral`, `negative`: model probabilities.
- `model`, `model_version`, `prompt_version`

### Coverage Tables

- `news_fetch_coverage`: what historical news windows were fetched.
- `bars_fetch_coverage`: what OHLCV windows were fetched by timeframe.

These are useful for auditing completeness, not usually needed as model features.

## No Look-Ahead Rule

For training and backtesting, never join a candle with future news. Use:

```sql
na.available_at <= bar.timestamp
```

For daily candles, a conservative default is to aggregate news available up to the candle timestamp. If you want to model “news during the trading day affects next day,” shift the news features by one candle in your ML pipeline.

## Example Queries

Daily AAPL candles:

```sql
select *
from bars
where symbol = 'AAPL'
  and timeframe = '1Day'
order by timestamp;
```

AAPL news with sentiment:

```sql
select
  na.id,
  nas.symbol,
  na.available_at,
  na.headline,
  nas.relation_type,
  ss.label,
  ss.score,
  ss.positive,
  ss.neutral,
  ss.negative
from news_articles na
join news_article_symbols nas on nas.article_id = na.id
left join sentiment_scores ss
  on ss.article_id = na.id
 and ss.symbol = nas.symbol
where nas.symbol = 'AAPL'
order by na.available_at;
```

Aggregate daily news sentiment for AAPL:

```sql
select
  cast(na.available_at as date) as news_date,
  count(*) as news_count,
  avg(ss.positive) as avg_positive,
  avg(ss.neutral) as avg_neutral,
  avg(ss.negative) as avg_negative,
  avg(case
    when ss.label = 'positive' then ss.score
    when ss.label = 'negative' then -ss.score
    else 0
  end) as avg_signed_sentiment
from news_articles na
join news_article_symbols nas on nas.article_id = na.id
left join sentiment_scores ss
  on ss.article_id = na.id
 and ss.symbol = nas.symbol
where nas.symbol = 'AAPL'
group by 1
order by 1;
```

## Export A Training Dataset

The repo includes an example exporter:

```bash
conda activate trading-lab
python scripts/export_training_dataset.py \
  --db data/trading.duckdb \
  --symbol AAPL \
  --timeframe 1Day \
  --output data/aapl_training_daily.csv
```

It outputs one row per candle with OHLCV plus trailing news/sentiment features.

Common options:

```bash
python scripts/export_training_dataset.py --help
```

## Example Output Columns

The example script exports:

- Candle columns: `symbol`, `timeframe`, `timestamp`, `open`, `high`, `low`, `close`, `volume`.
- Return columns: `return_1`, `future_return_1`.
- News columns: `news_count`, `direct_news_count`, `indirect_news_count`.
- Sentiment columns: `avg_positive`, `avg_neutral`, `avg_negative`, `avg_signed_sentiment`.
- Rolling sentiment columns over the last N candles, controlled by `--lookback-bars`.

`future_return_1` is included as an example supervised-learning target. Drop it when doing live inference.

