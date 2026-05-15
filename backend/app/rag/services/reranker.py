"""
Reranking Service
==================
Cross-encoder reranking of retrieved candidates.
Takes top-K candidates from hybrid retrieval and reorders
them using a more expensive but accurate cross-encoder model.

Backends:
  1. Cohere Rerank API (multilingual, production-grade)
  2. Local cross-encoder fallback (sentence-transformers)

Reranking dramatically improves precision — especially important
for banking where wrong document retrieval has compliance implications.
"""

from dataclasses import dataclass
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.services.vector_store import VectorSearchResult

logger = get_logger(__name__)


@dataclass
class RerankResult:
    chunk_id: str
    document_id: str
    chunk_text: str
    original_score: float
    rerank_score: float
    knowledge_base: str
    document_type: Optional[str]
    page_numbers: Optional[list]
    metadata: Optional[dict]
    rank: int


class CohereReranker:
    """
    Cohere Rerank API — best multilingual reranking quality.
    Falls back to local model if API key not set.
    """

    def __init__(self) -> None:
        self.api_key = settings.rag.cohere_api_key
        self.model = settings.rag.reranker_model
        self._client = None

    def _get_client(self):
        if self._client is None and self.api_key:
            import cohere
            self._client = cohere.Client(self.api_key)
        return self._client

    async def rerank(
        self,
        query: str,
        candidates: List[VectorSearchResult],
        top_k: Optional[int] = None,
    ) -> List[RerankResult]:
        """
        Rerank candidates using Cohere API or local fallback.
        Returns top_k results sorted by rerank score.
        """
        if not candidates:
            return []

        k = top_k or settings.rag.top_k_final
        client = self._get_client()

        if client and self.api_key:
            return await self._cohere_rerank(query, candidates, k, client)
        else:
            logger.warning("reranker.cohere_unavailable.using_local_fallback")
            return await self._local_rerank(query, candidates, k)

    async def _cohere_rerank(
        self,
        query: str,
        candidates: List[VectorSearchResult],
        top_k: int,
        client,
    ) -> List[RerankResult]:
        import asyncio
        from functools import partial

        docs = [c.chunk_text[:512] for c in candidates]

        def _call():
            return client.rerank(
                model=self.model,
                query=query,
                documents=docs,
                top_n=top_k,
            )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _call)

        results = []
        for rank, item in enumerate(response.results):
            orig = candidates[item.index]
            results.append(RerankResult(
                chunk_id=orig.chunk_id,
                document_id=orig.document_id,
                chunk_text=orig.chunk_text,
                original_score=orig.score,
                rerank_score=round(item.relevance_score, 6),
                knowledge_base=orig.knowledge_base,
                document_type=orig.document_type,
                page_numbers=orig.page_numbers,
                metadata=orig.metadata,
                rank=rank + 1,
            ))

        logger.info(
            "reranker.cohere_complete",
            query_len=len(query),
            candidates=len(candidates),
            returned=len(results),
        )
        return results

    async def _local_rerank(
        self,
        query: str,
        candidates: List[VectorSearchResult],
        top_k: int,
    ) -> List[RerankResult]:
        """
        Local cross-encoder reranking using sentence-transformers.
        Slower than Cohere but free and works offline.
        """
        import asyncio
        from functools import partial

        def _score():
            try:
                from sentence_transformers import CrossEncoder
                model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
                pairs = [(query, c.chunk_text[:512]) for c in candidates]
                scores = model.predict(pairs)
                return scores.tolist()
            except Exception as e:
                logger.warning("reranker.local_failed", error=str(e))
                return [c.score for c in candidates]

        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(None, _score)

        paired = list(zip(candidates, scores))
        paired.sort(key=lambda x: x[1], reverse=True)

        results = []
        for rank, (orig, score) in enumerate(paired[:top_k]):
            results.append(RerankResult(
                chunk_id=orig.chunk_id,
                document_id=orig.document_id,
                chunk_text=orig.chunk_text,
                original_score=orig.score,
                rerank_score=round(float(score), 6),
                knowledge_base=orig.knowledge_base,
                document_type=orig.document_type,
                page_numbers=orig.page_numbers,
                metadata=orig.metadata,
                rank=rank + 1,
            ))

        logger.info(
            "reranker.local_complete",
            candidates=len(candidates),
            returned=len(results),
        )
        return results


# ── Singleton ────────────────────────────────
_reranker: Optional[CohereReranker] = None


def get_reranker() -> CohereReranker:
    global _reranker
    if _reranker is None:
        _reranker = CohereReranker()
    return _reranker
