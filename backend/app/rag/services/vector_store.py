"""
Vector Store Service
=====================
pgvector-backed vector storage and retrieval.

Operations:
  - upsert_chunks   : Embed + store document chunks
  - semantic_search : ANN search via pgvector
  - delete_document : Remove all vectors for a document
  - create_index    : Build IVFFlat or HNSW index

Uses pgvector's <=> operator (cosine distance) for similarity search.
Metadata filtering is pushed into WHERE clause before the vector scan
for significant performance gains on large collections.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.documents.services.chunker import DocumentChunk
from app.rag.services.embedding_service import EmbeddingService, get_embedding_service

logger = get_logger(__name__)


@dataclass
class VectorSearchResult:
    chunk_id: str
    document_id: str
    chunk_text: str
    score: float                   # Cosine similarity (0–1, higher = more similar)
    knowledge_base: str
    document_type: Optional[str]
    page_numbers: Optional[list]
    metadata: Optional[Dict[str, Any]]
    rank: int = 0


class VectorStoreService:
    """
    Manages pgvector storage and similarity search.
    All SQL is raw to use pgvector operators not supported by ORM.
    """

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: Optional[EmbeddingService] = None,
    ) -> None:
        self.session = session
        self.emb = embedding_service or get_embedding_service()

    # ──────────────────────────────────────────
    # Upsert Chunks
    # ──────────────────────────────────────────

    async def upsert_chunks(
        self,
        chunks: List[DocumentChunk],
        document_id: uuid.UUID,
        user_id: uuid.UUID,
        knowledge_base: str,
        document_type: Optional[str] = None,
        bank_id: Optional[uuid.UUID] = None,
        language: Optional[str] = None,
        loan_application_id: Optional[uuid.UUID] = None,
    ) -> int:
        """
        Embed all chunks and upsert into document_vectors.
        Returns count of vectors stored.
        """
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        embeddings = await self.emb.embed_batch(texts)

        stored = 0
        for chunk, embedding in zip(chunks, embeddings):
            vec_str = "[" + ",".join(str(round(v, 8)) for v in embedding) + "]"

            await self.session.execute(
                text("""
                    INSERT INTO document_vectors (
                        id, document_id, chunk_id, user_id, loan_application_id,
                        chunk_text, chunk_index, page_numbers,
                        knowledge_base, document_type, bank_id, language,
                        embedding_model, embedding_dimension, is_indexed,
                        metadata, embedding, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :doc_id, :chunk_id, :user_id, :loan_id,
                        :text, :idx, :pages,
                        :kb, :doc_type, :bank_id, :lang,
                        :model, :dim, false,
                        :meta, :embedding::vector, NOW(), NOW()
                    )
                    ON CONFLICT (chunk_id, embedding_model)
                    DO UPDATE SET
                        chunk_text = EXCLUDED.chunk_text,
                        embedding = EXCLUDED.embedding,
                        is_indexed = false,
                        updated_at = NOW()
                """),
                {
                    "doc_id": str(document_id),
                    "chunk_id": chunk.chunk_id,
                    "user_id": str(user_id),
                    "loan_id": str(loan_application_id) if loan_application_id else None,
                    "text": chunk.text,
                    "idx": chunk.chunk_index,
                    "pages": chunk.page_numbers,
                    "kb": knowledge_base,
                    "doc_type": document_type,
                    "bank_id": str(bank_id) if bank_id else None,
                    "lang": language,
                    "model": self.emb.model_name,
                    "dim": self.emb.dim,
                    "meta": chunk.metadata or {},
                    "embedding": vec_str,
                }
            )
            stored += 1

        await self.session.flush()
        logger.info(
            "vector_store.upserted",
            document_id=str(document_id),
            chunks=stored,
            knowledge_base=knowledge_base,
        )
        return stored

    # ──────────────────────────────────────────
    # Semantic Search (ANN via pgvector)
    # ──────────────────────────────────────────

    async def semantic_search(
        self,
        query: str,
        knowledge_base: str,
        top_k: Optional[int] = None,
        user_id: Optional[uuid.UUID] = None,
        bank_id: Optional[uuid.UUID] = None,
        document_type: Optional[str] = None,
        language: Optional[str] = None,
        loan_application_id: Optional[uuid.UUID] = None,
        similarity_threshold: Optional[float] = None,
    ) -> List[VectorSearchResult]:
        """
        Cosine similarity ANN search with metadata filtering.
        Returns ranked results above similarity threshold.
        """
        k = top_k or settings.rag.top_k_semantic
        threshold = similarity_threshold or settings.rag.similarity_threshold

        query_embedding = await self.emb.embed_text(query)
        vec_str = "[" + ",".join(str(round(v, 8)) for v in query_embedding) + "]"

        # Build WHERE clause for metadata pre-filtering
        filters = ["knowledge_base = :kb", "is_indexed = true OR is_indexed = false"]
        params: Dict[str, Any] = {
            "kb": knowledge_base,
            "vec": vec_str,
            "k": k * 2,           # Over-fetch before threshold filter
            "threshold": 1 - threshold,   # pgvector cosine DISTANCE (lower = similar)
        }

        if user_id:
            filters.append("user_id = :user_id")
            params["user_id"] = str(user_id)
        if bank_id:
            filters.append("(bank_id = :bank_id OR bank_id IS NULL)")
            params["bank_id"] = str(bank_id)
        if document_type:
            filters.append("document_type = :doc_type")
            params["doc_type"] = document_type
        if language:
            filters.append("(language = :lang OR language IS NULL)")
            params["lang"] = language
        if loan_application_id:
            filters.append("loan_application_id = :loan_id")
            params["loan_id"] = str(loan_application_id)

        where_clause = " AND ".join(filters)

        sql = text(f"""
            SELECT
                chunk_id,
                document_id::text,
                chunk_text,
                knowledge_base,
                document_type,
                page_numbers,
                metadata,
                1 - (embedding <=> :vec::vector) AS similarity
            FROM document_vectors
            WHERE {where_clause}
              AND 1 - (embedding <=> :vec::vector) >= :threshold
            ORDER BY embedding <=> :vec::vector
            LIMIT :k
        """)

        result = await self.session.execute(sql, params)
        rows = result.fetchall()

        results = [
            VectorSearchResult(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                chunk_text=row.chunk_text,
                score=float(row.similarity),
                knowledge_base=row.knowledge_base,
                document_type=row.document_type,
                page_numbers=row.page_numbers,
                metadata=row.metadata,
                rank=i + 1,
            )
            for i, row in enumerate(rows[:k])
        ]

        logger.info(
            "vector_store.semantic_search",
            kb=knowledge_base,
            query_len=len(query),
            results=len(results),
            top_score=results[0].score if results else 0,
        )
        return results

    # ──────────────────────────────────────────
    # Delete
    # ──────────────────────────────────────────

    async def delete_document_vectors(self, document_id: uuid.UUID) -> int:
        result = await self.session.execute(
            text("DELETE FROM document_vectors WHERE document_id = :doc_id RETURNING id"),
            {"doc_id": str(document_id)}
        )
        deleted = len(result.fetchall())
        await self.session.flush()
        logger.info("vector_store.deleted", document_id=str(document_id), count=deleted)
        return deleted

    # ──────────────────────────────────────────
    # Index Management
    # ──────────────────────────────────────────

    async def create_ivfflat_index(self) -> None:
        """Create IVFFlat index — good for < 1M vectors."""
        await self.session.execute(text("SET maintenance_work_mem = '512MB'"))
        await self.session.execute(text(f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_vectors_embedding_ivfflat
            ON document_vectors
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = {settings.rag.vector_index_lists})
        """))
        logger.info("vector_store.index.ivfflat_created")

    async def create_hnsw_index(self) -> None:
        """Create HNSW index — better recall, good for large collections."""
        await self.session.execute(text(f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_vectors_embedding_hnsw
            ON document_vectors
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = {settings.rag.hnsw_m}, ef_construction = {settings.rag.hnsw_ef_construction})
        """))
        logger.info("vector_store.index.hnsw_created")

    async def get_stats(self, knowledge_base: Optional[str] = None) -> Dict[str, Any]:
        """Return collection statistics."""
        where = "WHERE knowledge_base = :kb" if knowledge_base else ""
        params = {"kb": knowledge_base} if knowledge_base else {}
        result = await self.session.execute(
            text(f"""
                SELECT
                    COUNT(*) as total_vectors,
                    COUNT(DISTINCT document_id) as total_documents,
                    COUNT(DISTINCT knowledge_base) as total_kbs,
                    AVG(LENGTH(chunk_text)) as avg_chunk_chars
                FROM document_vectors {where}
            """),
            params
        )
        row = result.fetchone()
        return {
            "total_vectors": row.total_vectors,
            "total_documents": row.total_documents,
            "total_knowledge_bases": row.total_kbs,
            "avg_chunk_chars": round(float(row.avg_chunk_chars or 0), 1),
        }
