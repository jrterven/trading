import { Send, WalletCards } from 'lucide-react';
import { useState } from 'react';

import { formatCurrency, formatNumber } from '../lib/format';
import type { PaperPortfolio } from '../types';

interface Props {
  symbol: string;
  portfolio: PaperPortfolio | null;
  onOrder: (side: 'buy' | 'sell', quantity: number) => void;
}

export function PaperPanel({ symbol, portfolio, onOrder }: Props) {
  const [quantity, setQuantity] = useState(1);
  const activePositions = portfolio?.positions.filter((position) => position.symbol === symbol) ?? [];
  const otherPositions = portfolio?.positions.filter((position) => position.symbol !== symbol) ?? [];
  const activeMarketValue = activePositions.reduce((total, position) => total + position.market_value, 0);
  const safeQuantity = Math.max(0, quantity || 0);

  return (
    <section className="side-panel paper-panel">
      <div className="panel-titlebar">
        <div>
          <p className="eyebrow">Paper</p>
          <h2>Portafolio</h2>
        </div>
        <WalletCards size={18} />
      </div>

      <div className="paper-order">
        <input
          type="number"
          min="0"
          step="1"
          value={quantity}
          onChange={(event) => setQuantity(Number(event.target.value))}
        />
        <button onClick={() => onOrder('buy', safeQuantity)} disabled={safeQuantity <= 0}>
          <Send size={15} />
          <span>Comprar {symbol}</span>
        </button>
        <button className="secondary-action" onClick={() => onOrder('sell', safeQuantity)} disabled={safeQuantity <= 0}>
          <Send size={15} />
          <span>Vender</span>
        </button>
      </div>

      <div className="portfolio-total">
        <span>Equity Alpaca</span>
        <strong>{formatCurrency(portfolio?.equity ?? portfolio?.market_value)}</strong>
      </div>

      <div className="portfolio-balance">
        <span>Cash {formatCurrency(portfolio?.cash)}</span>
        <span>Buying power {formatCurrency(portfolio?.buying_power)}</span>
      </div>

      <div className="positions-list">
        <div className="portfolio-subheading">{symbol}</div>
        {activePositions.map((position) => (
          <div key={position.symbol} className="position-row">
            <strong>{position.symbol}</strong>
            <span>{formatNumber(position.quantity, 4)} sh</span>
            <span>{formatCurrency(position.market_value)}</span>
          </div>
        ))}
        {!activePositions.length && (
          <div className="position-row muted-row">
            <strong>{symbol}</strong>
            <span>0 sh</span>
            <span>{formatCurrency(activeMarketValue)}</span>
          </div>
        )}

        {otherPositions.length > 0 && (
          <>
            <div className="portfolio-subheading">Otras posiciones</div>
            {otherPositions.map((position) => (
              <div key={position.symbol} className="position-row secondary-row">
                <strong>{position.symbol}</strong>
                <span>{formatNumber(position.quantity, 4)} sh</span>
                <span>{formatCurrency(position.market_value)}</span>
              </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}
