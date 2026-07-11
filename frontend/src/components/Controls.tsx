import { CalendarDays, RefreshCw, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { api } from '../api';
import { toDateInput } from '../lib/format';
import type { AssetClass, SymbolResult } from '../types';

interface Props {
  assetClass: AssetClass;
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  loading: boolean;
  onSymbolChange: (symbol: string) => void;
  onTimeframeChange: (timeframe: string) => void;
  onStartChange: (start: string) => void;
  onEndChange: (end: string) => void;
  onRefresh: () => void;
  onPreset: (days: number) => void;
  onYearPreset: (years: number) => void;
  onAssetClassChange: (assetClass: AssetClass) => void;
}

const timeframes = ['1Min', '5Min', '15Min', '1Hour', '1Day'];
const popularSymbols: SymbolResult[] = [
  { symbol: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ', tradable: true },
  { symbol: 'MSFT', name: 'Microsoft Corporation', exchange: 'NASDAQ', tradable: true },
  { symbol: 'NVDA', name: 'NVIDIA Corporation', exchange: 'NASDAQ', tradable: true },
  { symbol: 'TSLA', name: 'Tesla, Inc.', exchange: 'NASDAQ', tradable: true },
  { symbol: 'AMZN', name: 'Amazon.com, Inc.', exchange: 'NASDAQ', tradable: true },
  { symbol: 'META', name: 'Meta Platforms, Inc.', exchange: 'NASDAQ', tradable: true },
  { symbol: 'GOOGL', name: 'Alphabet Inc.', exchange: 'NASDAQ', tradable: true },
  { symbol: 'AMD', name: 'Advanced Micro Devices, Inc.', exchange: 'NASDAQ', tradable: true },
  { symbol: 'AVGO', name: 'Broadcom Inc.', exchange: 'NASDAQ', tradable: true },
  { symbol: 'NFLX', name: 'Netflix, Inc.', exchange: 'NASDAQ', tradable: true },
  { symbol: 'JPM', name: 'JPMorgan Chase & Co.', exchange: 'NYSE', tradable: true },
  { symbol: 'SPY', name: 'SPDR S&P 500 ETF Trust', exchange: 'NYSEARCA', tradable: true },
  { symbol: 'QQQ', name: 'Invesco QQQ Trust', exchange: 'NASDAQ', tradable: true },
];
const popularCryptoSymbols: SymbolResult[] = [
  { symbol: 'BTC/USD', name: 'Bitcoin / US Dollar', exchange: 'Alpaca Crypto', tradable: true },
  { symbol: 'ETH/USD', name: 'Ethereum / US Dollar', exchange: 'Alpaca Crypto', tradable: true },
  { symbol: 'SOL/USD', name: 'Solana / US Dollar', exchange: 'Alpaca Crypto', tradable: true },
  { symbol: 'XRP/USD', name: 'XRP / US Dollar', exchange: 'Alpaca Crypto', tradable: true },
  { symbol: 'DOGE/USD', name: 'Dogecoin / US Dollar', exchange: 'Alpaca Crypto', tradable: true },
  { symbol: 'ADA/USD', name: 'Cardano / US Dollar', exchange: 'Alpaca Crypto', tradable: true },
  { symbol: 'AVAX/USD', name: 'Avalanche / US Dollar', exchange: 'Alpaca Crypto', tradable: true },
  { symbol: 'LINK/USD', name: 'Chainlink / US Dollar', exchange: 'Alpaca Crypto', tradable: true },
];

function mergeSymbols(items: SymbolResult[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.symbol)) return false;
    seen.add(item.symbol);
    return true;
  });
}

function marketDateBounds(assetClass: AssetClass) {
  const max = new Date();
  const min = new Date(max);
  if (assetClass === 'crypto') {
    min.setFullYear(2021, 0, 1);
  } else {
    min.setFullYear(min.getFullYear() - 9);
  }
  return {
    min: toDateInput(min),
    max: toDateInput(max),
  };
}

