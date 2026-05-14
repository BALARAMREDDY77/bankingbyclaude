"""
Document API Schemas
=====================
Request/Response Pydantic models for document upload and management endpoints.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Request Schemas ──────────────────────────────────────────

class DocumentUploadMetadata(BaseModel):
    """Metadata sent alongside file upload (as form field)."""
    document_type: str = Field(..., description="DocumentType enum value")
    loan_application_id: Optional[uuid.UUID] = None
    description: Optional[str] = Field(default=None, max_length=500)
    document_number: Optional[str] = Field(default=None, max_length=100)
    issued_by: Optional[str] = Field(default=None, max_length=255)
    issued_date: Optional[str] = Field(default=None, description="DD/MM/YYYY")
    expiry_date: Optional[str] = Field(default=None, description="DD/MM/YYYY")


class DocumentStatusUpdateRequest(BaseModel):
    status: str
    rejection_reason: Optional[str] = Field(default=None, max_length=1000)


# ── Response Schemas ─────────────────────────────────────────

class DocumentResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    loan_application_id: Optional[uuid.UUID]
    document_type: str
    status: str
    version: int
    original_filename: str
    safe_filename: str
    file_size_bytes: int
    mime_type: str
    file_hash: str
    document_number: Optional[str]
    issued_by: Optional[str]
    issued_date: Optional[str]
    expiry_date: Optional[str]
    is_expired: bool
    ocr_extracted_data: Optional[Dict[str, Any]]
    malware_scan_status: Optional[str]
    rejection_reason: Optional[str]
    verified_at: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    message: str
    filename: str
    file_size_bytes: int
    task_id: Optional[str] = None       # Celery task ID for async tracking


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int


class PresignedUrlResponse(BaseModel):
    document_id: uuid.UUID
    url: str
    expires_in_seconds: int


class OCRResultResponse(BaseModel):
    document_id: uuid.UUID
    ocr_method: str
    is_scanned: bool
    total_pages: int
    word_count: int
    confidence: float
    language: Optional[str]
    extracted_fields: Optional[Dict[str, Any]]
    extraction_confidence: Optional[float]
    chunks_created: Optional[int]


class PipelineStatusResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    stage_completed: Optional[str]
    task_id: Optional[str]
    error: Optional[str]
