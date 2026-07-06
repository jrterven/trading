from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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
    volume: int
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
    content: str | None = None
    raw_symbols: list[str] = Field(default_factory=list)


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
    start: datetime | None = None
    end: datetime | None = None
    include_rss: bool = False
    limit: int = Field(default=30, ge=1, le=100)


class SentimentRunRequest(BaseModel):
    symbol: str
    article_ids: list[str] | None = None
    use_ollama: bool = False


class BacktestRequest(BaseModel):
    symbol: str = "AAPL"
    timeframe: str = "1Day"
    start: datetime
    end: datetime
    code: str
    strategy_name: str = "Estrategia sin nombre"
    initial_cash: float = Field(default=10000, gt=0)
    commission_pct: float = Field(default=0.001, ge=0, le=0.05)
    position_size_cash: float | None = Field(default=None, gt=0)
    stop_loss_pct: float | None = Field(default=None, ge=0, le=100)
    take_profit_pct: float | None = Field(default=None, ge=0, le=100)


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
    created_at: datetime


class BacktestSummary(BaseModel):
    id: str
    strategy_id: str
    strategy_name: str
    symbol: str
    timeframe: str
    status: Literal["completed", "failed"]
    final_equity: float | None = None
    total_return_pct: float | None = None
    trade_count: int | None = None
    created_at: datetime


class StrategySaveRequest(BaseModel):
    name: str = "Estrategia sin nombre"
    code: str


class StrategyRecord(BaseModel):
    id: str
    name: str
    code: str
    file_path: str | None = None
    created_at: datetime
    updated_at: datetime


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
