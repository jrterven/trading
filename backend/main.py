from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import init_db
from .sample_data import default_date_window
from .schemas import (
    BacktestRequest,
    NewsFetchRequest,
    PaperOrderRequest,
    SentimentRunRequest,
    StrategySaveRequest,
)
from .services.backtesting import BacktestService
from .services.crypto_dataset import CryptoDatasetService, crypto_db_path
from .services.dataset import DatasetService
from .services.market_data import MarketDataService
from .services.news import NewsService
from .services.paper import PaperService
from .services.sandbox import strategy_environment
from .services.sentiment import SentimentService
from .services.strategies import StrategyService
from .time_utils import parse_datetime, utc_now

logging.basicConfig(level=logging.INFO)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(settings)
    yield


app = FastAPI(title="Trading Lab", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "alpaca_configured": settings.has_alpaca_credentials,
        "duckdb_path": str(settings.duckdb_path),
        "crypto_duckdb_path": str(crypto_db_path(settings)),
    }


@app.get("/api/symbols/search")
async def search_symbols(
    q: str | None = Query(default=None, min_length=0),
    asset_class: str = Query(default="stock", pattern="^(stock|crypto)$"),
) -> list[dict]:
    if asset_class == "crypto":
        service = CryptoDatasetService(settings)
        return [item.model_dump() for item in await service.search_symbols(q)]
    service = MarketDataService(settings)
    return [item.model_dump() for item in await service.search_symbols(q)]


@app.get("/api/bars")
async def get_bars(
    symbol: str = "AAPL",
    timeframe: str = "1Day",
    start: str | None = None,
    end: str | None = None,
    refresh: bool = False,
    asset_class: str = Query(default="stock", pattern="^(stock|crypto)$"),
) -> list[dict]:
    default_start, default_end = default_date_window()
    parsed_start = parse_datetime(start, default_start)
    parsed_end = parse_datetime(end, default_end)
    if asset_class == "crypto":
        bars = CryptoDatasetService(settings).get_bars(
            symbol=symbol,
            timeframe=timeframe,
            start=parsed_start,
            end=parsed_end,
        )
        return [bar.model_dump(mode="json") for bar in bars]
    service = MarketDataService(settings)
    bars = await service.get_bars(
        symbol=symbol,
        timeframe=timeframe,
        start=parsed_start,
        end=parsed_end,
        refresh=refresh,
    )
    return [bar.model_dump(mode="json") for bar in bars]


@app.get("/api/news")
def get_news(
    symbol: str = "AAPL",
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(default=100, ge=1, le=10000),
    relation_type: str = Query(default="all", pattern="^(all|direct|indirect)$"),
    asset_class: str = Query(default="stock", pattern="^(stock|crypto)$"),
) -> list[dict]:
    if asset_class == "crypto":
        service = CryptoDatasetService(settings)
        articles = service.get_articles(
            symbol=symbol,
            start=parse_datetime(start, None) if start else None,
            end=parse_datetime(end, None) if end else None,
            limit=limit,
            relation_type=relation_type,  # type: ignore[arg-type]
        )
        return [article.model_dump(mode="json") for article in articles]
    service = NewsService(settings)
    articles = service.get_articles(
        symbol=symbol,
        start=parse_datetime(start, None) if start else None,
        end=parse_datetime(end, None) if end else None,
        limit=limit,
        relation_type=relation_type,  # type: ignore[arg-type]
    )
    return [article.model_dump(mode="json") for article in articles]


@app.post("/api/news/fetch")
async def fetch_news(request: NewsFetchRequest) -> dict:
    if request.asset_class == "crypto":
        result = CryptoDatasetService(settings).fetch_with_summary(
            symbol=request.symbol,
            start=request.start,
            end=request.end,
            limit=request.limit,
            relation_type=request.relation_type,
        )
        return result.model_dump(mode="json")
    service = NewsService(settings)
    result = await service.fetch_and_store_with_summary(
        symbol=request.symbol,
        start=request.start,
        end=request.end,
        include_rss=request.include_rss,
        limit=request.limit,
        relation_type=request.relation_type,
    )
    return result.model_dump(mode="json")


