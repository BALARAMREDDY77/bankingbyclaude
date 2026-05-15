"""
Retrieval Observability & Scoring
====================================
Tracks retrieval quality metrics and logs structured observability data.
Stores retrieval events to system_metrics table for dashboarding.
"""

import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.rag.services.hybrid_retrieval import HybridSearchResult, RetrievalObservability

logger = get_logger(__name__)


@dataclass
class RetrievalScore:
    """Quality score for a retrieval run."""
    query: str
    result_count: int
    top_score: float
    avg_score: float
    score_variance: float
    has_reranked_results: bool
    coverage_score: float        # % of results above threshold
    latency_ms: int
    quality_label: str           # excellent | good | fair | poor


def score_retrieval(
    results: List[HybridSearchResult],
    obs: RetrievalObservability,
    threshold: float = 0.3,
) -> RetrievalScore:
    """
    Compute a quality score for a retrieval run.
    Used for monitoring retrieval health over time.
    """
    if not results:
        return RetrievalScore(
            query=obs.query,
            result_count=0,
            top_score=0.0,
            avg_score=0.0,
            score_variance=0.0,
            has_reranked_results=obs.reranked,
            coverage_score=0.0,
            latency_ms=obs.latency_ms,
            quality_label="poor",
        )

    scores = [r.hybrid_score for r in results]
    top = max(scores)
    avg = sum(scores) / len(scores)
    variance = sum((s - avg) ** 2 for s in scores) / len(scores)
    coverage = len([s for s in scores if s >= threshold]) / len(scores)

    if top >= 0.7 and avg >= 0.5:
        label = "excellent"
    elif top >= 0.5 and avg >= 0.35:
        label = "good"
    elif top >= 0.3:
        label = "fair"
    else:
        label = "poor"

    score = RetrievalScore(
        query=obs.query,
        result_count=len(results),
        top_score=round(top, 4),
        avg_score=round(avg, 4),
        score_variance=round(variance, 4),
        has_reranked_results=obs.reranked,
        coverage_score=round(coverage, 4),
        latency_ms=obs.latency_ms,
        quality_label=label,
    )

    logger.info(
        "retrieval.quality_score",
        kb=obs.knowledge_base,
        quality=label,
        top_score=score.top_score,
        avg_score=score.avg_score,
        coverage=score.coverage_score,
        latency_ms=obs.latency_ms,
    )
    return score


async def record_retrieval_metric(
    obs: RetrievalObservability,
    score: RetrievalScore,
    session=None,
) -> None:
    """Persist retrieval metrics to system_metrics table."""
    if not session:
        return
    try:
        from app.db.models.ai_system import MetricType
        from app.db.repositories.domain import MetricsRepository

        repo = MetricsRepository(session)
        await repo.record(
            metric_type=MetricType.AI_INFERENCE_TIME,
            metric_name="rag_retrieval_latency",
            value=Decimal(obs.latency_ms),
            unit="ms",
            service="rag",
            endpoint=obs.knowledge_base,
            tags={
                "semantic_count": obs.semantic_count,
                "bm25_count": obs.bm25_count,
                "final_count": obs.final_count,
                "reranked": obs.reranked,
                "quality": score.quality_label,
                "top_score": score.top_score,
            },
        )
    except Exception as exc:
        logger.warning("retrieval.metric_record_failed", error=str(exc))


def format_context_window(
    results: List[HybridSearchResult],
    max_chars: int = 6000,
    include_metadata: bool = True,
) -> str:
    """
    Format retrieval results into a context window string for LLM prompts.
    Truncates to max_chars while preserving document boundaries.
    """
    if not results:
        return ""

    parts = []
    total_chars = 0

    for i, result in enumerate(results, start=1):
        header = f"[Document {i}"
        if result.document_type:
            header += f" | {result.document_type.replace('_', ' ').title()}"
        if result.page_numbers:
            header += f" | Pages {result.page_numbers}"
        header += f" | Relevance: {result.hybrid_score:.2f}]"

        chunk = f"{header}\n{result.chunk_text}"
        chunk_len = len(chunk)

        if total_chars + chunk_len > max_chars:
            # Truncate this chunk to fit
            remaining = max_chars - total_chars - len(header) - 4
            if remaining > 100:
                chunk = f"{header}\n{result.chunk_text[:remaining]}..."
                parts.append(chunk)
            break

        parts.append(chunk)
        total_chars += chunk_len + 2

    context = "\n\n".join(parts)
    logger.debug(
        "context_window.formatted",
        results_used=len(parts),
        total_results=len(results),
        chars=len(context),
    )
    return context
