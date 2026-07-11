import { AlertCircle, BarChart3 } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react';

import { api } from './api';
import { ChartPanel } from './components/ChartPanel';
import { Controls } from './components/Controls';
import { DatasetPanel } from './components/DatasetPanel';
import { NewsPanel } from './components/NewsPanel';
import { PaperPanel } from './components/PaperPanel';
import { ResultsPanel } from './components/ResultsPanel';
import { StatusPill } from './components/StatusPill';
import { StrategyEditor } from './components/StrategyEditor';
import { defaultStrategy } from './defaultStrategy';
import { toDateInput } from './lib/format';
import { strategyExamples, type StrategyExample } from './strategyExamples';
import type {
  AssetClass,
  BacktestRun,
  BacktestSummary,
  Bar,
  DatasetSummaryRow,
  NewsChartMarker,
  NewsChartMode,
  NewsArticle,
  NewsFetchSummary,
  NewsSortMode,
  PaperPortfolio,
  SentimentScore,
  StrategyEnvironment,
  StrategyRecord,
} from './types';

function webSocketBaseUrl() {
  const explicit = import.meta.env.VITE_WS_URL;
  if (explicit) return explicit.replace(/\/$/, '');
  const apiUrl = import.meta.env.VITE_API_URL;
  if (apiUrl?.startsWith('https://')) return apiUrl.replace('https://', 'wss://').replace(/\/$/, '');
  if (apiUrl?.startsWith('http://')) return apiUrl.replace('http://', 'ws://').replace(/\/$/, '');
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${protocol}://${window.location.host}`;
}

function initialStart() {
  return toDateInput(new Date(Date.now() - 180 * 24 * 60 * 60 * 1000));
}

function initialEnd() {
  return toDateInput(new Date());
}

type WorkspaceTab = 'news' | 'results' | 'strategy' | 'portfolio' | 'dataset';
type NewsRelationFilter = 'all' | 'direct' | 'indirect';

const DEFAULT_SYMBOL_BY_ASSET: Record<AssetClass, string> = {
  stock: 'AAPL',
  crypto: 'BTC/USD',
};
const NEWS_FEED_LIMIT = 10000;
const INFLUENTIAL_NEWS_LIMIT = 12;
const RIGHT_RAIL_STORAGE_KEY = 'trading-lab-right-rail-width';
const DEFAULT_RIGHT_RAIL_WIDTH = 560;
const RIGHT_RAIL_MIN_WIDTH = 420;
const RIGHT_RAIL_MAX_WIDTH = 980;
const MAIN_CHART_MIN_WIDTH = 520;

function clampRightRailWidth(width: number) {
  const baseWidth = Math.min(Math.max(width, RIGHT_RAIL_MIN_WIDTH), RIGHT_RAIL_MAX_WIDTH);
  if (typeof window === 'undefined') return baseWidth;

  const viewportMax = Math.max(RIGHT_RAIL_MIN_WIDTH, window.innerWidth - MAIN_CHART_MIN_WIDTH);
  return Math.min(baseWidth, viewportMax);
}

function initialRightRailWidth() {
  if (typeof window === 'undefined') return DEFAULT_RIGHT_RAIL_WIDTH;
  try {
    const stored = Number(window.localStorage.getItem(RIGHT_RAIL_STORAGE_KEY));
    return Number.isFinite(stored) && stored > 0 ? clampRightRailWidth(stored) : DEFAULT_RIGHT_RAIL_WIDTH;
  } catch {
    return DEFAULT_RIGHT_RAIL_WIDTH;
  }
}

