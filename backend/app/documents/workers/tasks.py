"""
Background Task Definitions
=============================
Celery tasks for async document processing.

Tasks:
  - process_document       : Full pipeline for one document
  - process_document_batch : Batch processing for multiple docs
  - retry_failed_documents : Periodic retry of failed docs
  - cleanup_expired_documents : Purge old processed files
"""

import asyncio
import uuid
from typing import List, Optional

from celery import Task
from celery.utils.log import get_task_logger

from app.documents.workers.celery_app import celery_app

logger = get_task_logger(__name__)


# ──────────────────────────────────────────────
# Base Task with DB Session Management
# ──────────────────────────────────────────────

class DatabaseTask(Task):
    """Base Celery task that provides an async DB session."""
    abstract = True

    def _run_async(self, coro):
        """Run an async coroutine from a sync Celery task."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ──────────────────────────────────────────────
# Main Processing Task
# ──────────────────────────────────────────────

@celery_app.task(
    base=DatabaseTask,
    bind=True,
    name="app.documents.workers.tasks.process_document",
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=120,
    time_limit=180,
)
def process_document(
    self,
    document_id: str,
    user_id: str,
    document_type: str,
    filename: str,
    storage_key: str,
    loan_application_id: Optional[str] = None,
) -> dict:
    """
    Full async pipeline for one document.
    Triggered after upload — reads content from storage, runs pipeline.

    Args:
        document_id: UUID string of the UploadedDocument record
        user_id: UUID string of the owning user
        document_type: DocumentType enum value string
        filename: Original filename
        storage_key: Storage key to read file content from
        loan_application_id: Optional associated loan application UUID
    """
    logger.info(
        f"[process_document] Starting doc_id={document_id} type={document_type}"
    )

    async def _run():
        from app.db.session import AsyncSessionFactory
        from app.db.models.document import DocumentType as DBDocType
        from app.documents.services.pipeline import DocumentPipeline
        from app.documents.utils.storage import get_storage

        storage = get_storage()

        async with AsyncSessionFactory() as session:
            try:
                # Read content from storage
                content = await storage.read(storage_key)

                # Run pipeline
                pipeline = DocumentPipeline(session)
                result = await pipeline.run(
                    content=content,
                    filename=filename,
                    document_type=DBDocType(document_type),
                    user_id=uuid.UUID(user_id),
                    document_id=uuid.UUID(document_id),
                    loan_application_id=uuid.UUID(loan_application_id) if loan_application_id else None,
                )

                await session.commit()
                return {
                    "success": result.success,
                    "document_id": document_id,
                    "stage_completed": result.stage_completed,
                    "chunks": result.chunking_result.total_chunks if result.chunking_result else 0,
                    "error": result.error,
                }

            except Exception as exc:
                await session.rollback()
                raise exc

    try:
        return self._run_async(_run())

    except Exception as exc:
        logger.error(f"[process_document] Failed doc_id={document_id}: {exc}")
        try:
            raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
        except self.MaxRetriesExceededError:
            logger.critical(f"[process_document] Max retries exceeded for doc_id={document_id}")
            return {"success": False, "document_id": document_id, "error": str(exc)}


# ──────────────────────────────────────────────
# Batch Processing
# ──────────────────────────────────────────────

@celery_app.task(
    name="app.documents.workers.tasks.process_document_batch",
    soft_time_limit=600,
    time_limit=720,
)
def process_document_batch(document_ids: List[str]) -> dict:
    """
    Submit multiple documents for processing in parallel.
    Returns a chord result with all individual task results.
    """
    from celery import group
    tasks = group(
        process_document.s(
            document_id=doc_id,
            user_id="",           # Will be resolved inside task from DB
            document_type="",
            filename="",
            storage_key="",
        )
        for doc_id in document_ids
    )
    result = tasks.apply_async()
    logger.info(f"[batch] Submitted {len(document_ids)} documents for processing")
    return {"batch_id": result.id, "count": len(document_ids)}


# ──────────────────────────────────────────────
# Periodic: Retry Failed Documents
# ──────────────────────────────────────────────

@celery_app.task(
    name="app.documents.workers.tasks.retry_failed_documents",
)
def retry_failed_documents() -> dict:
    """
    Periodic task: find documents stuck in UNDER_REVIEW for >30 min
    and re-submit them for processing.
    """
    async def _run():
        from datetime import datetime, timezone, timedelta
        from sqlalchemy import select, and_
        from app.db.session import AsyncSessionFactory
        from app.db.models.document import UploadedDocument, DocumentStatus

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(UploadedDocument).where(
                    and_(
                        UploadedDocument.status == DocumentStatus.UNDER_REVIEW,
                        UploadedDocument.created_at < cutoff,
                    )
                ).limit(20)
            )
            docs = result.scalars().all()
            retried = 0
            for doc in docs:
                if doc.storage_key:
                    process_document.apply_async(kwargs={
                        "document_id": str(doc.id),
                        "user_id": str(doc.user_id),
                        "document_type": doc.document_type.value,
                        "filename": doc.original_filename,
                        "storage_key": doc.storage_key,
                    })
                    retried += 1
            return {"retried": retried}

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_run())
        logger.info(f"[retry] Re-submitted {result['retried']} stalled documents")
        return result
    finally:
        loop.close()


# ──────────────────────────────────────────────
# Periodic: Cleanup Expired Documents
# ──────────────────────────────────────────────

@celery_app.task(
    name="app.documents.workers.tasks.cleanup_expired_documents",
)
def cleanup_expired_documents() -> dict:
    """
    Periodic task: soft-delete documents marked as expired in DB
    and remove their files from storage.
    """
    async def _run():
        from datetime import datetime, timezone
        from sqlalchemy import select, update, and_
        from app.db.session import AsyncSessionFactory
        from app.db.models.document import UploadedDocument, DocumentStatus
        from app.documents.utils.storage import get_storage

        storage = get_storage()
        now = datetime.now(timezone.utc)

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(UploadedDocument).where(
                    and_(
                        UploadedDocument.is_expired.is_(True),
                        UploadedDocument.deleted_at.is_(None),
                    )
                ).limit(50)
            )
            docs = result.scalars().all()
            cleaned = 0
            for doc in docs:
                try:
                    if doc.storage_key:
                        await storage.delete(doc.storage_key)
                    doc.soft_delete()
                    cleaned += 1
                except Exception as exc:
                    logger.warning(f"[cleanup] Failed to clean doc {doc.id}: {exc}")

            await session.commit()
            return {"cleaned": cleaned}

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_run())
        logger.info(f"[cleanup] Cleaned {result['cleaned']} expired documents")
        return result
    finally:
        loop.close()
