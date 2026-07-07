import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DatasetPanel } from '../components/DatasetPanel';
import type { DatasetSummaryRow } from '../types';

const rows: DatasetSummaryRow[] = [
  {
    symbol: 'AAPL',
    news_count: 2,
    news_start: '2026-01-01T00:00:00Z',
    news_end: '2026-01-02T00:00:00Z',
    sentiment_count: 1,
    sentiment_coverage_pct: 50,
    has_news: true,
    has_sentiment: true,
    has_ohlcv: true,
    bars: [
      { timeframe: '1Min', count: 0 },
      { timeframe: '5Min', count: 0 },
      { timeframe: '15Min', count: 0 },
      { timeframe: '1Hour', count: 3, start: '2026-01-01T14:00:00Z', end: '2026-01-01T16:00:00Z' },
      { timeframe: '1Day', count: 2, start: '2026-01-01T00:00:00Z', end: '2026-01-02T00:00:00Z' },
    ],
  },
  {
    symbol: 'MSFT',
    news_count: 0,
    sentiment_count: 0,
    sentiment_coverage_pct: 0,
    has_news: false,
    has_sentiment: false,
    has_ohlcv: true,
    bars: [{ timeframe: '1Day', count: 1, start: '2026-01-01T00:00:00Z', end: '2026-01-01T00:00:00Z' }],
  },
];

describe('DatasetPanel', () => {
  it('filters rows and selects a symbol', () => {
    const onSelectSymbol = vi.fn();

    render(<DatasetPanel rows={rows} loading={false} onRefresh={vi.fn()} onSelectSymbol={onSelectSymbol} />);

    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('MSFT')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Filter dataset by ticker'), { target: { value: 'MS' } });

    expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('MSFT'));

    expect(onSelectSymbol).toHaveBeenCalledWith('MSFT');
  });

  it('shows an empty state', () => {
    render(<DatasetPanel rows={[]} loading={false} onRefresh={vi.fn()} onSelectSymbol={vi.fn()} />);

    expect(screen.getByText('No local dataset coverage')).toBeInTheDocument();
  });
});
