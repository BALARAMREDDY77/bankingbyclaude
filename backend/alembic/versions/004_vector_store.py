"""create_vector_store_tables

Revision ID: 004_vector_store
Revises: 003_document_pipeline
Create Date: 2026-05-14

Enables pgvector extension and creates:
  - document_vectors (embeddings + metadata)
  - knowledge_bases (KB registry)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "004_vector_store"
down_revision = "003_document_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── knowledge_bases ─────────────────────────────────────
    op.create_table(
        "knowledge_bases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("bank_id", UUID(as_uuid=True),
                  sa.ForeignKey("banks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("is_global", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("document_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_bases_bank", "knowledge_bases", ["bank_id"])
    op.create_index("ix_knowledge_bases_active", "knowledge_bases", ["is_active"])

    # Seed default knowledge bases
    op.execute("""
        INSERT INTO knowledge_bases (name, display_name, description, is_global, embedding_model, language)
        VALUES
        ('general_banking', 'General Banking', 'General banking regulations, products, FAQs', true,
         'sentence-transformers/paraphrase-multilingual-mpnet-base-v2', 'en'),
        ('loan_underwriting', 'Loan Underwriting', 'Loan policies, credit guidelines, RBI norms', true,
         'sentence-transformers/paraphrase-multilingual-mpnet-base-v2', 'en'),
        ('fraud_detection', 'Fraud Detection', 'Fraud patterns, AML rules, suspicious indicators', true,
         'sentence-transformers/paraphrase-multilingual-mpnet-base-v2', 'en'),
        ('kyc_compliance', 'KYC Compliance', 'KYC/AML/CFT policies, PMLA norms', true,
         'sentence-transformers/paraphrase-multilingual-mpnet-base-v2', 'en'),
        ('customer_documents', 'Customer Documents', 'User-uploaded private documents', false,
         'sentence-transformers/paraphrase-multilingual-mpnet-base-v2', 'en'),
        ('bank_policies', 'Bank Policies', 'Bank-specific internal policies', false,
         'sentence-transformers/paraphrase-multilingual-mpnet-base-v2', 'en'),
        ('regulatory', 'Regulatory', 'RBI circulars, SEBI regulations, PMLA, FEMA', true,
         'sentence-transformers/paraphrase-multilingual-mpnet-base-v2', 'en')
    """)

    # ── document_vectors ────────────────────────────────────
    op.create_table(
        "document_vectors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", UUID(as_uuid=True),
                  sa.ForeignKey("uploaded_documents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("chunk_id", sa.String(150), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("loan_application_id", UUID(as_uuid=True),
                  sa.ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("page_numbers", JSONB, nullable=True),
        sa.Column("knowledge_base", sa.String(100), nullable=False,
                  server_default="general_banking"),
        sa.Column("document_type", sa.String(100), nullable=True),
        sa.Column("bank_id", UUID(as_uuid=True), nullable=True),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dimension", sa.Integer, nullable=False),
        sa.Column("is_indexed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # Add pgvector column (768 dimensions for multilingual-mpnet-base-v2)
    op.execute("ALTER TABLE document_vectors ADD COLUMN embedding vector(768)")

    # Unique constraint
    op.create_index(
        "uq_vectors_chunk_model",
        "document_vectors",
        ["chunk_id", "embedding_model"],
        unique=True,
    )

    # Standard indexes
    op.create_index("ix_vectors_document_id", "document_vectors", ["document_id"])
    op.create_index("ix_vectors_user_id", "document_vectors", ["user_id"])
    op.create_index("ix_vectors_knowledge_base", "document_vectors", ["knowledge_base"])
    op.create_index("ix_vectors_doc_type", "document_vectors", ["document_type"])
    op.create_index("ix_vectors_bank_id", "document_vectors", ["bank_id"])
    op.create_index("ix_vectors_language", "document_vectors", ["language"])
    op.create_index("ix_vectors_user_kb", "document_vectors", ["user_id", "knowledge_base"])

    # IVFFlat vector index (build after data is loaded — CONCURRENTLY in prod)
    # NOTE: Requires at least 1 row with embedding to build index
    # Run separately after initial data load:
    # CREATE INDEX CONCURRENTLY ix_vectors_embedding_ivfflat
    #   ON document_vectors USING ivfflat (embedding vector_cosine_ops)
    #   WITH (lists = 100);


def downgrade() -> None:
    op.drop_table("document_vectors")
    op.drop_table("knowledge_bases")
    op.execute("DROP EXTENSION IF EXISTS vector")
