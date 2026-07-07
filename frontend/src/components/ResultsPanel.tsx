import { Activity, AlertTriangle, Code2, FileText, History, TrendingUp } from 'lucide-react';

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
          <h2>Results</h2>
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
        <Metric label="Return" value={formatPercent(metrics.total_return_pct)} />
        <Metric label="Buy&Hold" value={formatPercent(metrics.buy_hold_return_pct)} />
        <Metric label="Drawdown" value={formatPercent(metrics.max_drawdown_pct)} />
        <Metric label="Trades" value={formatNumber(metrics.trade_count, 0)} />
        <Metric label="Sharpe" value={formatNumber(metrics.sharpe, 3)} />
      </div>

      {run?.equity_curve?.length ? <EquitySparkline run={run} /> : <div className="empty-state">No run</div>}

      {run?.strategy_code && (
        <div className="result-actions">
          <button className="secondary-action" onClick={() => onLoadRunCode(run)}>
            <Code2 size={15} />
            <span>Load used code</span>
          </button>
        </div>
      )}

      {run && <LogsDebug run={run} />}

      <div className="trade-table">
        <div className="table-heading">
          <Activity size={15} />
          <span>Trades</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Entry</th>
              <th>Exit</th>
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
          <span>History</span>
        </div>
        {history.map((item) => (
          <button key={item.id} className="history-row" onClick={() => onLoadRun(item.id)}>
            <strong>{item.strategy_name}</strong>
            <span>
              {item.symbol} {item.timeframe}
            </span>
            <span className={item.status === 'completed' ? 'positive-text' : 'negative-text'}>
              {item.status === 'completed' ? formatPercent(item.total_return_pct) : 'failed'}
            </span>
          </button>
        ))}
        {history.length === 0 && <div className="empty-state">No saved history</div>}
      </div>
    </section>
  );
}

function LogsDebug({ run }: { run: BacktestRun }) {
  const debugText = run.debug === undefined || run.debug === null ? '' : JSON.stringify(run.debug, null, 2);
  const hasLogs = Boolean(run.stdout_text || run.stderr_text || debugText || run.runtime_seconds || run.timeout_seconds);
  if (!hasLogs) return null;

  return (
    <details className="logs-debug">
      <summary>
        <FileText size={15} />
        <span>Logs / Debug</span>
      </summary>
      <div className="log-meta">
        {run.runtime_seconds !== null && run.runtime_seconds !== undefined && (
          <span>runtime {formatNumber(run.runtime_seconds, 2)}s</span>
        )}
        {run.timeout_seconds && <span>timeout {run.timeout_seconds}s</span>}
        {run.environment?.python_executable && <span title={run.environment.python_executable}>Python {run.environment.python_version}</span>}
      </div>
      {run.stdout_text && (
        <LogBlock title="stdout" value={run.stdout_text} />
      )}
      {run.stderr_text && (
        <LogBlock title="stderr" value={run.stderr_text} />
      )}
      {debugText && (
        <LogBlock title="debug" value={debugText} />
      )}
    </details>
  );
}

function LogBlock({ title, value }: { title: string; value: string }) {
  return (
    <div className="log-block">
      <span>{title}</span>
      <pre>{value}</pre>
    </div>
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
