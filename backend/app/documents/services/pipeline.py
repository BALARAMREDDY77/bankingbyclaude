"""
Document Pipeline Orchestrator
================================
Coordinates the full ingestion pipeline:

  Upload → Validate → Store → OCR → Clean → Extract → Chunk → Save

Each stage is independently retryable and logged.
The pipeline updates the UploadedDocument DB record at each stage.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.document import DocumentStatus, DocumentType
from app.db.repositories.domain import DocumentRepository
from app.documents.services.chunker import ChunkingResult, ChunkStrategy, chunk_document
from app.documents.services.extractor import ExtractedMetadata, SupportedDocType, extract_metadata
from app.documents.services.ocr_service import OCRResult, OCRService
from app.documents.services.preprocessor import CleanedText, clean_text
from app.documents.utils.storage import StorageBackend, get_storage
from app.documents.utils.validators import FileValidator, ValidatedFile

logger = get_logger(__name__)

# Map DB DocumentType → extractor SupportedDocType
DOC_TYPE_MAP: dict[DocumentType, SupportedDocType] = {
    DocumentType.AADHAAR: SupportedDocType.AADHAAR,
    DocumentType.PAN_CARD: SupportedDocType.PAN_CARD,
    DocumentType.SALARY_SLIP: SupportedDocType.SALARY_SLIP,
    DocumentType.BANK_STATEMENT: SupportedDocType.BANK_STATEMENT,
    DocumentType.FORM_16: SupportedDocType.SALARY_SLIP,
    DocumentType.ITR: SupportedDocType.GENERIC,
}


@dataclass
class PipelineResult:
    document_id: uuid.UUID
    success: bool
    stage_completed: str          # Last successfully completed stage
    ocr_result: Optional[OCRResult] = None
    cleaned_text: Optional[CleanedText] = None
    extracted_metadata: Optional[ExtractedMetadata] = None
    chunking_result: Optional[ChunkingResult] = None
    storage_key: Optional[str] = None
    error: Optional[str] = None
    processing_time_ms: int = 0


class DocumentPipeline:
    """
    Orchestrates the full document ingestion pipeline.
    Injected per-request with DB session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DocumentRepository(session)
        self.ocr = OCRService()
        self.storage: StorageBackend = get_storage()
        self.validator = FileValidator()

    async def run(
        self,
        content: bytes,
        filename: str,
        document_type: DocumentType,
        user_id: uuid.UUID,
        document_id: uuid.UUID,
        loan_application_id: Optional[uuid.UUID] = None,
    ) -> PipelineResult:
        """
        Execute the full pipeline for one document.
        Updates DB record at each stage — safe to retry from any point.
        """
        import time
        start = time.perf_counter()

        logger.info(
            "pipeline.started",
            doc_id=str(document_id),
            doc_type=document_type,
            filename=filename,
            size=len(content),
        )

        result = PipelineResult(document_id=document_id, success=False, stage_completed="init")

        try:
            # ── Stage 1: Validate ────────────────────────
            await self._update_status(document_id, DocumentStatus.UNDER_REVIEW)
            validated: ValidatedFile = await self.validator.validate_bytes(content, filename)
            result.stage_completed = "validated"
            logger.info("pipeline.stage.validated", doc_id=str(document_id))

            # ── Stage 2: Store ───────────────────────────
            storage_key = self.storage.build_key(user_id, document_type.value, validated.safe_filename)
            await self.storage.save(content, storage_key)
            result.storage_key = storage_key
            result.stage_completed = "stored"
            logger.info("pipeline.stage.stored", doc_id=str(document_id), key=storage_key)

            # ── Stage 3: OCR ─────────────────────────────
            ocr_result = await self.ocr.extract(content, filename)
            result.ocr_result = ocr_result
            result.stage_completed = "ocr"
            logger.info(
                "pipeline.stage.ocr",
                doc_id=str(document_id),
                pages=ocr_result.total_pages,
                words=ocr_result.word_count,
                scanned=ocr_result.is_scanned,
            )

            # ── Stage 4: Clean ───────────────────────────
            cleaned = await clean_text(ocr_result.full_text)
            result.cleaned_text = cleaned
            result.stage_completed = "cleaned"
            logger.info(
                "pipeline.stage.cleaned",
                doc_id=str(document_id),
                language=cleaned.language,
                noise_removed=cleaned.noise_removed_percent,
            )

            # ── Stage 5: Extract Metadata ─────────────────
            supported_type = DOC_TYPE_MAP.get(document_type, SupportedDocType.GENERIC)
            extracted = await extract_metadata(cleaned.cleaned, supported_type)
            result.extracted_metadata = extracted
            result.stage_completed = "extracted"
            logger.info(
                "pipeline.stage.extracted",
                doc_id=str(document_id),
                confidence=extracted.confidence,
                fields=list(extracted.fields.keys()),
            )

            # ── Stage 6: Chunk ───────────────────────────
            page_texts = [p.text for p in ocr_result.pages]
            chunked = await chunk_document(
                text=cleaned.cleaned,
                document_id=str(document_id),
                page_texts=page_texts,
                strategy=ChunkStrategy.HYBRID,
            )
            result.chunking_result = chunked
            result.stage_completed = "chunked"
            logger.info(
                "pipeline.stage.chunked",
                doc_id=str(document_id),
                chunks=chunked.total_chunks,
                avg_size=round(chunked.avg_chunk_size),
            )

            # ── Stage 7: Persist Results ──────────────────
            await self._persist_results(document_id, result)
            result.stage_completed = "complete"
            result.success = True

            result.processing_time_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "pipeline.completed",
                doc_id=str(document_id),
                time_ms=result.processing_time_ms,
            )
            return result

        except Exception as exc:
            result.error = str(exc)
            result.processing_time_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "pipeline.failed",
                doc_id=str(document_id),
                stage=result.stage_completed,
                error=str(exc),
            )
            await self._update_status(document_id, DocumentStatus.REJECTED, str(exc))
            return result

    async def _update_status(
        self,
        document_id: uuid.UUID,
        status: DocumentStatus,
        rejection_reason: Optional[str] = None,
    ) -> None:
        from sqlalchemy import update
        from app.db.models.document import UploadedDocument
        values = {"status": status}
        if rejection_reason:
            values["rejection_reason"] = rejection_reason
        await self.session.execute(
            update(UploadedDocument)
            .where(UploadedDocument.id == document_id)
            .values(**values)
        )
        await self.session.flush()

    async def _persist_results(
        self, document_id: uuid.UUID, result: PipelineResult
    ) -> None:
        """Save OCR text, metadata, and chunk info to DB record."""
        from sqlalchemy import update
        from app.db.models.document import UploadedDocument

        ocr_data: dict = {}
        if result.ocr_result:
            ocr_data["ocr"] = {
                "method": result.ocr_result.method_used,
                "pages": result.ocr_result.total_pages,
                "words": result.ocr_result.word_count,
                "confidence": result.ocr_result.confidence_avg,
                "is_scanned": result.ocr_result.is_scanned,
                "language": result.ocr_result.language,
            }
        if result.extracted_metadata:
            ocr_data["extracted_fields"] = result.extracted_metadata.fields
            ocr_data["extraction_confidence"] = result.extracted_metadata.confidence
        if result.chunking_result:
            ocr_data["chunks"] = {
                "total": result.chunking_result.total_chunks,
                "avg_size": round(result.chunking_result.avg_chunk_size),
                "strategy": result.chunking_result.strategy,
            }

        await self.session.execute(
            update(UploadedDocument)
            .where(UploadedDocument.id == document_id)
            .values(
                status=DocumentStatus.VERIFIED,
                ocr_extracted_data=ocr_data,
                storage_key=result.storage_key or "",
                malware_scan_status="passed",
                malware_scanned_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        await self.session.flush()
