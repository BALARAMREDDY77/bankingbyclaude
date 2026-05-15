"""
Vector Store Model (pgvector)
==============================
Stores document chunk embeddings alongside their text and metadata.
Supports both IVFFlat and HNSW indexes for approximate nearest-neighbor search.

Table: document_vectors
- Linked to document_chunks (Phase 4)
- Stores 768-dim embedding vectors
- Filtered by knowledge_base, bank_id, doc_type, language
"""

import uuid
from typing import Optional

from sqlalchemy import (
    Boolean, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DocumentVector(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Stores text chunks + their embedding vectors.
    One row per chunk. Linked to source document for provenance.
    """
    __tablename__ = "document_vectors"

    # Source provenance
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("uploaded_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[str] = mapped_column(
        String(150), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    loan_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Chunk content
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_numbers: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Classification for filtering
    knowledge_base: Mapped[str] = mapped_column(
        String(100), nullable=False,
        default="general_banking", index=True
    )
    document_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    bank_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)

    # Embedding metadata
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # The vector column is added via raw SQL in migration (pgvector type)
    # embedding: vector(768)  ← defined in migration, not in ORM

    # Rich metadata for filtering and display
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_model", name="uq_vectors_chunk_model"),
        Index("ix_vectors_knowledge_base", "knowledge_base"),
        Index("ix_vectors_doc_type", "document_type"),
        Index("ix_vectors_bank_id", "bank_id"),
        Index("ix_vectors_language", "language"),
        Index("ix_vectors_user_kb", "user_id", "knowledge_base"),
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentVector id={self.id} "
            f"chunk={self.chunk_id} kb={self.knowledge_base}>"
        )


class KnowledgeBase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Registry of knowledge bases.
    Each bank has its own KB + global banking KB.
    """
    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bank_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("banks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_global: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_knowledge_bases_bank", "bank_id"),
        Index("ix_knowledge_bases_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase name={self.name} bank={self.bank_id}>"
