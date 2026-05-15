"""
Embedding Service
==================
Generates dense vector embeddings for text chunks.

Model: paraphrase-multilingual-mpnet-base-v2 (768-dim)
  - Supports 50+ languages including Hindi, English
  - Optimized for semantic similarity
  - Swap model via RAG_EMBEDDING_MODEL env var

Features:
  - Redis embedding cache (SHA-256 keyed, 24h TTL)
  - Batch processing for throughput
  - Thread-pool execution (CPU-bound)
  - Embedding normalization (for cosine similarity)
  - Observability logging
"""

import asyncio
import hashlib
import json
from functools import partial
from typing import List, Optional

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_model = None                      # Lazy-loaded singleton


def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("embedding.model.loading", model=settings.rag.embedding_model)
        _model = SentenceTransformer(settings.rag.embedding_model)
        logger.info(
            "embedding.model.loaded",
            model=settings.rag.embedding_model,
            dim=settings.rag.embedding_dimension,
        )
    return _model


# ──────────────────────────────────────────────
# Cache Key
# ──────────────────────────────────────────────

def _cache_key(text: str, model: str) -> str:
    h = hashlib.sha256(f"{model}::{text}".encode()).hexdigest()
    return f"emb:{h}"


# ──────────────────────────────────────────────
# Embedding Service
# ──────────────────────────────────────────────

class EmbeddingService:
    """
    Generates normalized embedding vectors.
    Caches results in Redis to avoid recomputation.
    """

    def __init__(self) -> None:
        self.model_name = settings.rag.embedding_model
        self.dim = settings.rag.embedding_dimension
        self.batch_size = settings.rag.embedding_batch_size
        self.cache_ttl = settings.rag.embedding_cache_ttl

    async def embed_text(self, text: str) -> List[float]:
        """Embed a single text string. Returns normalized float list."""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(
        self, texts: List[str], use_cache: bool = True
    ) -> List[List[float]]:
        """
        Embed a list of texts. Checks cache first, batches uncached texts.
        Returns list of embedding vectors in same order as input.
        """
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        # Check cache
        if use_cache:
            cache_results = await self._batch_cache_get(texts)
            for i, cached in enumerate(cache_results):
                if cached is not None:
                    results[i] = cached
                else:
                    uncached_indices.append(i)
                    uncached_texts.append(texts[i])
        else:
            uncached_indices = list(range(len(texts)))
            uncached_texts = texts

        # Compute uncached embeddings
        if uncached_texts:
            computed = await self._compute_embeddings(uncached_texts)
            for idx, (i, vec) in enumerate(zip(uncached_indices, computed)):
                results[i] = vec
                if use_cache:
                    asyncio.create_task(
                        self._cache_set(_cache_key(uncached_texts[idx], self.model_name), vec)
                    )

        logger.info(
            "embedding.batch_complete",
            total=len(texts),
            cache_hits=len(texts) - len(uncached_texts),
            computed=len(uncached_texts),
        )

        return [r for r in results if r is not None]

    async def _compute_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Run sentence-transformers in thread pool (CPU-bound)."""
        loop = asyncio.get_event_loop()

        def _encode():
            model = _load_model()
            # Process in batches
            all_vecs = []
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i:i + self.batch_size]
                vecs = model.encode(
                    batch,
                    normalize_embeddings=True,  # Unit vectors for cosine similarity
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )
                all_vecs.extend(vecs.tolist())
            return all_vecs

        return await loop.run_in_executor(None, _encode)

    async def _batch_cache_get(
        self, texts: List[str]
    ) -> List[Optional[List[float]]]:
        try:
            from app.db.cache import get_redis_client
            client = get_redis_client()
            keys = [_cache_key(t, self.model_name) for t in texts]
            values = await client.mget(keys)
            results = []
            for v in values:
                if v:
                    results.append(json.loads(v))
                else:
                    results.append(None)
            return results
        except Exception as exc:
            logger.warning("embedding.cache.get_failed", error=str(exc))
            return [None] * len(texts)

    async def _cache_set(self, key: str, vector: List[float]) -> None:
        try:
            from app.db.cache import get_redis_client
            client = get_redis_client()
            await client.setex(key, self.cache_ttl, json.dumps(vector))
        except Exception as exc:
            logger.warning("embedding.cache.set_failed", error=str(exc))

    async def warm_cache(self, texts: List[str]) -> None:
        """Pre-warm the embedding cache for a list of texts."""
        logger.info("embedding.cache.warming", count=len(texts))
        await self.embed_batch(texts, use_cache=True)
        logger.info("embedding.cache.warmed")

    def get_zero_vector(self) -> List[float]:
        """Return a zero vector of the correct dimension (for fallback)."""
        return [0.0] * self.dim


# ── Singleton ────────────────────────────────
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
