"""
RAG API Endpoints
==================

POST /rag/retrieve              — Hybrid retrieval query
POST /rag/index/{document_id}   — Index document chunks into vector store
GET  /rag/stats                 — Vector store statistics
GET  /rag/knowledge-bases       — List knowledge bases
DELETE /rag/vectors/{doc_id}    — Remove document vectors
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.rag import (
    IndexDocumentRequest,
    IndexDocumentResponse,
    KnowledgeBaseResponse,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalResultItem,
    VectorStoreStatsResponse,
)
from app.api.v1.schemas.response import APIResponse
from app.auth.dependencies import CurrentUser
from app.auth.utils.rbac import RequireStaff
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.logging import get_logger
from app.db.repositories.domain import DocumentRepository
from app.db.session import get_db
from app.rag.services.embedding_pipeline import EmbeddingPipeline
from app.rag.services.hybrid_retrieval import HybridRetrievalService
from app.rag.services.vector_store import VectorStoreService
from app.rag.utils.contexts import KnowledgeBaseType, build_filters, get_context
from app.rag.utils.observability import (
    format_context_window,
    record_retrieval_metric,
    score_retrieval,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG"])


# ──────────────────────────────────────────────
# Retrieve
# ──────────────────────────────────────────────

@router.post(
    "/retrieve",
    summary="Hybrid RAG retrieval — semantic + BM25 + reranking",
    response_model=APIResponse[RetrievalResponse],
)
async def retrieve(
    body: RetrievalRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[RetrievalResponse]:
    # Resolve context
    ctx_name = body.context_name or body.knowledge_base
    ctx = get_context(ctx_name)

    # Build filters (enforce user-scoping for private KBs)
    filters = build_filters(
        context=ctx,
        user_id=str(current_user.id),
        bank_id=str(body.filters.get("bank_id", "")) if body.filters else None,
        language=body.language,
        loan_application_id=str(body.loan_application_id) if body.loan_application_id else None,
    )
    if body.filters:
        filters.update(body.filters)

    svc = HybridRetrievalService(db)

    # Search across all KBs in context
    all_results = []
    for kb in ctx.knowledge_bases:
        results, obs = await svc.retrieve(
            query=body.query,
            knowledge_base=kb,
            top_k=body.top_k or ctx.default_top_k,
            alpha=body.alpha or ctx.alpha,
            filters=filters,
            rerank=body.rerank if body.rerank is not None else ctx.rerank,
        )
        all_results.extend(results)

    # Sort merged results and take top-k
    all_results.sort(key=lambda r: r.hybrid_score, reverse=True)
    final = all_results[:body.top_k or ctx.default_top_k]

    # Score quality
    quality = score_retrieval(final, obs)
    await record_retrieval_metric(obs, quality, db)

    # Format context window
    context_window = format_context_window(final, max_chars=ctx.max_context_chars)

    logger.info(
        "rag.retrieve",
        user_id=str(current_user.id),
        kb=body.knowledge_base,
        results=len(final),
        quality=quality.quality_label,
    )

    return APIResponse.ok(
        data=RetrievalResponse(
            query=body.query,
            knowledge_base=body.knowledge_base,
            results=[
                RetrievalResultItem(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    chunk_text=r.chunk_text,
                    hybrid_score=r.hybrid_score,
                    semantic_score=r.semantic_score,
                    bm25_score=r.bm25_score,
                    rerank_score=r.rerank_score,
                    document_type=r.document_type,
                    page_numbers=r.page_numbers,
                    rank=r.rank,
                    retrieval_method=r.retrieval_method,
                )
                for r in final
            ],
            context_window=context_window,
            total_results=len(final),
            reranked=obs.reranked,
            latency_ms=obs.latency_ms,
            quality_label=quality.quality_label,
            top_score=quality.top_score,
        )
    )


# ──────────────────────────────────────────────
# Index Document
# ──────────────────────────────────────────────

@router.post(
    "/index/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Index a document's chunks into the vector store",
    response_model=APIResponse[IndexDocumentResponse],
)
async def index_document(
    document_id: uuid.UUID,
    body: IndexDocumentRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[IndexDocumentResponse]:
    # Verify document ownership
    doc_repo = DocumentRepository(db)
    doc = await doc_repo.get_by_id(document_id)
    if not doc or doc.deleted_at:
        raise NotFoundException("Document not found.")
    if doc.user_id != current_user.id and current_user.role.value not in ("admin", "employee"):
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("Access denied.")

    if not doc.ocr_extracted_data:
        raise BadRequestException("Document has not been processed by OCR yet.")

    # Rebuild chunks from DB (stored during Phase 4 pipeline)
    from sqlalchemy import text
    result = await db.execute(
        text("SELECT * FROM document_chunks WHERE document_id = :doc_id ORDER BY chunk_index"),
        {"doc_id": str(document_id)}
    )
    rows = result.fetchall()

    if not rows:
        raise BadRequestException("No chunks found. Run the document pipeline first.")

    from app.documents.services.chunker import DocumentChunk, ChunkingResult, ChunkStrategy
    chunks = [
        DocumentChunk(
            chunk_id=row.id,
            document_id=str(document_id),
            chunk_index=row.chunk_index,
            text=row.text,
            char_start=row.char_start,
            char_end=row.char_end,
            page_numbers=row.page_numbers or [],
            word_count=row.word_count,
            char_count=row.char_count,
            strategy=ChunkStrategy(row.strategy),
        )
        for row in rows
    ]

    chunking_result = ChunkingResult(
        document_id=str(document_id),
        total_chunks=len(chunks),
        chunks=chunks,
        strategy=ChunkStrategy.HYBRID,
        total_chars=sum(c.char_count for c in chunks),
        avg_chunk_size=sum(c.char_count for c in chunks) / max(len(chunks), 1),
        overlap_chars=200,
    )

    pipeline = EmbeddingPipeline(db)
    stored = await pipeline.index_document(
        chunking_result=chunking_result,
        document_id=document_id,
        user_id=current_user.id,
        knowledge_base=body.knowledge_base,
        document_type=body.document_type or doc.document_type.value,
        bank_id=body.bank_id,
        language=body.language,
        loan_application_id=body.loan_application_id,
    )

    return APIResponse.ok(
        data=IndexDocumentResponse(
            document_id=document_id,
            vectors_stored=stored,
            knowledge_base=body.knowledge_base,
            status="indexed",
        ),
        message=f"Successfully indexed {stored} chunks into '{body.knowledge_base}'.",
    )


# ──────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────

@router.get(
    "/stats",
    summary="Vector store statistics",
    response_model=APIResponse[VectorStoreStatsResponse],
)
async def get_stats(
    knowledge_base: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(RequireStaff),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VectorStoreStatsResponse]:
    vs = VectorStoreService(db)
    stats = await vs.get_stats(knowledge_base)
    return APIResponse.ok(
        data=VectorStoreStatsResponse(
            **stats, knowledge_base=knowledge_base
        )
    )


# ──────────────────────────────────────────────
# Knowledge Bases
# ──────────────────────────────────────────────

@router.get(
    "/knowledge-bases",
    summary="List all knowledge bases",
    response_model=APIResponse[list],
)
async def list_knowledge_bases(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list]:
    from sqlalchemy import select, text
    from app.db.models.vector_store import KnowledgeBase
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.is_active.is_(True))
        .order_by(KnowledgeBase.name)
    )
    kbs = result.scalars().all()
    return APIResponse.ok(
        data=[KnowledgeBaseResponse.model_validate(kb) for kb in kbs]
    )


# ──────────────────────────────────────────────
# Delete Vectors
# ──────────────────────────────────────────────

@router.delete(
    "/vectors/{document_id}",
    summary="Remove all vectors for a document",
    response_model=APIResponse[dict],
)
async def delete_vectors(
    document_id: uuid.UUID,
    knowledge_base: str = Query(...),
    current_user: CurrentUser = Depends(RequireStaff),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    pipeline = EmbeddingPipeline(db)
    deleted = await pipeline.delete_document(document_id, knowledge_base)
    return APIResponse.ok(
        data={"deleted_vectors": deleted, "document_id": str(document_id)}
    )