export function Controls({
  assetClass,
  symbol,
  timeframe,
  start,
  end,
  loading,
  onSymbolChange,
  onTimeframeChange,
  onStartChange,
  onEndChange,
  onRefresh,
  onPreset,
  onYearPreset,
  onAssetClassChange,
}: Props) {
  const [symbolQuery, setSymbolQuery] = useState('');
  const popularOptions = assetClass === 'crypto' ? popularCryptoSymbols : popularSymbols;
  const [symbolOptions, setSymbolOptions] = useState<SymbolResult[]>(popularOptions);
  const dateBounds = useMemo(() => marketDateBounds(assetClass), [assetClass]);

  useEffect(() => {
    setSymbolQuery('');
    setSymbolOptions(popularOptions);
  }, [assetClass, popularOptions]);

  useEffect(() => {
    let cancelled = false;
    const query = symbolQuery.trim();
    if (query.length < 2) {
      setSymbolOptions(popularOptions);
      return () => {
        cancelled = true;
      };
    }

    const timer = window.setTimeout(() => {
      api
        .searchSymbols(query, assetClass)
        .then((matches) => {
          if (!cancelled) setSymbolOptions(matches.length ? matches : popularOptions);
        })
        .catch(() => {
          if (!cancelled) setSymbolOptions(popularOptions);
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [assetClass, popularOptions, symbolQuery]);

  useEffect(() => {
    let cancelled = false;
    api
      .searchSymbols(symbol, assetClass)
      .then((matches) => {
        if (!cancelled && matches.length) {
          setSymbolOptions((current) => mergeSymbols([...matches, ...current]));
        }
      })
      .catch(() => {
        if (!cancelled) setSymbolOptions(popularOptions);
      });
    return () => {
      cancelled = true;
    };
  }, [assetClass, popularOptions, symbol]);

  const dropdownOptions = useMemo(() => {
    const options = symbolOptions.some((item) => item.symbol === symbol)
      ? symbolOptions
      : [{ symbol, name: symbol, tradable: true }, ...symbolOptions];
    return mergeSymbols(options);
  }, [symbol, symbolOptions]);

  return (
    <div className="control-strip">
      <div className="asset-control">
        <label>Asset</label>
        <div className="asset-toggle" role="group" aria-label="Asset class">
          <button
            type="button"
            className={assetClass === 'stock' ? 'active' : ''}
            onClick={() => onAssetClassChange('stock')}
          >
            Stocks
          </button>
          <button
            type="button"
            className={assetClass === 'crypto' ? 'active' : ''}
            onClick={() => onAssetClassChange('crypto')}
          >
            Crypto
          </button>
        </div>
      </div>
      <div className="symbol-control">
        <label htmlFor="symbol-select">Symbol</label>
        <div className="symbol-search">
          <Search size={15} />
          <input
            aria-label="Search symbol"
            placeholder={assetClass === 'crypto' ? 'BTC, Ethereum' : 'NVDA, Microsoft'}
            value={symbolQuery}
            onChange={(event) => setSymbolQuery(event.target.value)}
          />
        </div>
        <select
          id="symbol-select"
          className="symbol-select"
          value={symbol}
          onChange={(event) => {
            onSymbolChange(event.target.value);
            setSymbolQuery('');
          }}
        >
          {dropdownOptions.map((item) => (
            <option key={item.symbol} value={item.symbol}>
              {item.symbol} - {item.name}
            </option>
          ))}
        </select>
      </div>

      <div className="field-group">
        <label>Timeframe</label>
        <select value={timeframe} onChange={(event) => onTimeframeChange(event.target.value)}>
          {timeframes.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </div>

      <div className="segmented" aria-label="Ranges">
        <button onClick={() => onPreset(30)}>30D</button>
        <button onClick={() => onPreset(90)}>90D</button>
        <button onClick={() => onYearPreset(1)}>1Y</button>
        <button onClick={() => onYearPreset(3)}>3Y</button>
        <button onClick={() => onYearPreset(5)}>5Y</button>
        <button onClick={() => onYearPreset(9)}>9Y</button>
      </div>

      <div className="date-range">
        <CalendarDays size={17} />
        <input
          type="date"
          min={dateBounds.min}
          max={dateBounds.max}
          value={start}
          onChange={(event) => onStartChange(event.target.value)}
        />
        <input
          type="date"
          min={dateBounds.min}
          max={dateBounds.max}
          value={end}
          onChange={(event) => onEndChange(event.target.value)}
        />
      </div>

      <button className="primary-action" onClick={onRefresh} disabled={loading}>
        <RefreshCw size={16} className={loading ? 'spin' : ''} />
        <span>Refresh</span>
      </button>
    </div>
  );
}