@app.post("/api/sentiment/run")
async def run_sentiment(request: SentimentRunRequest) -> list[dict]:
    if request.asset_class == "crypto":
        scores = CryptoDatasetService(settings).get_scores(
            request.symbol,
            article_ids=request.article_ids,
        )
        return [score.model_dump(mode="json") for score in scores]
    service = SentimentService(settings)
    scores = await service.run_for_symbol(
        request.symbol,
        article_ids=request.article_ids,
        use_ollama=request.use_ollama,
    )
    return [score.model_dump(mode="json") for score in scores]


@app.get("/api/sentiment")
def get_sentiment(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    asset_class: str = Query(default="stock", pattern="^(stock|crypto)$"),
) -> list[dict]:
    if asset_class == "crypto":
        scores = CryptoDatasetService(settings).get_scores(
            symbol=symbol,
            start=parse_datetime(start, None) if start else None,
            end=parse_datetime(end, None) if end else None,
        )
        return [score.model_dump(mode="json") for score in scores]
    service = SentimentService(settings)
    scores = service.get_scores(
        symbol=symbol,
        start=parse_datetime(start, None) if start else None,
        end=parse_datetime(end, None) if end else None,
    )
    return [score.model_dump(mode="json") for score in scores]


@app.get("/api/dataset/summary")
def get_dataset_summary(
    asset_class: str = Query(default="stock", pattern="^(stock|crypto)$"),
) -> list[dict]:
    if asset_class == "crypto":
        return [row.model_dump(mode="json") for row in CryptoDatasetService(settings).summary()]
    service = DatasetService(settings)
    return [row.model_dump(mode="json") for row in service.summary()]


@app.post("/api/backtests")
async def run_backtest(request: BacktestRequest) -> dict:
    service = BacktestService(settings)
    run = await service.run(request)
    return run.model_dump(mode="json")


@app.get("/api/backtests")
def list_backtests(limit: int = Query(default=25, ge=1, le=100)) -> list[dict]:
    service = BacktestService(settings)
    return [item.model_dump(mode="json") for item in service.list_runs(limit=limit)]


@app.get("/api/backtests/{run_id}")
def get_backtest(run_id: str) -> dict:
    service = BacktestService(settings)
    try:
        run = service.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Backtest no encontrado") from exc
    return run.model_dump(mode="json")


@app.delete("/api/backtests/{run_id}")
def delete_backtest(run_id: str) -> dict:
    service = BacktestService(settings)
    if not service.delete(run_id):
        raise HTTPException(status_code=404, detail="Backtest no encontrado")
    return {"deleted": True, "id": run_id}


@app.get("/api/strategies")
def list_strategies(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    service = StrategyService(settings)
    return [item.model_dump(mode="json") for item in service.list(limit=limit)]


@app.get("/api/strategy/environment")
def get_strategy_environment() -> dict:
    return strategy_environment(settings.strategy_timeout_seconds)


@app.post("/api/strategies")
def save_strategy(request: StrategySaveRequest) -> dict:
    service = StrategyService(settings)
    return service.save(request).model_dump(mode="json")


@app.get("/api/paper/portfolio")
async def get_paper_portfolio() -> dict:
    try:
        return await PaperService(settings).portfolio()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/paper/orders")
async def place_paper_order(request: PaperOrderRequest) -> dict:
    try:
        order = await PaperService(settings).place_order(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return order.model_dump(mode="json")


@app.websocket("/ws/market/{symbol}")
async def market_stream(websocket: WebSocket, symbol: str, timeframe: str = "1Min") -> None:
    await websocket.accept()
    service = MarketDataService(settings)
    try:
        while True:
            end = utc_now()
            start = end - timedelta(minutes=90)
            bars = await service.get_bars(symbol, timeframe, start, end, refresh=True)
            latest = bars[-1] if bars else None
            await websocket.send_json(
                {
                    "symbol": symbol.upper(),
                    "timeframe": timeframe,
                    "bar": latest.model_dump(mode="json") if latest else None,
                    "mode": "alpaca" if settings.has_alpaca_credentials else "sin_alpaca",
                }
            )
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        return
