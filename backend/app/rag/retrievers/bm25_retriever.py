"""
BM25 Retriever
===============
Sparse keyword retrieval using BM25 (Best Match 25).
Complements semantic search — excels at exact term matching,
acronyms, document numbers, PAN/Aadhaar, amounts.

Implementation:
  - rank-bm25 library for scoring
  - Corpus is loaded from DB per knowledge_base (cached in Redis)
  - NLTK tokenization with stopword removal
  - Multilingual tokenization (Hindi + English)
  - Corpus cache: 1 hour TTL (refreshed on new document ingestion)
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.services.vector_store import VectorSearchResult

logger = get_logger(__name__)

# Download NLTK data on first use (non-blocking)
_nltk_ready = False


def _ensure_nltk():
    global _nltk_ready
    if not _nltk_ready:
        import nltk
        for pkg in ["punkt", "stopwords", "punkt_tab"]:
            try:
                nltk.download(pkg, quiet=True)
            except Exception:
                pass
        _nltk_ready = True


@dataclass
class BM25Corpus:
    knowledge_base: str
    chunk_ids: List[str]
    document_ids: List[str]
    texts: List[str]
    tokenized: List[List[str]]
    metadata: List[Dict[str, Any]]


class BM25Retriever:
    """
    BM25 keyword retriever with Redis-cached corpus.
    Loaded lazily per knowledge_base and refreshed periodically.
    """

    CACHE_TTL = 3600             # 1 hour
    CACHE_PREFIX = "bm25:corpus"

    def __init__(self) -> None:
        _ensure_nltk()
        self._stopwords = self._load_stopwords()

    # ──────────────────────────────────────────
    # Search
    # ──────────────────────────────────────────

    async def search(
        self,
        query: str,
        knowledge_base: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        session=None,
    ) -> List[VectorSearchResult]:
        """
        BM25 keyword search over a knowledge base corpus.
        Returns scored results sorted by relevance.
        """
        from rank_bm25 import BM25Okapi
        import asyncio

        k = top_k or settings.rag.top_k_bm25
        corpus = await self._load_corpus(knowledge_base, session)

        if not corpus or not corpus.tokenized:
            logger.warning("bm25.corpus_empty", kb=knowledge_base)
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # Apply metadata pre-filters
        filtered_indices = self._apply_filters(corpus, filters or {})
        if not filtered_indices:
            return []

        filtered_tokenized = [corpus.tokenized[i] for i in filtered_indices]
        bm25 = BM25Okapi(filtered_tokenized)
        scores = bm25.get_scores(query_tokens)

        # Sort by score descending
        ranked = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )[:k]

        results = []
        for rank, (local_idx, score) in enumerate(ranked):
            if score <= 0:
                continue
            orig_idx = filtered_indices[local_idx]
            meta = corpus.metadata[orig_idx]

            # Normalize BM25 score to 0–1 range
            max_score = ranked[0][1] if ranked else 1
            normalized = score / max_score if max_score > 0 else 0

            results.append(VectorSearchResult(
                chunk_id=corpus.chunk_ids[orig_idx],
                document_id=corpus.document_ids[orig_idx],
                chunk_text=corpus.texts[orig_idx],
                score=round(normalized, 4),
                knowledge_base=knowledge_base,
                document_type=meta.get("document_type"),
                page_numbers=meta.get("page_numbers"),
                metadata=meta,
                rank=rank + 1,
            ))

        logger.info(
            "bm25.search_complete",
            kb=knowledge_base,
            query_tokens=len(query_tokens),
            results=len(results),
        )
        return results

    # ──────────────────────────────────────────
    # Corpus Management
    # ──────────────────────────────────────────

    async def _load_corpus(
        self, knowledge_base: str, session=None
    ) -> Optional[BM25Corpus]:
        """Load corpus from Redis cache or DB."""
        cached = await self._cache_get(knowledge_base)
        if cached:
            return cached

        if session:
            corpus = await self._build_from_db(knowledge_base, session)
            if corpus:
                await self._cache_set(knowledge_base, corpus)
            return corpus
        return None

    async def _build_from_db(
        self, knowledge_base: str, session
    ) -> Optional[BM25Corpus]:
        """Build BM25 corpus by loading all chunks from DB."""
        from sqlalchemy import text

        result = await session.execute(
            text("""
                SELECT chunk_id, document_id::text, chunk_text,
                       document_type, page_numbers, metadata
                FROM document_vectors
                WHERE knowledge_base = :kb
                ORDER BY chunk_id
            """),
            {"kb": knowledge_base}
        )
        rows = result.fetchall()

        if not rows:
            return None

        chunk_ids, doc_ids, texts, tokenized, metas = [], [], [], [], []
        for row in rows:
            chunk_ids.append(row.chunk_id)
            doc_ids.append(row.document_id)
            texts.append(row.chunk_text)
            tokenized.append(self._tokenize(row.chunk_text))
            metas.append({
                "document_type": row.document_type,
                "page_numbers": row.page_numbers,
                **(row.metadata or {}),
            })

        logger.info(
            "bm25.corpus_built",
            kb=knowledge_base,
            chunks=len(rows),
        )
        return BM25Corpus(
            knowledge_base=knowledge_base,
            chunk_ids=chunk_ids,
            document_ids=doc_ids,
            texts=texts,
            tokenized=tokenized,
            metadata=metas,
        )

    async def invalidate_cache(self, knowledge_base: str) -> None:
        """Invalidate corpus cache when new docs are indexed."""
        try:
            from app.db.cache import get_redis_client
            client = get_redis_client()
            await client.delete(f"{self.CACHE_PREFIX}:{knowledge_base}")
            logger.info("bm25.cache_invalidated", kb=knowledge_base)
        except Exception:
            pass

    # ──────────────────────────────────────────
    # Tokenization
    # ──────────────────────────────────────────

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text with stopword removal."""
        try:
            from nltk.tokenize import word_tokenize
            tokens = word_tokenize(text.lower())
        except Exception:
            tokens = re.findall(r"\b\w+\b", text.lower())

        return [
            t for t in tokens
            if t not in self._stopwords
            and len(t) > 1
            and not t.isdigit()
        ]

    @staticmethod
    def _load_stopwords() -> set:
        try:
            from nltk.corpus import stopwords
            en = set(stopwords.words("english"))
            try:
                hi = {"का", "की", "के", "में", "है", "हैं", "और", "या", "पर", "से", "को", "यह"}
            except Exception:
                hi = set()
            return en | hi
        except Exception:
            return {"the", "a", "an", "is", "in", "of", "for", "to", "and", "or"}

    @staticmethod
    def _apply_filters(
        corpus: BM25Corpus, filters: Dict[str, Any]
    ) -> List[int]:
        """Return indices that pass all metadata filters."""
        indices = list(range(len(corpus.texts)))
        if not filters:
            return indices

        doc_type = filters.get("document_type")
        doc_id = filters.get("document_id")

        filtered = []
        for i in indices:
            meta = corpus.metadata[i]
            if doc_type and meta.get("document_type") != doc_type:
                continue
            if doc_id and corpus.document_ids[i] != str(doc_id):
                continue
            filtered.append(i)
        return filtered

    # ──────────────────────────────────────────
    # Redis Cache
    # ──────────────────────────────────────────

    async def _cache_get(self, knowledge_base: str) -> Optional[BM25Corpus]:
        try:
            from app.db.cache import get_redis_client
            client = get_redis_client()
            data = await client.get(f"{self.CACHE_PREFIX}:{knowledge_base}")
            if not data:
                return None
            d = json.loads(data)
            return BM25Corpus(**d)
        except Exception:
            return None

    async def _cache_set(self, knowledge_base: str, corpus: BM25Corpus) -> None:
        try:
            from app.db.cache import get_redis_client
            import dataclasses
            client = get_redis_client()
            await client.setex(
                f"{self.CACHE_PREFIX}:{knowledge_base}",
                self.CACHE_TTL,
                json.dumps(dataclasses.asdict(corpus)),
            )
        except Exception:
            pass
