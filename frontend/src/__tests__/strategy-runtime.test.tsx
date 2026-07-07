import { fireEvent, render, screen } from '@testing-library/react';
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

    render(
      <StrategyEditor
        strategyName="SMA"
        code="def run(ctx): return {}"
        running={false}
        saving={false}
        strategies={[]}
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

    render(<ResultsPanel run={run} history={[]} onLoadRun={vi.fn()} onLoadRunCode={vi.fn()} />);

    fireEvent.click(screen.getByText('Logs / Debug'));

    expect(screen.getByText('hello from strategy')).toBeInTheDocument();
    expect(screen.getByText(/"bars": 10/)).toBeInTheDocument();
    expect(screen.getByText('timeout 30s')).toBeInTheDocument();
  });
});
