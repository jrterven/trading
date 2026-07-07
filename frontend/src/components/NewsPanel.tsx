import { Brain, CalendarDays, DatabaseZap, ExternalLink, RefreshCw } from 'lucide-react';
import { useEffect, useRef } from 'react';

import { formatPercent, sentimentLabel, sentimentTone } from '../lib/format';
import type { NewsArticle, NewsChartMode, NewsFetchSummary, NewsSortMode, SentimentScore } from '../types';

interface Props {
  news: NewsArticle[];
  fetchSummary: NewsFetchSummary | null;
  sentiment: SentimentScore[];
  loading: boolean;
  loadingMessage: string | null;
  sortMode: NewsSortMode;
  chartMode: NewsChartMode;
  selectedNewsId: string | null;
  start: string;
  end: string;
  relationFilter: 'all' | 'direct' | 'indirect';
  onSortModeChange: (value: NewsSortMode) => void;
  onChartModeChange: (value: NewsChartMode) => void;
  onSelectNews: (articleId: string) => void;
  onStartChange: (value: string) => void;
  onEndChange: (value: string) => void;
  onRelationFilterChange: (value: 'all' | 'direct' | 'indirect') => void;
  onFetchNews: () => void;
  onRunSentiment: () => void;
}

const presets = [
  { label: 'Today', days: 0 },
  { label: '1W', days: 7 },
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: 'YTD', days: null },
] as const;

type PresetLabel = (typeof presets)[number]['label'] | 'Custom';

function dateInput(value: Date) {
  return value.toISOString().slice(0, 10);
}

function presetStart(days: number, endDate: Date) {
  const nextStart = new Date(endDate);
  nextStart.setDate(nextStart.getDate() - days);
  return dateInput(nextStart);
}

function activePreset(start: string, end: string): PresetLabel {
  const today = dateInput(new Date());
  if (end !== today) return 'Custom';
  const now = new Date();
  for (const preset of presets) {
    if (preset.days === null) {
      if (start === `${now.getFullYear()}-01-01`) return preset.label;
      continue;
    }
    if (start === presetStart(preset.days, now)) return preset.label;
  }
  return 'Custom';
}

function shortDate(date: string) {
  return new Date(`${date}T00:00:00`).toLocaleDateString('es-MX', {
    month: 'short',
    day: 'numeric',
  });
}

