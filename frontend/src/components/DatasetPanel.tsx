import { Database, RefreshCw, Search } from 'lucide-react';
import { useMemo, useState } from 'react';

import type { DatasetBarCoverage, DatasetSummaryRow } from '../types';

interface Props {
  rows: DatasetSummaryRow[];
  loading: boolean;
  onRefresh: () => void;
  onSelectSymbol: (symbol: string) => void;
}

const timeframes = ['1Min', '5Min', '15Min', '1Hour', '1Day'];

function shortDate(value?: string | null) {
  if (!value) return '--';
  return new Date(value).toLocaleDateString('es-MX', {
    month: 'short',
    day: 'numeric',
    year: '2-digit',
  });
}

function rangeText(start?: string | null, end?: string | null) {
  if (!start || !end) return 'Missing';
  return `${shortDate(start)} - ${shortDate(end)}`;
}

function statusLabel(row: DatasetSummaryRow) {
  if (!row.has_news && !row.has_ohlcv) return 'Missing';
  if (row.has_news && row.sentiment_count < row.news_count) return 'Partial';
  return 'OK';
}

function barForTimeframe(bars: DatasetBarCoverage[], timeframe: string) {
  return bars.find((item) => item.timeframe === timeframe) ?? { timeframe, count: 0 };
}

export function DatasetPanel({ rows, loading, onRefresh, onSelectSymbol }: Props) {
  const [query, setQuery] = useState('');
  const filteredRows = useMemo(() => {
    const needle = query.trim().toUpperCase();
    if (!needle) return rows;
    return rows.filter((row) => row.symbol.includes(needle));
  }, [query, rows]);

  return (
    <section className="side-panel dataset-panel">
      <div className="panel-titlebar">
        <div>
          <p className="eyebrow">Dataset</p>
          <h2>Local coverage</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          onClick={onRefresh}
          disabled={loading}
          aria-label="Refresh dataset summary"
          data-tooltip="Refresh local summary"
        >
          <RefreshCw size={16} className={loading ? 'spin' : ''} />
        </button>
      </div>

      <div className="dataset-toolbar">
        <label>
          <Search size={14} />
          <input
            aria-label="Filter dataset by ticker"
            placeholder="Filter ticker"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      {filteredRows.length === 0 ? (
        <div className="empty-state">
          <Database size={16} />
          No local dataset coverage
        </div>
      ) : (
        <div className="dataset-table-wrap">
          <table className="dataset-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>News</th>
                <th>Sentiment</th>
                {timeframes.map((timeframe) => (
                  <th key={timeframe}>{timeframe}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => {
                const status = statusLabel(row);
                return (
                  <tr key={row.symbol} onClick={() => onSelectSymbol(row.symbol)}>
                    <td>
                      <button type="button" className="dataset-symbol">
                        <strong>{row.symbol}</strong>
                        <span className={`dataset-status ${status.toLowerCase()}`}>{status}</span>
                      </button>
                    </td>
                    <td>
                      <DataCell count={row.news_count} range={rangeText(row.news_start, row.news_end)} />
                    </td>
                    <td>
                      <DataCell
                        count={row.sentiment_count}
                        range={`${row.sentiment_coverage_pct.toFixed(1)}% scored`}
                        tone={row.has_news && row.sentiment_count < row.news_count ? 'partial' : undefined}
                      />
                    </td>
                    {timeframes.map((timeframe) => {
                      const bar = barForTimeframe(row.bars, timeframe);
                      return (
                        <td key={timeframe}>
                          <DataCell count={bar.count} range={rangeText(bar.start, bar.end)} />
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function DataCell({ count, range, tone }: { count: number; range: string; tone?: 'partial' }) {
  return (
    <span className={tone === 'partial' ? 'dataset-cell partial' : 'dataset-cell'}>
      <strong>{count}</strong>
      <em>{range}</em>
    </span>
  );
}
