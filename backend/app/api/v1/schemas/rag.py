"""RAG API Pydantic Schemas."""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    knowledge_base: str = Field(default="general_banking")
    context_name: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    alpha: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rerank: Optional[bool] = None
    filters: Optional[Dict[str, Any]] = None
    loan_application_id: Optional[uuid.UUID] = None
    language: Optional[str] = Field(default=None, max_length=10)


class RetrievalResultItem(BaseModel):
    chunk_id: str
    document_id: str
    chunk_text: str
    hybrid_score: float
    semantic_score: Optional[float]
    bm25_score: Optional[float]
    rerank_score: Optional[float]
    document_type: Optional[str]
    page_numbers: Optional[list]
    rank: int
    retrieval_method: str


class RetrievalResponse(BaseModel):
    query: str
    knowledge_base: str
    results: List[RetrievalResultItem]
    context_window: str
    total_results: int
    reranked: bool
    latency_ms: int
    quality_label: str
    top_score: float


class IndexDocumentRequest(BaseModel):
    document_id: uuid.UUID
    knowledge_base: str = Field(default="customer_documents")
    document_type: Optional[str] = None
    bank_id: Optional[uuid.UUID] = None
    language: Optional[str] = None
    loan_application_id: Optional[uuid.UUID] = None


class IndexDocumentResponse(BaseModel):
    document_id: uuid.UUID
    vectors_stored: int
    knowledge_base: str
    status: str


class VectorStoreStatsResponse(BaseModel):
    total_vectors: int
    total_documents: int
    total_knowledge_bases: int
    avg_chunk_chars: float
    knowledge_base: Optional[str]


class KnowledgeBaseResponse(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    description: Optional[str]
    is_global: bool
    is_active: bool
    document_count: int
    chunk_count: int
    embedding_model: str
    language: str

    model_config = {"from_attributes": True}
