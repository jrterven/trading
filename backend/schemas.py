from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AssetClass = Literal["stock", "crypto"]


class SymbolResult(BaseModel):
    symbol: str
    name: str
    exchange: str | None = None
    tradable: bool = True


class Bar(BaseModel):
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str = "alpaca"


class NewsArticle(BaseModel):
    id: str
    source: str
    symbol: str
    headline: str
    summary: str | None = None
    url: str | None = None
    author: str | None = None
    published_at: datetime
    available_at: datetime | None = None
    content: str | None = None
    raw_symbols: list[str] = Field(default_factory=list)
    relation_type: Literal["direct", "indirect"] = "direct"
    relevance_score: float = 1.0
    relation_reason: str | None = None
    classifier_model: str | None = None
    classifier_version: str | None = None


class NewsFetchDayCount(BaseModel):
    date: str
    count: int


class NewsFetchDailyStats(BaseModel):
    max: NewsFetchDayCount | None = None
    min: NewsFetchDayCount | None = None
    average: float = 0.0


class MarketDataTimeframeSummary(BaseModel):
    timeframe: str
    total: int = 0
    fetched: int = 0
    new: int = 0
    existing: int = 0
    failed_windows: int = 0


class MarketDataFetchSummary(BaseModel):
    symbol: str
    start: datetime
    end: datetime
    timeframes: list[MarketDataTimeframeSummary] = Field(default_factory=list)


class DatasetBarCoverage(BaseModel):
    timeframe: str
    count: int = 0
    start: datetime | None = None
    end: datetime | None = None


class DatasetSummaryRow(BaseModel):
    symbol: str
    news_count: int = 0
    news_start: datetime | None = None
    news_end: datetime | None = None
    sentiment_count: int = 0
    sentiment_coverage_pct: float = 0.0
    bars: list[DatasetBarCoverage] = Field(default_factory=list)
    has_news: bool = False
    has_sentiment: bool = False
    has_ohlcv: bool = False


class NewsFetchSummary(BaseModel):
    total: int
    fetched: int
    existing: int
    new: int
    daily: NewsFetchDailyStats = Field(default_factory=NewsFetchDailyStats)
    market_data: MarketDataFetchSummary | None = None


class NewsFetchResponse(BaseModel):
    articles: list[NewsArticle]
    summary: NewsFetchSummary


class SentimentScore(BaseModel):
    id: str
    article_id: str
    symbol: str
    label: Literal["positive", "neutral", "negative"]
    score: float
    positive: float
    neutral: float
    negative: float
    model: str
    model_version: str | None = None
    prompt_version: str | None = None
    explanation: str | None = None
    created_at: datetime


class Marker(BaseModel):
    id: str | None = None
    run_id: str | None = None
    symbol: str
    timestamp: datetime
    marker_type: str
    label: str
    color: str
    price: float | None = None
    source: str = "strategy"


class Trade(BaseModel):
    id: str
    run_id: str
    symbol: str
    side: Literal["long"]
    entry_time: datetime
    exit_time: datetime | None = None
    entry_price: float
    exit_price: float | None = None
    quantity: float
    pnl: float
    return_pct: float


class NewsFetchRequest(BaseModel):
    symbol: str = "AAPL"
    asset_class: AssetClass = "stock"
    start: datetime | None = None
    end: datetime | None = None
    include_rss: bool = False
    limit: int = Field(default=100, ge=1, le=10000)
    relation_type: Literal["all", "direct", "indirect"] = "all"


class SentimentRunRequest(BaseModel):
    symbol: str
    asset_class: AssetClass = "stock"
    article_ids: list[str] | None = None
    use_ollama: bool = False


class BacktestRequest(BaseModel):
    symbol: str = "AAPL"
    timeframe: str = "1Day"
    start: datetime
    end: datetime
    code: str
    strategy_name: str = "Untitled strategy"
    initial_cash: float = Field(default=10000, gt=0)
    commission_pct: float = Field(default=0.001, ge=0, le=0.05)
    position_size_cash: float | None = Field(default=None, gt=0)
    stop_loss_pct: float | None = Field(default=None, ge=0, le=100)
    take_profit_pct: float | None = Field(default=None, ge=0, le=100)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)


class BacktestRun(BaseModel):
    id: str
    strategy_id: str
    strategy_name: str | None = None
    strategy_code: str | None = None
    symbol: str
    timeframe: str
    start_at: datetime
    end_at: datetime
    status: Literal["completed", "failed"]
    initial_cash: float
    commission_pct: float
    metrics: dict[str, Any] = Field(default_factory=dict)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[Trade] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    error: str | None = None
    stdout_text: str | None = None
    stderr_text: str | None = None
    debug: Any | None = None
    environment: dict[str, Any] | None = None
    runtime_seconds: float | None = None
    timeout_seconds: int | None = None
    created_at: datetime


class BacktestSummary(BaseModel):
    id: str
    strategy_id: str
    strategy_name: str
    symbol: str
    timeframe: str
    start_at: datetime
    end_at: datetime
    status: Literal["completed", "failed"]
    final_equity: float | None = None
    total_return_pct: float | None = None
    trade_count: int | None = None
    created_at: datetime


class StrategySaveRequest(BaseModel):
    name: str = "Untitled strategy"
    code: str


class StrategyRecord(BaseModel):
    id: str
    name: str
    code: str
    file_path: str | None = None
    created_at: datetime
    updated_at: datetime


class StrategyPackageInfo(BaseModel):
    installed: bool
    version: str | None = None


class StrategyEnvironment(BaseModel):
    python_executable: str
    python_version: str
    platform: str
    strategy_timeout_seconds: int
    packages: dict[str, StrategyPackageInfo]
    cuda_available: bool
    cuda_device_count: int
    cuda_device_name: str | None = None


class PaperOrderRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0)


class PaperOrder(BaseModel):
    id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    status: str
    created_at: datetime
