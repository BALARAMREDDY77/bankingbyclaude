"""
Document API Endpoints
=======================

POST   /documents/upload              — Upload a document (triggers async pipeline)
GET    /documents/                    — List user's documents
GET    /documents/{id}                — Get document details
GET    /documents/{id}/download       — Get presigned download URL
GET    /documents/{id}/ocr-result     — Get OCR & extraction results
DELETE /documents/{id}                — Soft-delete a document

Admin:
PATCH  /documents/{id}/status         — Update document verification status
GET    /documents/pending-review      — List documents pending verification
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.documents import (
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusUpdateRequest,
    DocumentUploadMetadata,
    DocumentUploadResponse,
    OCRResultResponse,
    PipelineStatusResponse,
    PresignedUrlResponse,
)
from app.api.v1.schemas.response import APIResponse
from app.auth.dependencies import CurrentUser
from app.auth.utils.rbac import RequireStaff, require_permission, Permission
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.db.models.document import DocumentStatus, DocumentType, UploadedDocument
from app.db.repositories.domain import DocumentRepository
from app.db.session import get_db
from app.documents.services.pipeline import DocumentPipeline
from app.documents.utils.storage import get_storage
from app.documents.utils.validators import FileValidator

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])

validator = FileValidator()


def _get_client_ip(request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    return forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else "unknown"
    )


# ──────────────────────────────────────────────
# Upload
# ──────────────────────────────────────────────

@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document for processing",
    response_model=APIResponse[DocumentUploadResponse],
)
async def upload_document(
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    loan_application_id: Optional[str] = Form(default=None),
    document_number: Optional[str] = Form(default=None),
    issued_by: Optional[str] = Form(default=None),
    issued_date: Optional[str] = Form(default=None),
    expiry_date: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentUploadResponse]:
    # Validate document type
    try:
        doc_type = DocumentType(document_type)
    except ValueError:
        raise BadRequestException(
            f"Invalid document type. Valid types: {[t.value for t in DocumentType]}"
        )

    # Validate loan_application_id if provided
    loan_id: Optional[uuid.UUID] = None
    if loan_application_id:
        try:
            loan_id = uuid.UUID(loan_application_id)
        except ValueError:
            raise BadRequestException("Invalid loan_application_id format.")

    # Validate file
    validated = await validator.validate(file)

    # Create DB record
    storage = get_storage()
    storage_key = storage.build_key(current_user.id, doc_type.value, validated.safe_filename)

    repo = DocumentRepository(db)
    doc = await repo.create({
        "user_id": current_user.id,
        "loan_application_id": loan_id,
        "document_type": doc_type,
        "status": DocumentStatus.UPLOADED,
        "original_filename": validated.original_filename,
        "safe_filename": validated.safe_filename,
        "file_size_bytes": validated.size_bytes,
        "mime_type": validated.content_type,
        "file_hash": validated.file_hash,
        "storage_key": storage_key,
        "storage_bucket": "",
        "document_number": document_number,
        "issued_by": issued_by,
        "issued_date": issued_date,
        "expiry_date": expiry_date,
        "created_by": current_user.id,
    })

    logger.info(
        "document.uploaded",
        doc_id=str(doc.id),
        user_id=str(current_user.id),
        type=doc_type.value,
        size=validated.size_bytes,
    )

    # Run pipeline as background task
    content = validated.content

    async def run_pipeline():
        from app.db.session import AsyncSessionFactory
        async with AsyncSessionFactory() as bg_session:
            pipeline = DocumentPipeline(bg_session)
            await pipeline.run(
                content=content,
                filename=validated.safe_filename,
                document_type=doc_type,
                user_id=current_user.id,
                document_id=doc.id,
                loan_application_id=loan_id,
            )
            await bg_session.commit()

    background_tasks.add_task(run_pipeline)

    return APIResponse.ok(
        data=DocumentUploadResponse(
            document_id=doc.id,
            status="processing",
            message="Document uploaded. Processing started in background.",
            filename=validated.safe_filename,
            file_size_bytes=validated.size_bytes,
        ),
        message="Document accepted for processing.",
    )


# ──────────────────────────────────────────────
# List
# ──────────────────────────────────────────────

@router.get(
    "/",
    summary="List current user's documents",
    response_model=APIResponse[DocumentListResponse],
)
async def list_documents(
    current_user: CurrentUser,
    document_type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentListResponse]:
    doc_type = None
    if document_type:
        try:
            doc_type = DocumentType(document_type)
        except ValueError:
            raise BadRequestException(f"Invalid document_type: {document_type}")

    repo = DocumentRepository(db)
    docs = await repo.get_for_user(current_user.id, doc_type=doc_type)

    return APIResponse.ok(
        data=DocumentListResponse(
            documents=[DocumentResponse.model_validate(d) for d in docs],
            total=len(docs),
        )
    )


# ──────────────────────────────────────────────
# Get by ID
# ──────────────────────────────────────────────

@router.get(
    "/{document_id}",
    summary="Get document details",
    response_model=APIResponse[DocumentResponse],
)
async def get_document(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    repo = DocumentRepository(db)
    doc = await repo.get_by_id(document_id)
    if not doc or doc.deleted_at:
        raise NotFoundException("Document not found.")
    if doc.user_id != current_user.id and current_user.role.value not in ("admin", "employee"):
        raise ForbiddenException("You do not have access to this document.")

    return APIResponse.ok(data=DocumentResponse.model_validate(doc))


# ──────────────────────────────────────────────
# Download (presigned URL)
# ──────────────────────────────────────────────

@router.get(
    "/{document_id}/download",
    summary="Get a presigned download URL",
    response_model=APIResponse[PresignedUrlResponse],
)
async def get_download_url(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    expires_in: int = Query(default=3600, ge=60, le=86400),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[PresignedUrlResponse]:
    repo = DocumentRepository(db)
    doc = await repo.get_by_id(document_id)
    if not doc or doc.deleted_at:
        raise NotFoundException("Document not found.")
    if doc.user_id != current_user.id and current_user.role.value not in ("admin", "employee"):
        raise ForbiddenException("Access denied.")

    storage = get_storage()
    url = await storage.get_presigned_url(doc.storage_key, expires_in=expires_in)

    return APIResponse.ok(
        data=PresignedUrlResponse(
            document_id=document_id,
            url=url,
            expires_in_seconds=expires_in,
        )
    )


# ──────────────────────────────────────────────
# OCR Result
# ──────────────────────────────────────────────

@router.get(
    "/{document_id}/ocr-result",
    summary="Get OCR extraction results for a document",
    response_model=APIResponse[OCRResultResponse],
)
async def get_ocr_result(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[OCRResultResponse]:
    repo = DocumentRepository(db)
    doc = await repo.get_by_id(document_id)
    if not doc or doc.deleted_at:
        raise NotFoundException("Document not found.")
    if doc.user_id != current_user.id and current_user.role.value not in ("admin", "employee", "fraud_reviewer"):
        raise ForbiddenException("Access denied.")
    if not doc.ocr_extracted_data:
        raise NotFoundException("OCR results not available yet. Processing may still be in progress.")

    data = doc.ocr_extracted_data
    ocr = data.get("ocr", {})

    return APIResponse.ok(
        data=OCRResultResponse(
            document_id=document_id,
            ocr_method=ocr.get("method", "unknown"),
            is_scanned=ocr.get("is_scanned", False),
            total_pages=ocr.get("pages", 0),
            word_count=ocr.get("words", 0),
            confidence=ocr.get("confidence", 0.0),
            language=ocr.get("language"),
            extracted_fields=data.get("extracted_fields"),
            extraction_confidence=data.get("extraction_confidence"),
            chunks_created=data.get("chunks", {}).get("total"),
        )
    )


# ──────────────────────────────────────────────
# Delete
# ──────────────────────────────────────────────

@router.delete(
    "/{document_id}",
    summary="Soft-delete a document",
    response_model=APIResponse[dict],
)
async def delete_document(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    repo = DocumentRepository(db)
    doc = await repo.get_by_id(document_id)
    if not doc or doc.deleted_at:
        raise NotFoundException("Document not found.")
    if doc.user_id != current_user.id and current_user.role.value != "admin":
        raise ForbiddenException("You can only delete your own documents.")

    doc.soft_delete(deleted_by=current_user.id)
    db.add(doc)

    logger.info("document.deleted", doc_id=str(document_id), by=str(current_user.id))
    return APIResponse.ok(data={"deleted": True, "document_id": str(document_id)})


# ──────────────────────────────────────────────
# Admin: Update Status
# ──────────────────────────────────────────────

@router.patch(
    "/{document_id}/status",
    summary="Update document verification status (staff only)",
    response_model=APIResponse[DocumentResponse],
)
async def update_document_status(
    document_id: uuid.UUID,
    body: DocumentStatusUpdateRequest,
    current_user: CurrentUser = Depends(RequireStaff),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    try:
        new_status = DocumentStatus(body.status)
    except ValueError:
        raise BadRequestException(f"Invalid status: {body.status}")

    repo = DocumentRepository(db)
    await repo.update_status(
        doc_id=document_id,
        status=new_status,
        verified_by=current_user.id,
        rejection_reason=body.rejection_reason,
    )
    doc = await repo.get_by_id(document_id)
    if not doc:
        raise NotFoundException("Document not found.")

    return APIResponse.ok(data=DocumentResponse.model_validate(doc))


# ──────────────────────────────────────────────
# Admin: Pending Review Queue
# ──────────────────────────────────────────────

@router.get(
    "/admin/pending-review",
    summary="List documents pending manual verification (staff only)",
    response_model=APIResponse[DocumentListResponse],
)
async def get_pending_review(
    current_user: CurrentUser = Depends(RequireStaff),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentListResponse]:
    repo = DocumentRepository(db)
    docs = await repo.get_pending_verification(limit=limit)
    return APIResponse.ok(
        data=DocumentListResponse(
            documents=[DocumentResponse.model_validate(d) for d in docs],
            total=len(docs),
        )
    )
