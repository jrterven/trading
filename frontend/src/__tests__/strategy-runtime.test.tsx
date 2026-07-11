import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ResultsPanel } from '../components/ResultsPanel';
import { StrategyEditor } from '../components/StrategyEditor';
import type { BacktestRun, StrategyEnvironment } from '../types';

vi.mock('@monaco-editor/react', () => ({
  default: ({ value }: { value: string }) => <textarea aria-label="code editor" readOnly value={value} />,
}));

const environment: StrategyEnvironment = {
  python_executable: '/home/juan/miniconda3/envs/trading-lab/bin/python',
  python_version: '3.12.13',
  platform: 'Linux',
  strategy_timeout_seconds: 8,
  packages: {
    pandas: { installed: true, version: '3.0.3' },
    numpy: { installed: true, version: '2.5.1' },
    torch: { installed: true, version: '2.12.1' },
    transformers: { installed: true, version: '5.13.0' },
    vectorbt: { installed: false, version: null },
  },
  cuda_available: true,
  cuda_device_count: 1,
  cuda_device_name: 'NVIDIA Test GPU',
};

describe('strategy runtime UI', () => {
  it('shows runtime details and edits timeout', () => {
    const onTimeoutSecondsChange = vi.fn();
    const onLoadExample = vi.fn();

    render(
      <StrategyEditor
        strategyName="SMA"
        code="def run(ctx): return {}"
        running={false}
        saving={false}
        strategies={[]}
        examples={[
          {
            id: 'rsi',
            name: 'RSI mean reversion',
            description: 'Buys oversold RSI.',
            code: 'def run(ctx): return {}',
          },
        ]}
        initialCash={10000}
        positionSizeCash={1000}
        stopLossPct={5}
        takeProfitPct={10}
        commissionPct={0.1}
        timeoutSeconds={8}
        environment={environment}
        onStrategyNameChange={vi.fn()}
        onChange={vi.fn()}
        onRun={vi.fn()}
        onSave={vi.fn()}
        onLoadStrategy={vi.fn()}
        onLoadExample={onLoadExample}
        onInitialCashChange={vi.fn()}
        onPositionSizeCashChange={vi.fn()}
        onStopLossPctChange={vi.fn()}
        onTakeProfitPctChange={vi.fn()}
        onCommissionPctChange={vi.fn()}
        onTimeoutSecondsChange={onTimeoutSecondsChange}
      />,
    );

    expect(screen.getByText('Python 3.12.13')).toBeInTheDocument();
    expect(screen.getByText('CUDA NVIDIA Test GPU')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Timeout (s)'), { target: { value: '30' } });

    expect(onTimeoutSecondsChange).toHaveBeenCalledWith(30);

    fireEvent.change(screen.getByLabelText('Examples'), { target: { value: 'rsi' } });

    expect(onLoadExample).toHaveBeenCalledWith(expect.objectContaining({ name: 'RSI mean reversion' }));
  });

  it('loads a local Python strategy file into the editor', async () => {
    const onChange = vi.fn();
    const onStrategyNameChange = vi.fn();
    const source = 'import pandas as pd\n\n\ndef run(ctx):\n    return {"entries": [], "exits": []}\n';

    render(
      <StrategyEditor
        strategyName="New strategy"
        code=""
        running={false}
        saving={false}
        strategies={[]}
        examples={[]}
        initialCash={10000}
        positionSizeCash={1000}
        stopLossPct={5}
        takeProfitPct={10}
        commissionPct={0.1}
        timeoutSeconds={8}
        environment={environment}
        onStrategyNameChange={onStrategyNameChange}
        onChange={onChange}
        onRun={vi.fn()}
        onSave={vi.fn()}
        onLoadStrategy={vi.fn()}
        onLoadExample={vi.fn()}
        onInitialCashChange={vi.fn()}
        onPositionSizeCashChange={vi.fn()}
        onStopLossPctChange={vi.fn()}
        onTakeProfitPctChange={vi.fn()}
        onCommissionPctChange={vi.fn()}
        onTimeoutSecondsChange={vi.fn()}
      />,
    );

    const file = new File([source], 'my_strategy.py', { type: 'text/x-python' });
    Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue(source) });
    const input = screen.getByLabelText('Load Python file') as HTMLInputElement;

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(source));
    expect(onStrategyNameChange).toHaveBeenCalledWith('my_strategy');
  });

  it('shows backtest logs and debug output', () => {
    const run: BacktestRun = {
      id: 'run-1',
      strategy_id: 'strategy-1',
      strategy_name: 'SMA',
      strategy_code: 'def run(ctx): return {}',
      symbol: 'AAPL',
      timeframe: '1Day',
      start_at: '2026-01-01T00:00:00Z',
      end_at: '2026-01-10T00:00:00Z',
      status: 'completed',
      initial_cash: 10000,
      commission_pct: 0.001,
      metrics: {},
      equity_curve: [],
      trades: [],
      markers: [],
      stdout_text: 'hello from strategy',
      stderr_text: '',
      debug: { bars: 10 },
      environment,
      runtime_seconds: 1.25,
      timeout_seconds: 30,
      created_at: '2026-01-10T00:00:00Z',
    };

    render(<ResultsPanel run={run} history={[]} onLoadRun={vi.fn()} onDeleteRun={vi.fn()} onLoadRunCode={vi.fn()} />);

    fireEvent.click(screen.getByText('Logs / Debug'));

    expect(screen.getByText('hello from strategy')).toBeInTheDocument();
    expect(screen.getByText(/"bars": 10/)).toBeInTheDocument();
    expect(screen.getByText('timeout 30s')).toBeInTheDocument();
  });

  it('shows negative history returns in red with the backtest date range', () => {
    const onDeleteRun = vi.fn();
    const onLoadRun = vi.fn();

    render(
      <ResultsPanel
        run={null}
        history={[
          {
            id: 'history-1',
            strategy_id: 'strategy-1',
            strategy_name: 'MACD momentum',
            symbol: 'AAPL',
            timeframe: '1Day',
            start_at: '2026-01-01T00:00:00Z',
            end_at: '2026-07-01T00:00:00Z',
            status: 'completed',
            total_return_pct: -12.82,
            created_at: '2026-07-01T00:00:00Z',
          },
        ]}
        onLoadRun={onLoadRun}
        onDeleteRun={onDeleteRun}
        onLoadRunCode={vi.fn()}
      />,
    );

    const returnCell = screen.getByText('-12.82%');

    expect(screen.getByText('01/01/26 - 07/01/26')).toBeInTheDocument();
    expect(returnCell).toHaveClass('negative-text');

    fireEvent.click(screen.getByLabelText('Delete MACD momentum'));

    expect(onDeleteRun).toHaveBeenCalledWith('history-1');
    expect(onLoadRun).not.toHaveBeenCalled();
  });
});
