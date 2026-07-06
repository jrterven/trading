from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..db import as_utc_naive, connection, rows_to_dicts
from ..schemas import NewsArticle, SentimentScore
from ..time_utils import utc_now

POSITIVE_WORDS = {
    "beat",
    "beats",
    "growth",
    "profit",
    "record",
    "raise",
    "raises",
    "upgrade",
    "strong",
    "surge",
    "alliance",
    "crecimiento",
    "eleva",
    "mejora",
    "oportunidades",
    "resiliente",
}
NEGATIVE_WORDS = {
    "miss",
    "loss",
    "downgrade",
    "weak",
    "risk",
    "lawsuit",
    "probe",
    "falls",
    "pressure",
    "costs",
    "presion",
    "costos",
    "regulatorios",
    "impacto",
    "cae",
}

OLLAMA_BULK_LIMIT = 5

logger = logging.getLogger(__name__)


class SentimentService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._pipeline: Any | None = None
        self._pipeline_error: str | None = None

    async def run_for_symbol(
        self,
        symbol: str,
        article_ids: list[str] | None = None,
        use_ollama: bool = True,
    ) -> list[SentimentScore]:
        articles = self._load_articles(symbol, article_ids)
        started_at = time.monotonic()
        logger.info(
            "sentiment_start symbol=%s articles=%s use_ollama=%s ollama_model=%s",
            symbol.upper(),
            len(articles),
            use_ollama,
            self.settings.ollama_model,
        )
        scores: list[SentimentScore] = []
        for index, article in enumerate(articles, start=1):
            article_started_at = time.monotonic()
            use_ollama_for_article = use_ollama and index <= OLLAMA_BULK_LIMIT
            if use_ollama and index == OLLAMA_BULK_LIMIT + 1:
                logger.info(
                    "ollama_bulk_limit_reached symbol=%s total_articles=%s limit=%s",
                    symbol.upper(),
                    len(articles),
                    OLLAMA_BULK_LIMIT,
                )
            score = await self.score_article(article, use_ollama=use_ollama_for_article)
            scores.append(score)
            logger.info(
                "sentiment_article_done symbol=%s index=%s/%s article_id=%s label=%s score=%.3f model=%s elapsed=%.2fs",
                article.symbol,
                index,
                len(articles),
                article.id,
                score.label,
                score.score,
                score.model,
                time.monotonic() - article_started_at,
            )
        self.save_scores(scores)
        logger.info(
            "sentiment_done symbol=%s scores=%s elapsed=%.2fs",
            symbol.upper(),
            len(scores),
            time.monotonic() - started_at,
        )
        return scores

    async def score_article(self, article: NewsArticle, use_ollama: bool = True) -> SentimentScore:
        text = " ".join(
            part
            for part in [article.headline, article.summary, article.content]
            if part and str(part).strip()
        )
        probabilities, model_name = self._score_with_finbert_or_lexicon(text)
        label = max(probabilities, key=probabilities.get)
        explanation = None
        if use_ollama:
            explanation = await self._ollama_summary(article, label)
        score_id = hashlib.sha1(
            f"{article.id}:{article.symbol}:{model_name}:{json.dumps(probabilities, sort_keys=True)}".encode()
        ).hexdigest()
        return SentimentScore(
            id=score_id,
            article_id=article.id,
            symbol=article.symbol,
            label=label,  # type: ignore[arg-type]
            score=float(probabilities[label]),
            positive=float(probabilities["positive"]),
            neutral=float(probabilities["neutral"]),
            negative=float(probabilities["negative"]),
            model=model_name,
            explanation=explanation,
            created_at=utc_now(),
        )

    def get_scores(self, symbol: str, article_ids: list[str] | None = None) -> list[SentimentScore]:
        clauses = ["symbol = ?"]
        params: list[Any] = [symbol.upper()]
        if article_ids:
            placeholders = ",".join(["?"] * len(article_ids))
            clauses.append(f"article_id IN ({placeholders})")
            params.extend(article_ids)
        with connection(self.settings) as con:
            rows = rows_to_dicts(
                con.execute(
                    f"""
                    SELECT id, article_id, symbol, label, score, positive, neutral,
                           negative, model, explanation, created_at
                    FROM sentiment_scores
                    WHERE {' AND '.join(clauses)}
                    ORDER BY created_at DESC
                    """,
                    params,
                )
            )
        return [SentimentScore(**row) for row in rows]

    def save_scores(self, scores: list[SentimentScore]) -> None:
        if not scores:
            return
        with connection(self.settings) as con:
            for score in scores:
                con.execute("DELETE FROM sentiment_scores WHERE id = ?", [score.id])
            con.executemany(
                """
                INSERT INTO sentiment_scores
                (id, article_id, symbol, label, score, positive, neutral, negative,
                 model, explanation, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        score.id,
                        score.article_id,
                        score.symbol,
                        score.label,
                        score.score,
                        score.positive,
                        score.neutral,
                        score.negative,
                        score.model,
                        score.explanation,
                        as_utc_naive(score.created_at),
                    ]
                    for score in scores
                ],
            )

    def _load_articles(self, symbol: str, article_ids: list[str] | None) -> list[NewsArticle]:
        clauses = ["symbol = ?"]
        params: list[Any] = [symbol.upper()]
        if article_ids:
            placeholders = ",".join(["?"] * len(article_ids))
            clauses.append(f"id IN ({placeholders})")
            params.extend(article_ids)
        with connection(self.settings) as con:
            rows = rows_to_dicts(
                con.execute(
                    f"""
                    SELECT id, source, symbol, headline, summary, url, author,
                           published_at, content, raw_symbols
                    FROM news_articles
                    WHERE {' AND '.join(clauses)}
                    ORDER BY published_at DESC
                    """,
                    params,
                )
            )
        articles: list[NewsArticle] = []
        for row in rows:
            row["raw_symbols"] = json.loads(row["raw_symbols"] or "[]")
            articles.append(NewsArticle(**row))
        return articles

    def _score_with_finbert_or_lexicon(self, text: str) -> tuple[dict[str, float], str]:
        pipeline = self._load_pipeline()
        if pipeline is not None:
            try:
                results = pipeline(text[:1800], truncation=True, top_k=None)
                if results and isinstance(results[0], list):
                    results = results[0]
                probabilities = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
                for item in results:
                    label = str(item["label"]).lower()
                    if label in probabilities:
                        probabilities[label] = float(item["score"])
                total = sum(probabilities.values()) or 1.0
                return {key: value / total for key, value in probabilities.items()}, "ProsusAI/finbert"
            except Exception as exc:  # pragma: no cover - depends on optional model runtime
                self._pipeline_error = str(exc)
        return self._lexicon_score(text), "lexicon-fallback"

    def _load_pipeline(self) -> Any | None:
        if self._pipeline is not None or self._pipeline_error is not None:
            return self._pipeline
        try:
            from transformers import pipeline

            self._pipeline = pipeline("text-classification", model="ProsusAI/finbert")
        except Exception as exc:  # pragma: no cover - optional dependency/model download
            self._pipeline_error = str(exc)
            self._pipeline = None
            logger.info("finbert_unavailable fallback=lexicon reason=%s", exc)
        return self._pipeline

    @staticmethod
    def _lexicon_score(text: str) -> dict[str, float]:
        tokens = {token.strip(".,:;!?()[]{}'\"").lower() for token in text.split()}
        pos = len(tokens & POSITIVE_WORDS)
        neg = len(tokens & NEGATIVE_WORDS)
        positive = 0.2 + pos * 0.25
        negative = 0.2 + neg * 0.25
        neutral = 0.7 if pos == neg else 0.35
        total = positive + neutral + negative
        return {
            "positive": positive / total,
            "neutral": neutral / total,
            "negative": negative / total,
        }

    async def _ollama_summary(self, article: NewsArticle, label: str) -> str | None:
        article_text = " ".join(str(article.summary or article.content or "").split())[:1200]
        prompt = (
            "Resume en una frase el catalizador principal de esta noticia financiera y "
            "di por que el sentimiento podria ser relevante para trading. "
            f"Ticker: {article.symbol}. Sentimiento base: {label}. "
            f"Titulo: {article.headline}. Resumen: {article_text}"
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=2.0)) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url}/api/chat",
                    json={
                        "model": self.settings.ollama_model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": "Responde en espanol, breve y cuantitativo."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
            if response.status_code >= 400:
                logger.warning(
                    "ollama_summary_failed article_id=%s status=%s body=%s",
                    article.id,
                    response.status_code,
                    response.text[:200],
                )
                return None
            content = response.json().get("message", {}).get("content")
            return str(content).strip()[:500] if content else None
        except httpx.TimeoutException:
            logger.warning(
                "ollama_summary_timeout article_id=%s model=%s timeout_seconds=8",
                article.id,
                self.settings.ollama_model,
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning("ollama_summary_error article_id=%s error=%s", article.id, exc)
            return None
