import { Brain, ExternalLink, Newspaper, RefreshCw } from 'lucide-react';

import { formatPercent, sentimentLabel, sentimentTone } from '../lib/format';
import type { NewsArticle, SentimentScore } from '../types';

interface Props {
  news: NewsArticle[];
  sentiment: SentimentScore[];
  loading: boolean;
  onFetchNews: () => void;
  onRunSentiment: () => void;
}

export function NewsPanel({ news, sentiment, loading, onFetchNews, onRunSentiment }: Props) {
  const sentimentByArticle = new Map(sentiment.map((score) => [score.article_id, score]));

  return (
    <section className="side-panel news-panel">
      <div className="panel-titlebar">
        <div>
          <p className="eyebrow">Noticias</p>
          <h2>Feed y sentimiento</h2>
        </div>
        <div className="tool-buttons">
          <button className="icon-button" onClick={onFetchNews} aria-label="Traer noticias">
            <Newspaper size={16} />
          </button>
          <button className="icon-button" onClick={onRunSentiment} aria-label="Analizar sentimiento">
            <Brain size={16} />
          </button>
          {loading && <RefreshCw size={16} className="spin subtle-icon" />}
        </div>
      </div>
      <div className="news-list">
        {news.map((article) => {
          const score = sentimentByArticle.get(article.id);
          const tone = sentimentTone(score?.label);
          return (
            <article key={article.id} className="news-item">
              <div className="news-meta">
                <span>{article.source}</span>
                <span>{new Date(article.published_at).toLocaleDateString('es-MX')}</span>
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

