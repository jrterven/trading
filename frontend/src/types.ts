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
  available_at?: string | null;
  content?: string | null;
  raw_symbols: string[];
  relation_type: 'direct' | 'indirect';
  relevance_score: number;
  relation_reason?: string | null;
  classifier_model?: string | null;
  classifier_version?: string | null;
}

export interface NewsFetchSummary {
  total: number;
  fetched: number;
  existing: number;
  new: number;
  daily: {
    max?: { date: string; count: number } | null;
    min?: { date: string; count: number } | null;
    average: number;
  };
  market_data?: MarketDataFetchSummary | null;
}

export interface NewsFetchResponse {
  articles: NewsArticle[];
  summary: NewsFetchSummary;
}

export interface MarketDataTimeframeSummary {
  timeframe: string;
  total: number;
  fetched: number;
  new: number;
  existing: number;
  failed_windows: number;
}

export interface MarketDataFetchSummary {
  symbol: string;
  start: string;
  end: string;
  timeframes: MarketDataTimeframeSummary[];
}

export interface DatasetBarCoverage {
  timeframe: string;
  count: number;
  start?: string | null;
  end?: string | null;
}

export interface DatasetSummaryRow {
  symbol: string;
  news_count: number;
  news_start?: string | null;
  news_end?: string | null;
  sentiment_count: number;
  sentiment_coverage_pct: number;
  bars: DatasetBarCoverage[];
  has_news: boolean;
  has_sentiment: boolean;
  has_ohlcv: boolean;
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
  model_version?: string | null;
  prompt_version?: string | null;
  explanation?: string | null;
  created_at: string;
}

export type NewsSortMode = 'chronological' | 'positive' | 'negative';
export type NewsChartMode = 'none' | 'all' | 'influential';

export interface NewsChartMarker {
  article_id: string;
  timestamp: string;
  label: string;
  sentiment: 'positive' | 'negative' | 'neutral';
  score: number;
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
