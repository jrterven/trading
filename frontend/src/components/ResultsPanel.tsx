import { Activity, AlertTriangle, Code2, History, TrendingUp } from 'lucide-react';

import { formatCurrency, formatNumber, formatPercent } from '../lib/format';
import type { BacktestRun, BacktestSummary } from '../types';

interface Props {
  run: BacktestRun | null;
  history: BacktestSummary[];
  onLoadRun: (id: string) => void;
  onLoadRunCode: (run: BacktestRun) => void;
}

export function ResultsPanel({ run, history, onLoadRun, onLoadRunCode }: Props) {
  const metrics = run?.metrics ?? {};
  return (
    <section className="side-panel results-panel">
      <div className="panel-titlebar">
        <div>
          <p className="eyebrow">Backtest</p>
          <h2>Resultados</h2>
        </div>
        {run?.status === 'failed' ? (
          <AlertTriangle size={18} className="danger-icon" />
        ) : (
          <TrendingUp size={18} className="success-icon" />
        )}
      </div>

      {run?.error && <div className="error-box">{run.error}</div>}

      <div className="metric-grid">
        <Metric label="Equity" value={formatCurrency(metrics.final_equity)} />
        <Metric label="Retorno" value={formatPercent(metrics.total_return_pct)} />
        <Metric label="Buy&Hold" value={formatPercent(metrics.buy_hold_return_pct)} />
        <Metric label="Drawdown" value={formatPercent(metrics.max_drawdown_pct)} />
        <Metric label="Trades" value={formatNumber(metrics.trade_count, 0)} />
        <Metric label="Sharpe" value={formatNumber(metrics.sharpe, 3)} />
      </div>

      {run?.equity_curve?.length ? <EquitySparkline run={run} /> : <div className="empty-state">Sin corrida</div>}

      {run?.strategy_code && (
        <div className="result-actions">
          <button className="secondary-action" onClick={() => onLoadRunCode(run)}>
            <Code2 size={15} />
            <span>Cargar codigo usado</span>
          </button>
        </div>
      )}

      <div className="trade-table">
        <div className="table-heading">
          <Activity size={15} />
          <span>Trades</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Entrada</th>
              <th>Salida</th>
              <th>PnL</th>
            </tr>
          </thead>
          <tbody>
            {run?.trades.map((trade) => (
              <tr key={trade.id}>
                <td>{formatCurrency(trade.entry_price)}</td>
                <td>{formatCurrency(trade.exit_price)}</td>
                <td className={trade.pnl >= 0 ? 'positive-text' : 'negative-text'}>
                  {formatCurrency(trade.pnl)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="history-list">
        <div className="table-heading">
          <History size={15} />
          <span>Historial</span>
        </div>
        {history.map((item) => (
          <button key={item.id} className="history-row" onClick={() => onLoadRun(item.id)}>
            <strong>{item.strategy_name}</strong>
            <span>
              {item.symbol} {item.timeframe}
            </span>
            <span className={item.status === 'completed' ? 'positive-text' : 'negative-text'}>
              {item.status === 'completed' ? formatPercent(item.total_return_pct) : 'fallo'}
            </span>
          </button>
        ))}
        {history.length === 0 && <div className="empty-state">Sin historial guardado</div>}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function EquitySparkline({ run }: { run: BacktestRun }) {
  const values = run.equity_curve.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * 100;
      const y = 42 - ((value - min) / range) * 36;
      return `${x},${y}`;
    })
    .join(' ');
  return (
    <svg className="sparkline" viewBox="0 0 100 48" preserveAspectRatio="none">
      <polyline points={points} fill="none" stroke="#0f766e" strokeWidth="2" />
    </svg>
  );
}
