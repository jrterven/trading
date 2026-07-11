import type {
  BacktestRun,
  Bar,
  DatasetSummaryRow,
  NewsArticle,
  NewsFetchResponse,
  PaperPortfolio,
  SentimentScore,
  BacktestSummary,
  StrategyRecord,
  StrategyEnvironment,
  SymbolResult,
  AssetClass,
} from './types';

const API_BASE = import.meta.env.VITE_API_URL ?? '';
const GET_RETRY_DELAYS_MS = [300, 800, 1500];

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const method = options?.method?.toUpperCase() ?? 'GET';
  const canRetry = method === 'GET';
  for (let attempt = 0; attempt <= (canRetry ? GET_RETRY_DELAYS_MS.length : 0); attempt += 1) {
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        headers: {
          'Content-Type': 'application/json',
          ...options?.headers,
        },
        ...options,
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `HTTP ${response.status}`);
      }
      return response.json() as Promise<T>;
    } catch (err) {
      const hasRetryLeft = canRetry && attempt < GET_RETRY_DELAYS_MS.length;
      if (hasRetryLeft) {
        await delay(GET_RETRY_DELAYS_MS[attempt]);
        continue;
      }
      if (err instanceof TypeError) {
        throw new Error('Backend is still starting or unreachable. Please try again in a moment.');
      }
      throw err;
    }
  }
  throw new Error('Request failed');
}

function delay(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  }
  return search.toString();
}

export const api = {
  health: () => request<{ status: string; alpaca_configured: boolean }>('/api/health'),
  searchSymbols: (q: string, asset_class: AssetClass = 'stock') =>
    request<SymbolResult[]>(`/api/symbols/search?${qs({ q, asset_class })}`),
  bars: (params: {
    symbol: string;
    timeframe: string;
    start: string;
    end: string;
    refresh?: boolean;
    asset_class?: AssetClass;
  }) => request<Bar[]>(`/api/bars?${qs(params)}`),
  news: (params: {
    symbol: string;
    start?: string;
    end?: string;
    limit?: number;
    relation_type?: 'all' | 'direct' | 'indirect';
    asset_class?: AssetClass;
  }) =>
    request<NewsArticle[]>(`/api/news?${qs(params)}`),
  fetchNews: (body: {
    symbol: string;
    asset_class?: AssetClass;
    start?: string;
    end?: string;
    include_rss: boolean;
    limit: number;
    relation_type?: 'all' | 'direct' | 'indirect';
  }) =>
    request<NewsFetchResponse>('/api/news/fetch', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  runSentiment: (body: { symbol: string; asset_class?: AssetClass; article_ids?: string[]; use_ollama: boolean }) =>
    request<SentimentScore[]>('/api/sentiment/run', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  sentiment: (params: { symbol: string; start?: string; end?: string; asset_class?: AssetClass }) =>
    request<SentimentScore[]>(`/api/sentiment?${qs(params)}`),
  datasetSummary: (asset_class: AssetClass = 'stock') =>
    request<DatasetSummaryRow[]>(`/api/dataset/summary?${qs({ asset_class })}`),
  strategyEnvironment: () => request<StrategyEnvironment>('/api/strategy/environment'),
  runBacktest: (body: {
    symbol: string;
    timeframe: string;
    start: string;
    end: string;
    code: string;
    strategy_name: string;
    initial_cash: number;
    commission_pct: number;
    position_size_cash?: number | null;
    stop_loss_pct?: number | null;
    take_profit_pct?: number | null;
    timeout_seconds?: number | null;
  }) =>
    request<BacktestRun>('/api/backtests', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  backtests: (limit = 25) => request<BacktestSummary[]>(`/api/backtests?${qs({ limit })}`),
  backtest: (id: string) => request<BacktestRun>(`/api/backtests/${id}`),
  deleteBacktest: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/api/backtests/${id}`, {
      method: 'DELETE',
    }),
  strategies: (limit = 50) => request<StrategyRecord[]>(`/api/strategies?${qs({ limit })}`),
  saveStrategy: (body: { name: string; code: string }) =>
    request<StrategyRecord>('/api/strategies', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  portfolio: () => request<PaperPortfolio>('/api/paper/portfolio'),
  paperOrder: (body: { symbol: string; side: 'buy' | 'sell'; quantity: number }) =>
    request('/api/paper/orders', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};