export default function App() {
  const [assetClass, setAssetClass] = useState<AssetClass>('stock');
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL_BY_ASSET.stock);
  const [timeframe, setTimeframe] = useState('1Day');
  const [start, setStart] = useState(initialStart);
  const [end, setEnd] = useState(initialEnd);
  const [newsStart, setNewsStart] = useState(initialStart);
  const [newsEnd, setNewsEnd] = useState(initialEnd);
  const [newsRelationFilter, setNewsRelationFilter] = useState<NewsRelationFilter>('all');
  const [bars, setBars] = useState<Bar[]>([]);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [newsFetchSummary, setNewsFetchSummary] = useState<NewsFetchSummary | null>(null);
  const [sentiment, setSentiment] = useState<SentimentScore[]>([]);
  const [newsSortMode, setNewsSortMode] = useState<NewsSortMode>('chronological');
  const [newsChartMode, setNewsChartMode] = useState<NewsChartMode>('none');
  const [selectedNewsId, setSelectedNewsId] = useState<string | null>(null);
  const [newsFocusRequest, setNewsFocusRequest] = useState<{ articleId: string; nonce: number } | null>(null);
  const [code, setCode] = useState(defaultStrategy);
  const [strategyName, setStrategyName] = useState('New strategy');
  const [strategies, setStrategies] = useState<StrategyRecord[]>([]);
  const [backtest, setBacktest] = useState<BacktestRun | null>(null);
  const [backtestHistory, setBacktestHistory] = useState<BacktestSummary[]>([]);
  const [portfolio, setPortfolio] = useState<PaperPortfolio | null>(null);
  const [datasetRows, setDatasetRows] = useState<DatasetSummaryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [datasetLoading, setDatasetLoading] = useState(false);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsLoadingMessage, setNewsLoadingMessage] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [alpacaConfigured, setAlpacaConfigured] = useState(false);
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('news');
  const [savingStrategy, setSavingStrategy] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [initialCash, setInitialCash] = useState(10000);
  const [positionSizeCash, setPositionSizeCash] = useState(10000);
  const [stopLossPct, setStopLossPct] = useState(10);
  const [takeProfitPct, setTakeProfitPct] = useState(0);
  const [commissionPct, setCommissionPct] = useState(0.1);
  const [timeoutSeconds, setTimeoutSeconds] = useState(8);
  const [strategyEnvironment, setStrategyEnvironment] = useState<StrategyEnvironment | null>(null);
  const [rightRailWidth, setRightRailWidth] = useState(initialRightRailWidth);

  const markers = useMemo(() => {
    if (!backtest) return [];
    const runMatchesChart =
      backtest.symbol === symbol &&
      backtest.timeframe === timeframe &&
      toDateInput(new Date(backtest.start_at)) === start &&
      toDateInput(new Date(backtest.end_at)) === end;
    return runMatchesChart ? backtest.markers : [];
  }, [backtest, end, start, symbol, timeframe]);
  const livePrice = bars.length ? bars[bars.length - 1].close : null;
  const workspaceStyle = useMemo(
    () => ({ '--right-rail-width': `${rightRailWidth}px` }) as CSSProperties,
    [rightRailWidth],
  );
  const sentimentByArticle = useMemo(
    () => new Map(sentiment.map((score) => [score.article_id, score])),
    [sentiment],
  );
  const sortedNews = useMemo(() => {
    const scoreValue = (article: NewsArticle, field: 'positive' | 'negative') => {
      const score = sentimentByArticle.get(article.id);
      return score ? score[field] : -1;
    };
    return [...news].sort((a, b) => {
      if (newsSortMode === 'positive') {
        return scoreValue(b, 'positive') - scoreValue(a, 'positive');
      }
      if (newsSortMode === 'negative') {
        return scoreValue(b, 'negative') - scoreValue(a, 'negative');
      }
      return new Date(a.published_at).getTime() - new Date(b.published_at).getTime();
    });
  }, [news, newsSortMode, sentimentByArticle]);
  const newsChartMarkers = useMemo<NewsChartMarker[]>(() => {
    if (newsChartMode === 'none') return [];
    const scored = news
      .map((article) => {
        const score = sentimentByArticle.get(article.id);
        const dominantScore = score ? Math.max(score.positive, score.negative) : 0;
        return { article, score, dominantScore };
      })
      .filter(({ article }) => Boolean(article.published_at));
    const visibleBase = newsChartMode === 'influential'
      ? [...scored]
          .sort((a, b) => b.dominantScore - a.dominantScore)
          .slice(0, INFLUENTIAL_NEWS_LIMIT)
      : scored;
    const visible = selectedNewsId && !visibleBase.some(({ article }) => article.id === selectedNewsId)
      ? [...visibleBase, ...scored.filter(({ article }) => article.id === selectedNewsId)]
      : visibleBase;
    return visible.map(({ article, score, dominantScore }) => ({
      article_id: article.id,
      timestamp: article.published_at,
      label: article.headline,
      sentiment: score?.label ?? 'neutral',
      score: dominantScore,
    }));
  }, [news, newsChartMode, selectedNewsId, sentimentByArticle]);

  useEffect(() => {
    api
      .health()
      .then((health) => setAlpacaConfigured(health.alpaca_configured))
      .catch(() => setAlpacaConfigured(false));
    loadStrategies();
    loadBacktestHistory();
    loadDatasetSummary();
    loadStrategyEnvironment();
  }, []);

  useEffect(() => {
    loadDatasetSummary();
  }, [assetClass]);

  useEffect(() => {
    try {
      window.localStorage.setItem(RIGHT_RAIL_STORAGE_KEY, String(rightRailWidth));
    } catch {
      // Layout preferences are optional; ignore storage failures.
    }
  }, [rightRailWidth]);

  const startWorkspaceResize = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = rightRailWidth;
      const previousCursor = document.body.style.cursor;
      const previousUserSelect = document.body.style.userSelect;

      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';

      const onPointerMove = (moveEvent: PointerEvent) => {
        const delta = startX - moveEvent.clientX;
        setRightRailWidth(clampRightRailWidth(startWidth + delta));
      };

      const onPointerUp = () => {
        document.body.style.cursor = previousCursor;
        document.body.style.userSelect = previousUserSelect;
        window.removeEventListener('pointermove', onPointerMove);
      };

      window.addEventListener('pointermove', onPointerMove);
      window.addEventListener('pointerup', onPointerUp, { once: true });
    },
    [rightRailWidth],
  );

  useEffect(() => {
    loadMarket(false);
  }, [assetClass, symbol, timeframe, start, end]);

  useEffect(() => {
    loadNewsCache();
  }, [assetClass, symbol, newsStart, newsEnd, newsRelationFilter]);

  useEffect(() => {
    if (assetClass !== 'stock') {
      setLive(false);
      return;
    }
    const socket = new WebSocket(`${webSocketBaseUrl()}/ws/market/${symbol}?timeframe=1Min`);
    socket.onopen = () => setLive(true);
    socket.onclose = () => setLive(false);
    socket.onerror = () => setLive(false);
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (!payload.bar || timeframe !== '1Min') return;
      setBars((current) => {
        const next = current.filter((bar) => bar.timestamp !== payload.bar.timestamp);
        return [...next, payload.bar].sort((a, b) => a.timestamp.localeCompare(b.timestamp)).slice(-1200);
      });
    };
    return () => socket.close();
  }, [assetClass, symbol, timeframe]);

  async function loadMarket(refresh: boolean) {
    setLoading(true);
    setError(null);
    try {
      const nextBars = await api.bars({ symbol, timeframe, start, end, refresh, asset_class: assetClass });
      setBars(nextBars);
      if (assetClass === 'stock') {
        setPortfolio(await api.portfolio());
      } else {
        setPortfolio(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error loading data');
    } finally {
      setLoading(false);
    }
  }

  async function loadNewsCache() {
    setNewsLoading(true);
    setNewsLoadingMessage('Loading saved news...');
    setError(null);
    try {
      const [nextNews, nextSentiment] = await Promise.all([
        api.news({
          symbol,
          start: newsStart,
          end: newsEnd,
          limit: NEWS_FEED_LIMIT,
          relation_type: newsRelationFilter,
          asset_class: assetClass,
        }),
        api.sentiment({ symbol, start: newsStart, end: newsEnd, asset_class: assetClass }),
      ]);
      setNews(nextNews);
      setSelectedNewsId(null);
      setNewsFetchSummary(null);
      setSentiment(nextSentiment);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error loading news');
    } finally {
      setNewsLoading(false);
      setNewsLoadingMessage(null);
    }
  }

  async function fetchNews() {
    setNewsLoading(true);
    setNewsLoadingMessage(
      assetClass === 'crypto'
        ? 'Loading local crypto news, sentiment, and OHLCV history...'
        : 'Processing news, sentiment, and OHLCV history...',
    );
    setError(null);
    try {
      const result = await api.fetchNews({
        symbol,
        asset_class: assetClass,
        start: newsStart,
        end: newsEnd,
        include_rss: false,
        limit: NEWS_FEED_LIMIT,
        relation_type: newsRelationFilter,
      });
      const articles = result.articles;
      setNews(articles);
      setSelectedNewsId(null);
      setNewsFetchSummary(result.summary);
      const existingScores = await api.sentiment({ symbol, start: newsStart, end: newsEnd, asset_class: assetClass });
      if (assetClass === 'crypto') {
        setSentiment(existingScores);
        loadDatasetSummary();
        return;
      }
      const existingScoreIds = new Set(existingScores.map((score) => score.article_id));
      const articlesToScore = articles.filter((article) => !existingScoreIds.has(article.id));
      if (articlesToScore.length) {
        setNewsLoadingMessage(`Analyzing sentiment (${articlesToScore.length} pending)...`);
        const scores = await api.runSentiment({
          symbol,
          asset_class: assetClass,
          article_ids: articlesToScore.map((article) => article.id),
          use_ollama: false,
        });
        const scoreIds = new Set(scores.map((score) => score.article_id));
        setSentiment((current) => [
          ...scores,
          ...existingScores.filter((score) => !scoreIds.has(score.article_id)),
          ...current.filter((score) => !scoreIds.has(score.article_id)),
        ]);
      } else {
        setSentiment(existingScores);
      }
      loadDatasetSummary();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error loading news');
    } finally {
      setNewsLoading(false);
      setNewsLoadingMessage(null);
    }
  }

  async function runSentiment() {
    setNewsLoading(true);
    setNewsLoadingMessage(assetClass === 'crypto' ? 'Loading saved crypto sentiment...' : 'Analyzing sentiment...');
    setError(null);
    try {
      if (assetClass === 'crypto') {
        setSentiment(await api.sentiment({ symbol, start: newsStart, end: newsEnd, asset_class: assetClass }));
        return;
      }
      const articles = news.length
        ? news
        : (
            await api.fetchNews({
              symbol,
              asset_class: assetClass,
              start: newsStart,
              end: newsEnd,
              include_rss: false,
              limit: NEWS_FEED_LIMIT,
              relation_type: newsRelationFilter,
            })
          ).articles;
      setNews(articles);
      const existingScores = await api.sentiment({ symbol, start: newsStart, end: newsEnd, asset_class: assetClass });
      const existingScoreIds = new Set(existingScores.map((score) => score.article_id));
      const articlesToScore = articles.filter((article) => !existingScoreIds.has(article.id));
      if (!articlesToScore.length) {
        setSentiment(existingScores);
        return;
      }
      const scores = await api.runSentiment({
        symbol,
        asset_class: assetClass,
        article_ids: articlesToScore.map((article) => article.id),
        use_ollama: false,
      });
      const scoreIds = new Set(scores.map((score) => score.article_id));
      setSentiment([
        ...scores,
        ...existingScores.filter((score) => !scoreIds.has(score.article_id)),
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error analyzing sentiment');
    } finally {
      setNewsLoading(false);
      setNewsLoadingMessage(null);
    }
  }

  async function runBacktest() {
    if (assetClass === 'crypto') {
      setError('Crypto backtesting is not wired yet. Use the chart, news, sentiment, and Dataset views for crypto for now.');
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const run = await api.runBacktest({
        symbol,
        timeframe,
        start,
        end,
        code,
        strategy_name: strategyName || `${symbol} strategy`,
        initial_cash: Math.max(1, initialCash || 1),
        commission_pct: Math.max(0, commissionPct || 0) / 100,
        position_size_cash: positionSizeCash > 0 ? positionSizeCash : null,
        stop_loss_pct: stopLossPct > 0 ? stopLossPct : null,
        take_profit_pct: takeProfitPct > 0 ? takeProfitPct : null,
        timeout_seconds: Math.min(300, Math.max(1, Math.round(timeoutSeconds || 8))),
      });
      setBacktest(run);
      setBacktestHistory(await api.backtests());
      setActiveTab('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error running backtest');
    } finally {
      setRunning(false);
    }
  }

  async function placeOrder(side: 'buy' | 'sell', quantity: number) {
    setError(null);
    try {
      await api.paperOrder({ symbol, side, quantity });
      setPortfolio(await api.portfolio());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error placing paper order');
    }
  }

  async function saveStrategy() {
    setSavingStrategy(true);
    setSaveMessage(null);
    setError(null);
    try {
      const saved = await api.saveStrategy({ name: strategyName || 'Untitled strategy', code });
      setStrategies((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      setSaveMessage(saved.file_path ? `Saved to ${saved.file_path}` : 'Strategy saved');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error saving strategy');
    } finally {
      setSavingStrategy(false);
    }
  }

  async function loadStrategies() {
    try {
      setStrategies(await api.strategies());
    } catch {
      setStrategies([]);
    }
  }

  async function loadBacktestHistory() {
    try {
      setBacktestHistory(await api.backtests());
    } catch {
      setBacktestHistory([]);
    }
  }

  async function loadDatasetSummary() {
    setDatasetLoading(true);
    setError(null);
    try {
      setDatasetRows(await api.datasetSummary(assetClass));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error loading dataset summary');
    } finally {
      setDatasetLoading(false);
    }
  }

  async function loadStrategyEnvironment() {
    try {
      const environment = await api.strategyEnvironment();
      setStrategyEnvironment(environment);
      setTimeoutSeconds(environment.strategy_timeout_seconds);
    } catch {
      setStrategyEnvironment(null);
    }
  }

  async function loadBacktestRun(id: string) {
    setError(null);
    try {
      const run = await api.backtest(id);
      setAssetClass('stock');
      setSymbol(run.symbol);
      setTimeframe(run.timeframe);
      setStart(toDateInput(new Date(run.start_at)));
      setEnd(toDateInput(new Date(run.end_at)));
      setBacktest(run);
      setActiveTab('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error loading backtest');
    }
  }

  async function deleteBacktestRun(id: string) {
    const target = backtestHistory.find((item) => item.id === id);
    const label = target ? `${target.strategy_name} ${target.symbol} ${target.timeframe}` : 'this backtest';
    if (!window.confirm(`Delete ${label}? This cannot be undone.`)) return;
    setError(null);
    try {
      await api.deleteBacktest(id);
      setBacktestHistory((current) => current.filter((item) => item.id !== id));
      setBacktest((current) => (current?.id === id ? null : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error deleting backtest');
    }
  }

  function loadRunCode(run: BacktestRun) {
    if (!run.strategy_code) return;
    setCode(run.strategy_code);
    setStrategyName(run.strategy_name || `${run.symbol} strategy`);
    setActiveTab('strategy');
  }

  function loadStrategy(strategy: StrategyRecord) {
    setCode(strategy.code);
    setStrategyName(strategy.name);
    setSaveMessage(strategy.file_path ? `Loaded from ${strategy.file_path}` : 'Strategy loaded');
  }

  function loadStrategyExample(example: StrategyExample) {
    setCode(example.code);
    setStrategyName(example.name);
    setSaveMessage(`Example loaded: ${example.description}`);
  }

  function selectNewsFromChart(articleId: string) {
    setSelectedNewsId(articleId);
    setActiveTab('news');
  }

  function selectNewsFromList(articleId: string) {
    setSelectedNewsId(articleId);
    setNewsFocusRequest((current) => ({
      articleId,
      nonce: (current?.nonce ?? 0) + 1,
    }));
  }

  function selectDatasetSymbol(nextSymbol: string) {
    setSymbol(nextSymbol);
  }

  function handleAssetClassChange(nextAssetClass: AssetClass) {
    if (nextAssetClass === assetClass) return;
    const nextSymbol = DEFAULT_SYMBOL_BY_ASSET[nextAssetClass];
    setAssetClass(nextAssetClass);
    setSymbol(nextSymbol);
    setBars([]);
    setNews([]);
    setSentiment([]);
    setNewsFetchSummary(null);
    setSelectedNewsId(null);
    setBacktest(null);
    setPortfolio(null);
    setStart(initialStart());
    setEnd(initialEnd());
    setNewsStart(initialStart());
    setNewsEnd(initialEnd());
    setError(null);
  }

  function setPreset(days: number) {
    setStart(toDateInput(new Date(Date.now() - days * 24 * 60 * 60 * 1000)));
    setEnd(initialEnd());
  }

  function setYearPreset(years: number) {
    const nextEnd = new Date();
    const nextStart = new Date(nextEnd);
    nextStart.setFullYear(nextStart.getFullYear() - years);
    setStart(toDateInput(nextStart));
    setEnd(toDateInput(nextEnd));
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand-lockup">
          <BarChart3 size={25} />
          <div>
            <span>Trading Lab</span>
            <small>local research</small>
          </div>
        </div>
        <Controls
          assetClass={assetClass}
          symbol={symbol}
          timeframe={timeframe}
          start={start}
          end={end}
          loading={loading}
          onSymbolChange={setSymbol}
          onTimeframeChange={setTimeframe}
          onStartChange={setStart}
          onEndChange={setEnd}
          onRefresh={() => loadMarket(true)}
          onPreset={setPreset}
          onYearPreset={setYearPreset}
          onAssetClassChange={handleAssetClassChange}
        />
        <StatusPill live={live} alpacaConfigured={alpacaConfigured} />
      </header>

      {error && (
        <div className="top-alert">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="workspace" style={workspaceStyle}>
        <div className="main-column">
          <ChartPanel
            bars={bars}
            markers={markers}
            newsMarkers={newsChartMarkers}
            selectedNewsId={selectedNewsId}
            focusNewsRequest={newsFocusRequest}
            symbol={symbol}
            timeframe={timeframe}
            livePrice={livePrice}
            onNewsMarkerClick={selectNewsFromChart}
          />
        </div>
        <button
          className="workspace-resizer"
          type="button"
          aria-label="Resize chart and side panel"
          onPointerDown={startWorkspaceResize}
        />
        <aside className="right-rail">
          <div className="workspace-tabs" role="tablist" aria-label="Right panel">
            <TabButton active={activeTab === 'news'} onClick={() => setActiveTab('news')}>
              News
            </TabButton>
            <TabButton active={activeTab === 'results'} onClick={() => setActiveTab('results')}>
              Results
            </TabButton>
            <TabButton active={activeTab === 'strategy'} onClick={() => setActiveTab('strategy')}>
              Strategy
            </TabButton>
            <TabButton active={activeTab === 'portfolio'} onClick={() => setActiveTab('portfolio')}>
              Portfolio
            </TabButton>
            <TabButton active={activeTab === 'dataset'} onClick={() => setActiveTab('dataset')}>
              Dataset
            </TabButton>
          </div>
          <div className="tab-content">
            {activeTab === 'news' && (
              <NewsPanel
                assetClass={assetClass}
                news={sortedNews}
                fetchSummary={newsFetchSummary}
                sentiment={sentiment}
                loading={newsLoading}
                loadingMessage={newsLoadingMessage}
                sortMode={newsSortMode}
                chartMode={newsChartMode}
                selectedNewsId={selectedNewsId}
                start={newsStart}
                end={newsEnd}
                relationFilter={newsRelationFilter}
                onSortModeChange={setNewsSortMode}
                onChartModeChange={setNewsChartMode}
                onSelectNews={selectNewsFromList}
                onStartChange={setNewsStart}
                onEndChange={setNewsEnd}
                onRelationFilterChange={setNewsRelationFilter}
                onFetchNews={fetchNews}
                onRunSentiment={runSentiment}
              />
            )}
            {activeTab === 'results' && (
              <ResultsPanel
                run={backtest}
                history={backtestHistory}
                onLoadRun={loadBacktestRun}
                onDeleteRun={deleteBacktestRun}
                onLoadRunCode={loadRunCode}
              />
            )}
            {activeTab === 'strategy' && (
              <StrategyEditor
                strategyName={strategyName}
                code={code}
                running={running}
                saving={savingStrategy}
                saveMessage={saveMessage}
                strategies={strategies}
                examples={strategyExamples}
                initialCash={initialCash}
                positionSizeCash={positionSizeCash}
                stopLossPct={stopLossPct}
                takeProfitPct={takeProfitPct}
                commissionPct={commissionPct}
                timeoutSeconds={timeoutSeconds}
                environment={strategyEnvironment}
                onStrategyNameChange={setStrategyName}
                onChange={setCode}
                onRun={runBacktest}
                onSave={saveStrategy}
                onLoadStrategy={loadStrategy}
                onLoadExample={loadStrategyExample}
                onInitialCashChange={setInitialCash}
                onPositionSizeCashChange={setPositionSizeCash}
                onStopLossPctChange={setStopLossPct}
                onTakeProfitPctChange={setTakeProfitPct}
                onCommissionPctChange={setCommissionPct}
                onTimeoutSecondsChange={setTimeoutSeconds}
              />
            )}
            {activeTab === 'portfolio' && <PaperPanel symbol={symbol} portfolio={portfolio} onOrder={placeOrder} />}
            {activeTab === 'dataset' && (
              <DatasetPanel
                rows={datasetRows}
                assetClass={assetClass}
                loading={datasetLoading}
                onRefresh={loadDatasetSummary}
                onSelectSymbol={selectDatasetSymbol}
              />
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button className={active ? 'active' : ''} role="tab" aria-selected={active} onClick={onClick}>
      {children}
    </button>
  );
}
