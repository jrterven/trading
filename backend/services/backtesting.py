from __future__ import annotations

import json
import math
import uuid
from datetime import datetime
from typing import Any

import numpy as np

from ..config import Settings, get_settings
from ..db import as_utc_naive, connection, rows_to_dicts
from ..schemas import BacktestRequest, BacktestRun, BacktestSummary, Bar, Marker, Trade
from ..time_utils import isoformat_utc, utc_now
from .market_data import MarketDataService
from .news import NewsService
from .sandbox import StrategyExecutionError, run_strategy_subprocess, strategy_environment
from .sentiment import SentimentService


STRATEGY_NEWS_LIMIT = 10_000


class BacktestService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.market_data = MarketDataService(self.settings)
        self.news = NewsService(self.settings)
        self.sentiment = SentimentService(self.settings)

    async def run(self, request: BacktestRequest) -> BacktestRun:
        run_id = str(uuid.uuid4())
        strategy_id = str(uuid.uuid4())
        created_at = utc_now()
        bars = await self.market_data.get_bars(
            request.symbol, request.timeframe, request.start, request.end
        )
        effective_end = max((bar.timestamp for bar in bars), default=request.end)
        articles = self.news.get_articles(
            request.symbol,
            request.start,
            effective_end,
            limit=STRATEGY_NEWS_LIMIT,
        )
        scores = self.sentiment.get_scores(request.symbol, start=request.start, end=effective_end)
        payload = {
            "symbol": request.symbol.upper(),
            "timeframe": request.timeframe,
            "candles": [bar.model_dump(mode="json") for bar in bars],
            "news": [article.model_dump(mode="json") for article in articles],
            "sentiment": [score.model_dump(mode="json") for score in scores],
        }

        status = "completed"
        error = None
        stdout_text = None
        stderr_text = None
        debug: Any | None = None
        runtime_seconds = None
        timeout_seconds = request.timeout_seconds or self.settings.strategy_timeout_seconds
        environment = strategy_environment(timeout_seconds)
        metrics: dict[str, Any] = {}
        equity_curve: list[dict[str, Any]] = []
        trades: list[Trade] = []
        markers: list[Marker] = []
        try:
            if not bars:
                raise ValueError(
                    "No Alpaca bars found for the selected symbol, timeframe, and range"
                )
            result = run_strategy_subprocess(
                request.code,
                payload,
                timeout_seconds=timeout_seconds,
            )
            stdout_text = result.get("stdout")
            stderr_text = result.get("stderr")
            debug = result.get("debug")
            runtime_seconds = result.get("runtime_seconds")
            if result.get("python_executable"):
                environment["python_executable"] = result["python_executable"]
            simulation = simulate_long_only(
                bars=bars,
                entries=result.get("entries", []),
                exits=result.get("exits", []),
                initial_cash=request.initial_cash,
                commission_pct=request.commission_pct,
                position_size_cash=request.position_size_cash,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
                run_id=run_id,
                symbol=request.symbol.upper(),
            )
            metrics = simulation["metrics"]
            equity_curve = simulation["equity_curve"]
            trades = simulation["trades"]
            markers = simulation["markers"]
            markers.extend(
                normalize_strategy_markers(
                    result.get("markers", []),
                    request.symbol.upper(),
                    run_id,
                    bars,
                )
            )
        except StrategyExecutionError as exc:
            status = "failed"
            error = str(exc)
            stdout_text = exc.stdout_text
            stderr_text = exc.stderr_text
            debug = exc.debug
            runtime_seconds = exc.runtime_seconds
            if exc.python_executable:
                environment["python_executable"] = exc.python_executable
        except Exception as exc:
            status = "failed"
            error = str(exc)

        self._store_run(
            run_id=run_id,
            strategy_id=strategy_id,
            request=request,
            status=status,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trades,
            markers=markers,
            error=error,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            debug=debug,
            environment=environment,
            runtime_seconds=runtime_seconds,
            timeout_seconds=timeout_seconds,
            created_at=created_at,
        )
        return self.get(run_id)

    def get(self, run_id: str) -> BacktestRun:
        with connection(self.settings) as con:
            run_row = rows_to_dicts(
                con.execute(
                    """
                    SELECT r.id, r.strategy_id, s.name AS strategy_name, s.code AS strategy_code,
                           r.symbol, r.timeframe, r.start_at, r.end_at, r.status,
                           r.initial_cash, r.commission_pct, r.metrics_json, r.equity_curve_json,
                           r.error, r.stdout_text, r.stderr_text, r.debug_json,
                           r.environment_json, r.runtime_seconds, r.timeout_seconds,
                           r.created_at
                    FROM backtest_runs r
                    LEFT JOIN strategies s ON s.id = r.strategy_id
                    WHERE r.id = ?
                    """,
                    [run_id],
                )
            )
            if not run_row:
                raise KeyError(run_id)
            trade_rows = rows_to_dicts(
                con.execute(
                    """
                    SELECT id, run_id, symbol, side, entry_time, exit_time, entry_price,
                           exit_price, quantity, pnl, return_pct
                    FROM trades WHERE run_id = ? ORDER BY entry_time
                    """,
                    [run_id],
                )
            )
            marker_rows = rows_to_dicts(
                con.execute(
                    """
                    SELECT id, run_id, symbol, timestamp, marker_type, label, color,
                           price, source
                    FROM markers WHERE run_id = ? ORDER BY timestamp
                    """,
                    [run_id],
                )
            )
        row = run_row[0]
        return BacktestRun(
            id=row["id"],
            strategy_id=row["strategy_id"],
            strategy_name=row["strategy_name"],
            strategy_code=row["strategy_code"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            start_at=row["start_at"],
            end_at=row["end_at"],
            status=row["status"],
            initial_cash=row["initial_cash"],
            commission_pct=row["commission_pct"],
            metrics=json.loads(row["metrics_json"] or "{}"),
            equity_curve=json.loads(row["equity_curve_json"] or "[]"),
            trades=[Trade(**trade) for trade in trade_rows],
            markers=[Marker(**marker) for marker in marker_rows],
            error=row["error"],
            stdout_text=row["stdout_text"],
            stderr_text=row["stderr_text"],
            debug=json.loads(row["debug_json"]) if row["debug_json"] else None,
            environment=json.loads(row["environment_json"]) if row["environment_json"] else None,
            runtime_seconds=row["runtime_seconds"],
            timeout_seconds=row["timeout_seconds"],
            created_at=row["created_at"],
        )

    def list_runs(self, limit: int = 25) -> list[BacktestSummary]:
        with connection(self.settings) as con:
            rows = rows_to_dicts(
                con.execute(
                    """
                    SELECT r.id, r.strategy_id, COALESCE(s.name, 'Strategy') AS strategy_name,
                           r.symbol, r.timeframe, r.start_at, r.end_at, r.status,
                           r.metrics_json, r.created_at
                    FROM backtest_runs r
                    LEFT JOIN strategies s ON s.id = r.strategy_id
                    ORDER BY r.created_at DESC
                    LIMIT ?
                    """,
                    [limit],
                )
            )
        summaries: list[BacktestSummary] = []
        for row in rows:
            metrics = json.loads(row["metrics_json"] or "{}")
            summaries.append(
                BacktestSummary(
                    id=row["id"],
                    strategy_id=row["strategy_id"],
                    strategy_name=row["strategy_name"],
                    symbol=row["symbol"],
                    timeframe=row["timeframe"],
                    start_at=row["start_at"],
                    end_at=row["end_at"],
                    status=row["status"],
                    final_equity=metrics.get("final_equity"),
                    total_return_pct=metrics.get("total_return_pct"),
                    trade_count=metrics.get("trade_count"),
                    created_at=row["created_at"],
                )
            )
        return summaries

    def delete(self, run_id: str) -> bool:
        with connection(self.settings) as con:
            rows = rows_to_dicts(
                con.execute(
                    "SELECT strategy_id FROM backtest_runs WHERE id = ?",
                    [run_id],
                )
            )
            if not rows:
                return False
            strategy_id = rows[0]["strategy_id"]
            con.execute("DELETE FROM trades WHERE run_id = ?", [run_id])
            con.execute("DELETE FROM markers WHERE run_id = ?", [run_id])
            con.execute("DELETE FROM backtest_runs WHERE id = ?", [run_id])
            con.execute(
                "DELETE FROM strategies WHERE id = ? AND file_path IS NULL",
                [strategy_id],
            )
        return True

    def _store_run(
        self,
        run_id: str,
        strategy_id: str,
        request: BacktestRequest,
        status: str,
        metrics: dict[str, Any],
        equity_curve: list[dict[str, Any]],
        trades: list[Trade],
        markers: list[Marker],
        error: str | None,
        stdout_text: str | None,
        stderr_text: str | None,
        debug: Any | None,
        environment: dict[str, Any] | None,
        runtime_seconds: float | None,
        timeout_seconds: int | None,
        created_at: datetime,
    ) -> None:
        with connection(self.settings) as con:
            con.execute(
                """
                INSERT INTO strategies (id, name, code, file_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    strategy_id,
                    request.strategy_name,
                    request.code,
                    None,
                    as_utc_naive(created_at),
                    as_utc_naive(created_at),
                ],
            )
            con.execute(
                """
                INSERT INTO backtest_runs
                (id, strategy_id, symbol, timeframe, start_at, end_at, status,
                 initial_cash, commission_pct, metrics_json, equity_curve_json,
                 error, stdout_text, stderr_text, debug_json, environment_json,
                 runtime_seconds, timeout_seconds, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    strategy_id,
                    request.symbol.upper(),
                    request.timeframe,
                    as_utc_naive(request.start),
                    as_utc_naive(request.end),
                    status,
                    request.initial_cash,
                    request.commission_pct,
                    json.dumps(metrics),
                    json.dumps(equity_curve),
                    error,
                    stdout_text,
                    stderr_text,
                    json.dumps(debug) if debug is not None else None,
                    json.dumps(environment) if environment is not None else None,
                    runtime_seconds,
                    timeout_seconds,
                    as_utc_naive(created_at),
                ],
            )
            if trades:
                con.executemany(
                    """
                    INSERT INTO trades
                    (id, run_id, symbol, side, entry_time, exit_time, entry_price,
                     exit_price, quantity, pnl, return_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        [
                            trade.id,
                            trade.run_id,
                            trade.symbol,
                            trade.side,
                            as_utc_naive(trade.entry_time),
                            as_utc_naive(trade.exit_time) if trade.exit_time else None,
                            trade.entry_price,
                            trade.exit_price,
                            trade.quantity,
                            trade.pnl,
                            trade.return_pct,
                        ]
                        for trade in trades
                    ],
                )
            if markers:
                con.executemany(
                    """
                    INSERT INTO markers
                    (id, run_id, symbol, timestamp, marker_type, label, color,
                     price, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
                    """,
                    [
                        [
                            marker.id or str(uuid.uuid4()),
                            run_id,
                            marker.symbol,
                            as_utc_naive(marker.timestamp),
                            marker.marker_type,
                            marker.label,
                            marker.color,
                            marker.price,
                            marker.source,
                        ]
                        for marker in markers
                    ],
                )


def simulate_long_only(
    bars: list[Bar],
    entries: list[bool],
    exits: list[bool],
    initial_cash: float,
    commission_pct: float,
    run_id: str,
    symbol: str,
    position_size_cash: float | None = None,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> dict[str, Any]:
    cash = float(initial_cash)
    quantity = 0.0
    entry_price = 0.0
    entry_time: datetime | None = None
    entry_fee = 0.0
    trades: list[Trade] = []
    markers: list[Marker] = []
    equity_curve: list[dict[str, Any]] = []
    entries = _pad_bool(entries, len(bars))
    exits = _pad_bool(exits, len(bars))

    for index, bar in enumerate(bars):
        price = bar.close
        if quantity == 0 and entries[index]:
            buying_power = min(cash, position_size_cash or cash)
            quantity = buying_power / (price * (1 + commission_pct))
            gross = quantity * price
            entry_fee = gross * commission_pct
            cash -= gross + entry_fee
            entry_price = price
            entry_time = bar.timestamp
            markers.append(
                Marker(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    symbol=symbol,
                    timestamp=bar.timestamp,
                    marker_type="buy",
                    label="Buy",
                    color="#0f9f6e",
                    price=price,
                    source="strategy",
                )
            )
        elif quantity > 0:
            stop_price = entry_price * (1 - (stop_loss_pct or 0) / 100) if stop_loss_pct else None
            target_price = entry_price * (1 + (take_profit_pct or 0) / 100) if take_profit_pct else None
            exit_price = price
            exit_label = "Sell"
            exit_color = "#d64545"
            should_exit = False
            if stop_price is not None and bar.low <= stop_price:
                exit_price = stop_price
                exit_label = "Stop"
                exit_color = "#a03232"
                should_exit = True
            elif target_price is not None and bar.high >= target_price:
                exit_price = target_price
                exit_label = "Take profit"
                exit_color = "#0f766e"
                should_exit = True
            elif exits[index]:
                should_exit = True

            if not should_exit:
                equity = cash + quantity * price
                equity_curve.append({"timestamp": isoformat_utc(bar.timestamp), "equity": round(equity, 4)})
                continue

            gross = quantity * exit_price
            exit_fee = gross * commission_pct
            cash += gross - exit_fee
            pnl = (exit_price - entry_price) * quantity - entry_fee - exit_fee
            return_pct = ((exit_price / entry_price) - 1 - (commission_pct * 2)) * 100
            trade = Trade(
                id=str(uuid.uuid4()),
                run_id=run_id,
                symbol=symbol,
                side="long",
                entry_time=entry_time or bar.timestamp,
                exit_time=bar.timestamp,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                pnl=pnl,
                return_pct=return_pct,
            )
            trades.append(trade)
            markers.append(
                Marker(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    symbol=symbol,
                    timestamp=bar.timestamp,
                    marker_type="sell",
                    label=exit_label,
                    color=exit_color,
                    price=exit_price,
                    source="strategy",
                )
            )
            quantity = 0.0
            entry_price = 0.0
            entry_time = None
            entry_fee = 0.0
        equity = cash + quantity * price
        equity_curve.append({"timestamp": isoformat_utc(bar.timestamp), "equity": round(equity, 4)})

    final_equity = equity_curve[-1]["equity"] if equity_curve else initial_cash
    metrics = calculate_metrics(bars, equity_curve, trades, initial_cash, final_equity)
    metrics.update(
        {
            "initial_cash": round(float(initial_cash), 2),
            "position_size_cash": round(float(position_size_cash), 2) if position_size_cash else None,
            "stop_loss_pct": round(float(stop_loss_pct), 2) if stop_loss_pct is not None else None,
            "take_profit_pct": round(float(take_profit_pct), 2) if take_profit_pct is not None else None,
        }
    )
    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
        "markers": markers,
    }


def calculate_metrics(
    bars: list[Bar],
    equity_curve: list[dict[str, Any]],
    trades: list[Trade],
    initial_cash: float,
    final_equity: float,
) -> dict[str, Any]:
    equities = np.array([point["equity"] for point in equity_curve], dtype=float)
    returns = np.diff(equities) / equities[:-1] if len(equities) > 1 else np.array([])
    peak = np.maximum.accumulate(equities) if len(equities) else np.array([initial_cash])
    drawdowns = (equities - peak) / peak if len(equities) else np.array([0.0])
    wins = [trade for trade in trades if trade.pnl > 0]
    sharpe = 0.0
    if len(returns) > 1 and float(np.std(returns)) > 0:
        sharpe = float((np.mean(returns) / np.std(returns)) * math.sqrt(252))
    buy_hold = 0.0
    if len(bars) > 1 and bars[0].close:
        buy_hold = ((bars[-1].close / bars[0].close) - 1) * 100
    return {
        "final_equity": round(float(final_equity), 2),
        "total_return_pct": round(((final_equity / initial_cash) - 1) * 100, 2),
        "buy_hold_return_pct": round(float(buy_hold), 2),
        "max_drawdown_pct": round(float(drawdowns.min() * 100), 2) if len(drawdowns) else 0.0,
        "trade_count": len(trades),
        "win_rate_pct": round((len(wins) / len(trades)) * 100, 2) if trades else 0.0,
        "sharpe": round(sharpe, 3),
    }


def normalize_strategy_markers(
    raw_markers: list[dict[str, Any]],
    symbol: str,
    run_id: str,
    bars: list[Bar],
) -> list[Marker]:
    if not raw_markers:
        return []
    first_timestamp = bars[0].timestamp if bars else utc_now()
    markers: list[Marker] = []
    for raw in raw_markers:
        timestamp = raw.get("timestamp") or raw.get("time") or first_timestamp
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        markers.append(
            Marker(
                id=str(uuid.uuid4()),
                run_id=run_id,
                symbol=symbol,
                timestamp=timestamp,
                marker_type=str(raw.get("type") or raw.get("marker_type") or "note"),
                label=str(raw.get("label") or "Marker"),
                color=str(raw.get("color") or "#d6a419"),
                price=float(raw["price"]) if raw.get("price") is not None else None,
                source="strategy",
            )
        )
    return markers


def _pad_bool(values: list[bool], n: int) -> list[bool]:
    normalized = [bool(value) for value in values[:n]]
    if len(normalized) < n:
        normalized.extend([False] * (n - len(normalized)))
    return normalized
