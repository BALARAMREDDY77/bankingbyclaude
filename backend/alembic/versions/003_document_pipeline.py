"""add_document_pipeline_fields

Revision ID: 003_document_pipeline
Revises: 002_domain_tables
Create Date: 2026-05-14

Adds OCR result, chunking metadata, and storage fields
to uploaded_documents table for Phase 4 pipeline.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "003_document_pipeline"
down_revision = "002_domain_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All core columns already created in 002.
    # Add any pipeline-specific columns that were missed or extended.

    # Add chunk storage table for embedding preparation (Phase 5)
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(100), primary_key=True),   # {doc_id}_chunk_{N}
        sa.Column(
            "document_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uploaded_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("char_start", sa.Integer, nullable=False),
        sa.Column("char_end", sa.Integer, nullable=False),
        sa.Column("page_numbers", JSONB, nullable=True),
        sa.Column("word_count", sa.Integer, nullable=False),
        sa.Column("char_count", sa.Integer, nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("embedding_vector", JSONB, nullable=True),  # Phase 5 will populate
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_doc_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_doc_chunks_chunk_index", "document_chunks", ["document_id", "chunk_index"])

    # Add pipeline tracking columns to uploaded_documents
    with op.batch_alter_table("uploaded_documents") as batch_op:
        batch_op.add_column(
            sa.Column("pipeline_version", sa.String(20), nullable=True, server_default="1.0")
        )
        batch_op.add_column(
            sa.Column("processing_time_ms", sa.Integer, nullable=True)
        )
        batch_op.add_column(
            sa.Column("retry_count", sa.Integer, nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("last_error", sa.Text, nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("uploaded_documents") as batch_op:
        batch_op.drop_column("pipeline_version")
        batch_op.drop_column("processing_time_ms")
        batch_op.drop_column("retry_count")
        batch_op.drop_column("last_error")

    op.drop_table("document_chunks")