export function NewsPanel({
  news,
  fetchSummary,
  sentiment,
  loading,
  loadingMessage,
  sortMode,
  chartMode,
  selectedNewsId,
  start,
  end,
  relationFilter,
  onSortModeChange,
  onChartModeChange,
  onSelectNews,
  onStartChange,
  onEndChange,
  onRelationFilterChange,
  onFetchNews,
  onRunSentiment,
}: Props) {
  const articleRefs = useRef(new Map<string, HTMLElement>());
  const sentimentByArticle = new Map(sentiment.map((score) => [score.article_id, score]));
  const selectedPreset = activePreset(start, end);
  const setPreset = (days: number | null) => {
    const now = new Date();
    if (days === null) {
      onStartChange(`${now.getFullYear()}-01-01`);
      onEndChange(dateInput(now));
      return;
    }
    onStartChange(presetStart(days, now));
    onEndChange(dateInput(now));
  };

  useEffect(() => {
    if (!selectedNewsId) return;
    articleRefs.current.get(selectedNewsId)?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    });
  }, [selectedNewsId, news]);

  return (
    <section className="side-panel news-panel">
      <div className="panel-titlebar">
        <div>
          <p className="eyebrow">Noticias</p>
          <h2>Feed y sentimiento</h2>
        </div>
        <div className="tool-buttons">
          <button
            className="icon-button"
            onClick={onRunSentiment}
            disabled={loading}
            aria-label="Analizar sentimiento"
            data-tooltip="Analizar sentimiento"
          >
            <Brain size={16} />
          </button>
          <button
            className="icon-button"
            onClick={onFetchNews}
            disabled={loading}
            aria-label="Generar o actualizar histórico"
            data-tooltip="Generar/Actualizar histórico"
          >
            <DatabaseZap size={16} />
          </button>
          {loading && <RefreshCw size={16} className="spin subtle-icon" />}
        </div>
      </div>
      <div className="news-controls">
        <div className="segmented-control" aria-label="Rango de noticias">
          {presets.map((preset) => (
            <button
              key={preset.label}
              type="button"
              className={selectedPreset === preset.label ? 'active' : ''}
              onClick={() => setPreset(preset.days)}
            >
              {preset.label}
            </button>
          ))}
          <button type="button" className={selectedPreset === 'Custom' ? 'active' : ''}>
            Custom
          </button>
        </div>
        <div className="news-date-row">
          <label>
            <CalendarDays size={14} />
            <input type="date" value={start} onChange={(event) => onStartChange(event.target.value)} />
          </label>
          <label>
            <CalendarDays size={14} />
            <input type="date" value={end} onChange={(event) => onEndChange(event.target.value)} />
          </label>
        </div>
        <div className="segmented-control relation-filter" aria-label="Relacion de noticias">
          {(['all', 'direct', 'indirect'] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={relationFilter === value ? 'active' : ''}
              onClick={() => onRelationFilterChange(value)}
            >
              {value === 'all' ? 'All' : value === 'direct' ? 'Direct' : 'Indirect'}
            </button>
          ))}
        </div>
        <div className="news-options-grid">
          <div className="news-option-group">
            <span>Orden</span>
            <div className="segmented-control news-sort-control" aria-label="Orden de noticias">
              {([
                ['chronological', 'Cronológico'],
                ['positive', '+ Positivo'],
                ['negative', '+ Negativo'],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={sortMode === value ? 'active' : ''}
                  onClick={() => onSortModeChange(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="news-option-group">
            <span>Gráfica</span>
            <div className="segmented-control news-chart-control" aria-label="Noticias en grafica">
              {([
                ['all', 'Todas'],
                ['influential', 'Influyentes'],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={chartMode === value ? 'active' : ''}
                  onClick={() => onChartModeChange(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
        <button className="primary-row-button" type="button" onClick={onFetchNews} disabled={loading}>
          <DatabaseZap size={15} />
          Generar/Actualizar histórico
        </button>
        {loading && (
          <div className="news-progress" role="progressbar" aria-label={loadingMessage || 'Procesando noticias'}>
            <div className="news-progress-header">
              <span>{loadingMessage || 'Procesando noticias...'}</span>
              <strong>En curso</strong>
            </div>
            <div className="news-progress-track">
              <div className="news-progress-bar" />
            </div>
          </div>
        )}
        {fetchSummary && (
          <div className="news-fetch-summary" aria-label="Resumen de noticias extraidas">
            <div className="summary-metrics">
              <span>
                <strong>{fetchSummary.total}</strong>
                Total
              </span>
              <span>
                <strong>{fetchSummary.new}</strong>
                Nuevas
              </span>
              <span>
                <strong>{fetchSummary.existing}</strong>
                Ya existían
              </span>
              <span>
                <strong>{fetchSummary.fetched}</strong>
                Bajadas
              </span>
            </div>
            {(fetchSummary.daily.max || fetchSummary.daily.min) && (
              <div className="summary-daily-stats">
                {fetchSummary.daily.max && (
                  <span>
                    Max/día
                    <strong>{fetchSummary.daily.max.count}</strong>
                    <em>{shortDate(fetchSummary.daily.max.date)}</em>
                  </span>
                )}
                {fetchSummary.daily.min && (
                  <span>
                    Min/día
                    <strong>{fetchSummary.daily.min.count}</strong>
                    <em>{shortDate(fetchSummary.daily.min.date)}</em>
                  </span>
                )}
                <span>
                  Prom/día
                  <strong>{fetchSummary.daily.average.toFixed(2)}</strong>
                  <em>rango</em>
                </span>
              </div>
            )}
          </div>
        )}
      </div>
      <div className="news-list">
        {news.map((article) => {
          const score = sentimentByArticle.get(article.id);
          const tone = sentimentTone(score?.label);
          return (
            <article
              key={article.id}
              ref={(node) => {
                if (node) articleRefs.current.set(article.id, node);
                else articleRefs.current.delete(article.id);
              }}
              className={article.id === selectedNewsId ? 'news-item selected' : 'news-item'}
              onClick={() => onSelectNews(article.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelectNews(article.id);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <div className="news-meta">
                <span>{article.source}</span>
                <span>{new Date(article.published_at).toLocaleDateString('es-MX')}</span>
                <span className={`relation-badge ${article.relation_type}`}>
                  {article.relation_type === 'direct' ? 'direct' : 'indirect'}
                </span>
                {score && (
                  <span className={`sentiment-badge ${tone}`}>
                    {sentimentLabel(score.label)} {formatPercent(score.score * 100)}
                  </span>
                )}
              </div>
              <h3>{article.headline}</h3>
              {article.summary && <p>{article.summary}</p>}
              {score?.explanation && <p className="ai-note">{score.explanation}</p>}
              {article.url && (
                <a href={article.url} target="_blank" rel="noreferrer">
                  <ExternalLink size={13} /> fuente
                </a>
              )}
            </article>
          );
        })}
        {news.length === 0 && <div className="empty-state">Sin noticias cargadas</div>}
      </div>
    </section>
  );
}
