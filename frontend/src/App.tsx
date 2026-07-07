import { AlertCircle, BarChart3 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { api } from './api';
import { ChartPanel } from './components/ChartPanel';
import { Controls } from './components/Controls';
import { NewsPanel } from './components/NewsPanel';
import { PaperPanel } from './components/PaperPanel';
import { ResultsPanel } from './components/ResultsPanel';
import { StatusPill } from './components/StatusPill';
import { StrategyEditor } from './components/StrategyEditor';
import { defaultStrategy } from './defaultStrategy';
import { toDateInput } from './lib/format';
import type {
  BacktestRun,
  BacktestSummary,
  Bar,
  NewsChartMarker,
  NewsChartMode,
  NewsArticle,
  NewsFetchSummary,
  NewsSortMode,
  PaperPortfolio,
  SentimentScore,
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

type WorkspaceTab = 'news' | 'results' | 'strategy' | 'portfolio';
type NewsRelationFilter = 'all' | 'direct' | 'indirect';

const NEWS_FEED_LIMIT = 2000;
const INFLUENTIAL_NEWS_LIMIT = 12;

export default function App() {
  const [symbol, setSymbol] = useState('AAPL');
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
  const [newsChartMode, setNewsChartMode] = useState<NewsChartMode>('all');
  const [selectedNewsId, setSelectedNewsId] = useState<string | null>(null);
  const [newsFocusRequest, setNewsFocusRequest] = useState<{ articleId: string; nonce: number } | null>(null);
  const [code, setCode] = useState(defaultStrategy);
  const [strategyName, setStrategyName] = useState('SMA crossover');
  const [strategies, setStrategies] = useState<StrategyRecord[]>([]);
  const [backtest, setBacktest] = useState<BacktestRun | null>(null);
  const [backtestHistory, setBacktestHistory] = useState<BacktestSummary[]>([]);
  const [portfolio, setPortfolio] = useState<PaperPortfolio | null>(null);
  const [loading, setLoading] = useState(false);
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

  const markers = useMemo(() => backtest?.markers ?? [], [backtest]);
  const livePrice = bars.length ? bars[bars.length - 1].close : null;
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
  }, []);

  useEffect(() => {
    loadMarket(false);
  }, [symbol, timeframe, start, end]);

  useEffect(() => {
    loadNewsCache();
  }, [symbol, newsStart, newsEnd, newsRelationFilter]);

  useEffect(() => {
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
  }, [symbol, timeframe]);

  async function loadMarket(refresh: boolean) {
    setLoading(true);
    setError(null);
    setBacktest(null);
    try {
      const [nextBars, nextPortfolio] = await Promise.all([
        api.bars({ symbol, timeframe, start, end, refresh }),
        api.portfolio(),
      ]);
      setBars(nextBars);
      setPortfolio(nextPortfolio);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error cargando datos');
    } finally {
      setLoading(false);
    }
  }

  async function loadNewsCache() {
    setNewsLoading(true);
    setNewsLoadingMessage('Cargando noticias guardadas...');
    setError(null);
    try {
      const [nextNews, nextSentiment] = await Promise.all([
        api.news({
          symbol,
          start: newsStart,
          end: newsEnd,
          limit: NEWS_FEED_LIMIT,
          relation_type: newsRelationFilter,
        }),
        api.sentiment({ symbol, start: newsStart, end: newsEnd }),
      ]);
      setNews(nextNews);
      setSelectedNewsId(null);
      setNewsFetchSummary(null);
      setSentiment(nextSentiment);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error cargando noticias');
    } finally {
      setNewsLoading(false);
      setNewsLoadingMessage(null);
    }
  }

  async function fetchNews() {
    setNewsLoading(true);
    setNewsLoadingMessage('Procesando histórico de noticias...');
    setError(null);
    try {
      const result = await api.fetchNews({
        symbol,
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
      const existingScores = await api.sentiment({ symbol, start: newsStart, end: newsEnd });
      const existingScoreIds = new Set(existingScores.map((score) => score.article_id));
      const articlesToScore = articles.filter((article) => !existingScoreIds.has(article.id));
      if (articlesToScore.length) {
        setNewsLoadingMessage(`Analizando sentimiento (${articlesToScore.length} pendientes)...`);
        const scores = await api.runSentiment({
          symbol,
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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error cargando noticias');
    } finally {
      setNewsLoading(false);
      setNewsLoadingMessage(null);
    }
  }

  async function runSentiment() {
    setNewsLoading(true);
    setNewsLoadingMessage('Analizando sentimiento...');
    setError(null);
    try {
      const articles = news.length
        ? news
        : (
            await api.fetchNews({
              symbol,
              start: newsStart,
              end: newsEnd,
              include_rss: false,
              limit: NEWS_FEED_LIMIT,
              relation_type: newsRelationFilter,
            })
          ).articles;
      setNews(articles);
      const existingScores = await api.sentiment({ symbol, start: newsStart, end: newsEnd });
      const existingScoreIds = new Set(existingScores.map((score) => score.article_id));
      const articlesToScore = articles.filter((article) => !existingScoreIds.has(article.id));
      if (!articlesToScore.length) {
        setSentiment(existingScores);
        return;
      }
      const scores = await api.runSentiment({
        symbol,
        article_ids: articlesToScore.map((article) => article.id),
        use_ollama: false,
      });
      const scoreIds = new Set(scores.map((score) => score.article_id));
      setSentiment([
        ...scores,
        ...existingScores.filter((score) => !scoreIds.has(score.article_id)),
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error analizando sentimiento');
    } finally {
      setNewsLoading(false);
      setNewsLoadingMessage(null);
    }
  }

  async function runBacktest() {
    setRunning(true);
    setError(null);
    try {
      const run = await api.runBacktest({
        symbol,
        timeframe,
        start,
        end,
        code,
        strategy_name: strategyName || `${symbol} estrategia`,
        initial_cash: Math.max(1, initialCash || 1),
        commission_pct: Math.max(0, commissionPct || 0) / 100,
        position_size_cash: positionSizeCash > 0 ? positionSizeCash : null,
        stop_loss_pct: stopLossPct > 0 ? stopLossPct : null,
        take_profit_pct: takeProfitPct > 0 ? takeProfitPct : null,
      });
      setBacktest(run);
      setBacktestHistory(await api.backtests());
      setActiveTab('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error corriendo backtest');
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
      setError(err instanceof Error ? err.message : 'Error en orden paper');
    }
  }

  async function saveStrategy() {
    setSavingStrategy(true);
    setSaveMessage(null);
    setError(null);
    try {
      const saved = await api.saveStrategy({ name: strategyName || 'Estrategia sin nombre', code });
      setStrategies((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      setSaveMessage(saved.file_path ? `Guardada en ${saved.file_path}` : 'Estrategia guardada');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error guardando estrategia');
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

  async function loadBacktestRun(id: string) {
    setError(null);
    try {
      const run = await api.backtest(id);
      setBacktest(run);
      setActiveTab('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error cargando backtest');
    }
  }

  function loadRunCode(run: BacktestRun) {
    if (!run.strategy_code) return;
    setCode(run.strategy_code);
    setStrategyName(run.strategy_name || `${run.symbol} estrategia`);
    setActiveTab('strategy');
  }

  function loadStrategy(strategy: StrategyRecord) {
    setCode(strategy.code);
    setStrategyName(strategy.name);
    setSaveMessage(strategy.file_path ? `Cargada desde ${strategy.file_path}` : 'Estrategia cargada');
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
            <small>research local</small>
          </div>
        </div>
        <Controls
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
        />
        <StatusPill live={live} alpacaConfigured={alpacaConfigured} />
      </header>

      {error && (
        <div className="top-alert">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="workspace">
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
        <aside className="right-rail">
          <div className="workspace-tabs" role="tablist" aria-label="Panel derecho">
            <TabButton active={activeTab === 'news'} onClick={() => setActiveTab('news')}>
              Noticias
            </TabButton>
            <TabButton active={activeTab === 'results'} onClick={() => setActiveTab('results')}>
              Resultados
            </TabButton>
            <TabButton active={activeTab === 'strategy'} onClick={() => setActiveTab('strategy')}>
              Estrategia
            </TabButton>
            <TabButton active={activeTab === 'portfolio'} onClick={() => setActiveTab('portfolio')}>
              Portafolio
            </TabButton>
          </div>
          <div className="tab-content">
            {activeTab === 'news' && (
              <NewsPanel
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
                initialCash={initialCash}
                positionSizeCash={positionSizeCash}
                stopLossPct={stopLossPct}
                takeProfitPct={takeProfitPct}
                commissionPct={commissionPct}
                onStrategyNameChange={setStrategyName}
                onChange={setCode}
                onRun={runBacktest}
                onSave={saveStrategy}
                onLoadStrategy={loadStrategy}
                onInitialCashChange={setInitialCash}
                onPositionSizeCashChange={setPositionSizeCash}
                onStopLossPctChange={setStopLossPct}
                onTakeProfitPctChange={setTakeProfitPct}
                onCommissionPctChange={setCommissionPct}
              />
            )}
            {activeTab === 'portfolio' && <PaperPanel symbol={symbol} portfolio={portfolio} onOrder={placeOrder} />}
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
