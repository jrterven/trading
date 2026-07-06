import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Controls } from '../components/Controls';

const baseProps = {
  symbol: 'AAPL',
  timeframe: '1Day',
  start: '2026-01-01',
  end: '2026-07-05',
  loading: false,
  onSymbolChange: vi.fn(),
  onTimeframeChange: vi.fn(),
  onStartChange: vi.fn(),
  onEndChange: vi.fn(),
  onRefresh: vi.fn(),
  onPreset: vi.fn(),
  onYearPreset: vi.fn(),
};

describe('Controls', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows ticker dropdown options with company names', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          { symbol: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ', tradable: true },
          { symbol: 'MSFT', name: 'Microsoft Corporation', exchange: 'NASDAQ', tradable: true },
        ],
      }),
    );
    const onSymbolChange = vi.fn();

    render(<Controls {...baseProps} onSymbolChange={onSymbolChange} />);

    await waitFor(() => expect(screen.getByRole('option', { name: 'AAPL - Apple Inc.' })).toBeInTheDocument());
    expect(screen.getByRole('option', { name: 'NVDA - NVIDIA Corporation' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: 'MSFT' } });

    expect(screen.getByRole('option', { name: 'MSFT - Microsoft Corporation' })).toBeInTheDocument();
    expect(onSymbolChange).toHaveBeenCalledWith('MSFT');
  });

  it('searches tickers through the API', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ symbol: 'MSFT', name: 'Microsoft Corporation', exchange: 'NASDAQ', tradable: true }],
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<Controls {...baseProps} />);

    fireEvent.change(screen.getByLabelText('Buscar ticker'), { target: { value: 'Microsoft' } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('q=Microsoft'), expect.anything()));
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'MSFT - Microsoft Corporation' })).toBeInTheDocument(),
    );
  });

  it('limits date pickers to the supported historical window', () => {
    render(<Controls {...baseProps} />);

    const [startInput, endInput] = screen.getAllByDisplayValue(/2026-/);
    expect(startInput).toHaveAttribute('max');
    expect(startInput).toHaveAttribute('min');
    expect(endInput).toHaveAttribute('max');
    expect(endInput).toHaveAttribute('min');
    expect((startInput.getAttribute('min') ?? '') < '2026-01-01').toBe(true);
    expect(endInput.getAttribute('max')).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
