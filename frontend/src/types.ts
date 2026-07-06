export interface SymbolResult {
  symbol: string;
  name: string;
  exchange?: string | null;
  tradable: boolean;
}

export interface Bar {
  symbol: string;
  timeframe: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  source: string;
}

export interface NewsArticle {
  id: string;
  source: string;
  symbol: string;
  headline: string;
  summary?: string | null;
  url?: string | null;
  author?: string | null;
  published_at: string;
  content?: string | null;
  raw_symbols: string[];
}

export interface SentimentScore {
  id: string;
  article_id: string;
  symbol: string;
  label: 'positive' | 'neutral' | 'negative';
  score: number;
  positive: number;
  neutral: number;
  negative: number;
  model: string;
  explanation?: string | null;
  created_at: string;
}

export interface Marker {
  id?: string | null;
  run_id?: string | null;
  symbol: string;
  timestamp: string;
  marker_type: string;
  label: string;
  color: string;
  price?: number | null;
  source: string;
}

export interface Trade {
  id: string;
  run_id: string;
  symbol: string;
  side: 'long';
  entry_time: string;
  exit_time?: string | null;
  entry_price: number;
  exit_price?: number | null;
  quantity: number;
  pnl: number;
  return_pct: number;
}

export interface BacktestRun {
  id: string;
  strategy_id: string;
  strategy_name?: string | null;
  strategy_code?: string | null;
  symbol: string;
  timeframe: string;
  start_at: string;
  end_at: string;
  status: 'completed' | 'failed';
  initial_cash: number;
  commission_pct: number;
  metrics: Record<string, number | null>;
  equity_curve: Array<{ timestamp: string; equity: number }>;
  trades: Trade[];
  markers: Marker[];
  error?: string | null;
  created_at: string;
}

export interface BacktestSummary {
  id: string;
  strategy_id: string;
  strategy_name: string;
  symbol: string;
  timeframe: string;
  status: 'completed' | 'failed';
  final_equity?: number | null;
  total_return_pct?: number | null;
  trade_count?: number | null;
  created_at: string;
}

export interface StrategyRecord {
  id: string;
  name: string;
  code: string;
  file_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaperPortfolio {
  positions: Array<{
    symbol: string;
    quantity: number;
    avg_cost: number;
    last_price: number;
    market_value: number;
    unrealized_pnl: number;
  }>;
  orders: Array<{
    id: string;
    symbol: string;
    side: 'buy' | 'sell';
    quantity: number;
    price: number;
    status: string;
    created_at: string;
  }>;
  market_value: number;
  equity?: number;
  cash?: number;
  buying_power?: number;
  currency?: string;
  trading_blocked?: boolean;
}
