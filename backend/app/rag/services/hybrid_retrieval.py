"""
Hybrid Retrieval Service
==========================
Combines semantic (dense) and BM25 (sparse) retrieval
using Reciprocal Rank Fusion (RRF) for score merging.

Pipeline:
  1. Semantic search (pgvector ANN)
  2. BM25 keyword search (rank-bm25)
  3. RRF score fusion
  4. Deduplication
  5. Reranking (optional, cross-encoder)

RRF formula: score(d) = Σ 1 / (k + rank(d))
  where k=60 (standard constant) and rank is 1-indexed position.

Alpha parameter controls semantic vs BM25 balance:
  alpha=1.0 → pure semantic
  alpha=0.0 → pure BM25
  alpha=0.6 → 60% semantic, 40% BM25 (default)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.retrievers.bm25_retriever import BM25Retriever
from app.rag.services.reranker import CohereReranker, RerankResult, get_reranker
from app.rag.services.vector_store import VectorSearchResult, VectorStoreService

logger = get_logger(__name__)

RRF_K = 60   # Standard RRF constant


@dataclass
class HybridSearchResult:
    chunk_id: str
    document_id: str
    chunk_text: str
    hybrid_score: float
    semantic_score: Optional[float]
    bm25_score: Optional[float]
    rerank_score: Optional[float]
    knowledge_base: str
    document_type: Optional[str]
    page_numbers: Optional[list]
    metadata: Optional[Dict[str, Any]]
    rank: int
    retrieval_method: str = "hybrid"


@dataclass
class RetrievalObservability:
    query: str
    knowledge_base: str
    semantic_count: int
    bm25_count: int
    fused_count: int
    final_count: int
    reranked: bool
    alpha: float
    top_score: float
    latency_ms: int
    filters: Dict[str, Any] = field(default_factory=dict)


class HybridRetrievalService:
    """
    Unified retrieval service combining semantic + BM25.
    Entry point for all RAG retrieval operations.
    """

    def __init__(
        self,
        session: AsyncSession,
        vector_store: Optional[VectorStoreService] = None,
        bm25: Optional[BM25Retriever] = None,
        reranker: Optional[CohereReranker] = None,
    ) -> None:
        self.session = session
        self.vector_store = vector_store or VectorStoreService(session)
        self.bm25 = bm25 or BM25Retriever()
        self.reranker = reranker or get_reranker()

    async def retrieve(
        self,
        query: str,
        knowledge_base: str,
        top_k: Optional[int] = None,
        alpha: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None,
        rerank: Optional[bool] = None,
    ) -> tuple[List[HybridSearchResult], RetrievalObservability]:
        """
        Main retrieval method. Returns ranked results + observability data.

        Args:
            query:          Search query (natural language)
            knowledge_base: KB name to search within
            top_k:          Final result count after reranking
            alpha:          Semantic weight (0.0–1.0)
            filters:        Metadata filters (doc_type, bank_id, language, etc.)
            rerank:         Override reranking setting
        """
        import time
        start = time.perf_counter()

        k_final = top_k or settings.rag.top_k_final
        k_hybrid = settings.rag.top_k_hybrid
        a = alpha if alpha is not None else settings.rag.hybrid_alpha
        do_rerank = rerank if rerank is not None else settings.rag.reranker_enabled
        filters = filters or {}

        import uuid
        user_id = filters.get("user_id")
        bank_id = filters.get("bank_id")
        doc_type = filters.get("document_type")
        language = filters.get("language")
        loan_id = filters.get("loan_application_id")

        # ── Step 1: Semantic retrieval ────────────────────
        semantic_results = await self.vector_store.semantic_search(
            query=query,
            knowledge_base=knowledge_base,
            top_k=k_hybrid,
            user_id=uuid.UUID(str(user_id)) if user_id else None,
            bank_id=uuid.UUID(str(bank_id)) if bank_id else None,
            document_type=doc_type,
            language=language,
            loan_application_id=uuid.UUID(str(loan_id)) if loan_id else None,
        )

        # ── Step 2: BM25 retrieval ────────────────────────
        bm25_results = await self.bm25.search(
            query=query,
            knowledge_base=knowledge_base,
            top_k=k_hybrid,
            filters=filters,
            session=self.session,
        )

        # ── Step 3: RRF Fusion ────────────────────────────
        fused = self._rrf_fuse(semantic_results, bm25_results, alpha=a)

        # ── Step 4: Rerank ────────────────────────────────
        reranked_map: Dict[str, float] = {}
        if do_rerank and fused:
            # Convert to VectorSearchResult for reranker input
            candidates = [
                VectorSearchResult(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    chunk_text=r.chunk_text,
                    score=r.hybrid_score,
                    knowledge_base=r.knowledge_base,
                    document_type=r.document_type,
                    page_numbers=r.page_numbers,
                    metadata=r.metadata,
                )
                for r in fused[:k_hybrid]
            ]
            reranked = await self.reranker.rerank(query, candidates, top_k=k_final)
            for rr in reranked:
                reranked_map[rr.chunk_id] = rr.rerank_score

            # Re-sort fused results by rerank score
            fused.sort(
                key=lambda x: reranked_map.get(x.chunk_id, 0),
                reverse=True
            )
            for i, r in enumerate(fused):
                r.rank = i + 1
                if r.chunk_id in reranked_map:
                    r.rerank_score = reranked_map[r.chunk_id]
                    r.retrieval_method = "hybrid+rerank"

        final = fused[:k_final]
        latency_ms = int((time.perf_counter() - start) * 1000)

        obs = RetrievalObservability(
            query=query,
            knowledge_base=knowledge_base,
            semantic_count=len(semantic_results),
            bm25_count=len(bm25_results),
            fused_count=len(fused),
            final_count=len(final),
            reranked=do_rerank and bool(reranked_map),
            alpha=a,
            top_score=final[0].hybrid_score if final else 0.0,
            latency_ms=latency_ms,
            filters=filters,
        )

        if settings.rag.retrieval_logging_enabled:
            logger.info(
                "retrieval.complete",
                kb=knowledge_base,
                semantic=obs.semantic_count,
                bm25=obs.bm25_count,
                final=obs.final_count,
                reranked=obs.reranked,
                latency_ms=latency_ms,
                top_score=round(obs.top_score, 4),
            )

        return final, obs

    def _rrf_fuse(
        self,
        semantic: List[VectorSearchResult],
        bm25: List[VectorSearchResult],
        alpha: float = 0.6,
    ) -> List[HybridSearchResult]:
        """
        Reciprocal Rank Fusion — merges two ranked lists.
        RRF is robust to different score scales between retrievers.
        """
        rrf_scores: Dict[str, Dict] = {}

        # Semantic contributions
        for rank, result in enumerate(semantic, start=1):
            cid = result.chunk_id
            rrf_semantic = alpha * (1 / (RRF_K + rank))
            if cid not in rrf_scores:
                rrf_scores[cid] = {
                    "result": result,
                    "semantic_score": result.score,
                    "bm25_score": None,
                    "rrf": 0.0,
                }
            rrf_scores[cid]["rrf"] += rrf_semantic

        # BM25 contributions
        for rank, result in enumerate(bm25, start=1):
            cid = result.chunk_id
            rrf_bm25 = (1 - alpha) * (1 / (RRF_K + rank))
            if cid not in rrf_scores:
                rrf_scores[cid] = {
                    "result": result,
                    "semantic_score": None,
                    "bm25_score": result.score,
                    "rrf": 0.0,
                }
            else:
                rrf_scores[cid]["bm25_score"] = result.score
            rrf_scores[cid]["rrf"] += rrf_bm25

        # Sort by RRF score
        sorted_items = sorted(
            rrf_scores.values(), key=lambda x: x["rrf"], reverse=True
        )

        fused = []
        for rank, item in enumerate(sorted_items, start=1):
            r = item["result"]
            method = "hybrid"
            if item["semantic_score"] and not item["bm25_score"]:
                method = "semantic"
            elif item["bm25_score"] and not item["semantic_score"]:
                method = "bm25"

            fused.append(HybridSearchResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                chunk_text=r.chunk_text,
                hybrid_score=round(item["rrf"], 6),
                semantic_score=item["semantic_score"],
                bm25_score=item["bm25_score"],
                rerank_score=None,
                knowledge_base=r.knowledge_base,
                document_type=r.document_type,
                page_numbers=r.page_numbers,
                metadata=r.metadata,
                rank=rank,
                retrieval_method=method,
            ))

        return fused
