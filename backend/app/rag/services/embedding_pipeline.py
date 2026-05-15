"""
Embedding Ingestion Pipeline
==============================
Connects Phase 4 (document chunking) to Phase 5 (vector store).
Takes chunked documents and stores their embeddings in pgvector.

Flow:
  DocumentChunk[] → EmbeddingService → VectorStoreService → document_vectors table

Also handles:
  - BM25 corpus cache invalidation
  - Incremental re-indexing on document updates
  - Knowledge base statistics updates
"""

import uuid
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.documents.services.chunker import ChunkingResult
from app.rag.retrievers.bm25_retriever import BM25Retriever
from app.rag.services.embedding_service import get_embedding_service
from app.rag.services.vector_store import VectorStoreService

logger = get_logger(__name__)


class EmbeddingPipeline:
    """
    Orchestrates embedding generation and vector storage for document chunks.
    Called after Phase 4 chunking is complete.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.vector_store = VectorStoreService(session, get_embedding_service())
        self.bm25 = BM25Retriever()

    async def index_document(
        self,
        chunking_result: ChunkingResult,
        document_id: uuid.UUID,
        user_id: uuid.UUID,
        knowledge_base: str,
        document_type: Optional[str] = None,
        bank_id: Optional[uuid.UUID] = None,
        language: Optional[str] = None,
        loan_application_id: Optional[uuid.UUID] = None,
    ) -> int:
        """
        Embed and store all chunks for a document.
        Returns count of vectors stored.
        """
        if not chunking_result.chunks:
            logger.warning("embedding_pipeline.no_chunks", doc_id=str(document_id))
            return 0

        logger.info(
            "embedding_pipeline.started",
            doc_id=str(document_id),
            chunks=chunking_result.total_chunks,
            kb=knowledge_base,
        )

        stored = await self.vector_store.upsert_chunks(
            chunks=chunking_result.chunks,
            document_id=document_id,
            user_id=user_id,
            knowledge_base=knowledge_base,
            document_type=document_type,
            bank_id=bank_id,
            language=language,
            loan_application_id=loan_application_id,
        )

        # Invalidate BM25 corpus cache so next search gets fresh corpus
        await self.bm25.invalidate_cache(knowledge_base)

        # Update knowledge base stats
        await self._update_kb_stats(knowledge_base, stored)

        logger.info(
            "embedding_pipeline.complete",
            doc_id=str(document_id),
            vectors_stored=stored,
            kb=knowledge_base,
        )
        return stored

    async def reindex_document(
        self,
        document_id: uuid.UUID,
        chunking_result: ChunkingResult,
        user_id: uuid.UUID,
        knowledge_base: str,
        **kwargs,
    ) -> int:
        """Remove old vectors and re-index with new chunks."""
        deleted = await self.vector_store.delete_document_vectors(document_id)
        logger.info("embedding_pipeline.reindex.deleted_old", count=deleted)
        return await self.index_document(
            chunking_result, document_id, user_id, knowledge_base, **kwargs
        )

    async def delete_document(
        self, document_id: uuid.UUID, knowledge_base: str
    ) -> int:
        """Remove all vectors for a document and invalidate BM25 cache."""
        deleted = await self.vector_store.delete_document_vectors(document_id)
        await self.bm25.invalidate_cache(knowledge_base)
        return deleted

    async def _update_kb_stats(self, knowledge_base: str, new_chunks: int) -> None:
        """Increment chunk count on the knowledge_bases record."""
        try:
            from sqlalchemy import text
            await self.session.execute(
                text("""
                    UPDATE knowledge_bases
                    SET chunk_count = chunk_count + :n,
                        updated_at = NOW()
                    WHERE name = :kb
                """),
                {"n": new_chunks, "kb": knowledge_base}
            )
            await self.session.flush()
        except Exception as exc:
            logger.warning("embedding_pipeline.kb_stats_update_failed", error=str(exc))
