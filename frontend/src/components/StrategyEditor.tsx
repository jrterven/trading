import Editor from '@monaco-editor/react';
import { Play, Save } from 'lucide-react';

import type { StrategyRecord } from '../types';

interface Props {
  strategyName: string;
  code: string;
  running: boolean;
  saving: boolean;
  saveMessage?: string | null;
  strategies: StrategyRecord[];
  initialCash: number;
  positionSizeCash: number;
  stopLossPct: number;
  takeProfitPct: number;
  commissionPct: number;
  onStrategyNameChange: (name: string) => void;
  onChange: (code: string) => void;
  onRun: () => void;
  onSave: () => void;
  onLoadStrategy: (strategy: StrategyRecord) => void;
  onInitialCashChange: (value: number) => void;
  onPositionSizeCashChange: (value: number) => void;
  onStopLossPctChange: (value: number) => void;
  onTakeProfitPctChange: (value: number) => void;
  onCommissionPctChange: (value: number) => void;
}

export function StrategyEditor({
  strategyName,
  code,
  running,
  saving,
  saveMessage,
  strategies,
  initialCash,
  positionSizeCash,
  stopLossPct,
  takeProfitPct,
  commissionPct,
  onStrategyNameChange,
  onChange,
  onRun,
  onSave,
  onLoadStrategy,
  onInitialCashChange,
  onPositionSizeCashChange,
  onStopLossPctChange,
  onTakeProfitPctChange,
  onCommissionPctChange,
}: Props) {
  return (
    <section className="editor-panel">
      <div className="panel-titlebar">
        <div>
          <p className="eyebrow">Python</p>
          <h2>Strategy</h2>
        </div>
        <div className="tool-buttons">
          <button className="icon-button" onClick={onSave} disabled={saving} aria-label="Save local strategy">
            <Save size={16} />
          </button>
          <button className="primary-action" onClick={onRun} disabled={running}>
            <Play size={16} />
            <span>{running ? 'Corriendo' : 'Backtest'}</span>
          </button>
        </div>
      </div>
      <div className="strategy-filebar">
        <label>
          Name
          <input
            value={strategyName}
            onChange={(event) => onStrategyNameChange(event.target.value)}
            placeholder="SMA crossover"
          />
        </label>
        <label>
          Saved
          <select
            value=""
            onChange={(event) => {
              const selected = strategies.find((strategy) => strategy.id === event.target.value);
              if (selected) onLoadStrategy(selected);
            }}
          >
            <option value="">Load...</option>
            {strategies.map((strategy) => (
              <option key={strategy.id} value={strategy.id}>
                {strategy.name}
              </option>
            ))}
          </select>
        </label>
        {saveMessage && <span className="save-message">{saveMessage}</span>}
      </div>
      <div className="backtest-settings" aria-label="Backtest parameters">
        <label>
          Capital
          <input
            type="number"
            min="1"
            step="500"
            value={initialCash}
            onChange={(event) => onInitialCashChange(Number(event.target.value))}
          />
        </label>
        <label>
          Trade $
          <input
            type="number"
            min="0"
            step="100"
            value={positionSizeCash}
            onChange={(event) => onPositionSizeCashChange(Number(event.target.value))}
          />
        </label>
        <label>
          Stop %
          <input
            type="number"
            min="0"
            step="0.5"
            value={stopLossPct}
            onChange={(event) => onStopLossPctChange(Number(event.target.value))}
          />
        </label>
        <label>
          Take %
          <input
            type="number"
            min="0"
            step="0.5"
            value={takeProfitPct}
            onChange={(event) => onTakeProfitPctChange(Number(event.target.value))}
          />
        </label>
        <label>
          Commission %
          <input
            type="number"
            min="0"
            step="0.01"
            value={commissionPct}
            onChange={(event) => onCommissionPctChange(Number(event.target.value))}
          />
        </label>
      </div>
      <div className="editor-frame">
        <Editor
          height="100%"
          width="100%"
          language="python"
          theme="vs-dark"
          value={code}
          onChange={(value) => onChange(value ?? '')}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineHeight: 20,
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 4,
            wordWrap: 'on',
          }}
        />
      </div>
    </section>
  );
}
