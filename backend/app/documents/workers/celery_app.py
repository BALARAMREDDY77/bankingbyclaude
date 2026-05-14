"""
Celery Application
===================
Background task queue for async document processing.
Uses Redis as both broker and result backend.

Start worker:
    celery -A app.documents.workers.celery_app worker --loglevel=info -Q documents
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "banking_documents",
    broker=settings.documents.celery_broker_url,
    backend=settings.documents.celery_result_backend,
    include=["app.documents.workers.tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task routing — dedicated document queue
    task_routes={
        "app.documents.workers.tasks.*": {"queue": "documents"},
    },

    # Retry config
    task_acks_late=True,                    # Ack after completion (safer)
    task_reject_on_worker_lost=True,        # Re-queue if worker dies
    worker_prefetch_multiplier=1,           # One task at a time per worker

    # Result expiry
    result_expires=86400,                   # 24 hours

    # Rate limiting
    task_annotations={
        "app.documents.workers.tasks.process_document": {
            "rate_limit": "30/m",           # 30 docs/min per worker
        }
    },

    # Beat schedule (periodic tasks)
    beat_schedule={
        "cleanup-expired-documents": {
            "task": "app.documents.workers.tasks.cleanup_expired_documents",
            "schedule": 3600.0,             # Every hour
        },
        "retry-failed-documents": {
            "task": "app.documents.workers.tasks.retry_failed_documents",
            "schedule": 300.0,              # Every 5 minutes
        },
    },
)
