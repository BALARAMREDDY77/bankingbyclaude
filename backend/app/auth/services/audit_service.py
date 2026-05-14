"""
Audit Logging Service
======================
Dedicated service for writing immutable audit trail entries.
Used across the platform — not just auth.

All writes are fire-and-forget where possible (background tasks),
with fallback to synchronous writes for critical security events.
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.user import AuditEventType, AuditLog
from app.db.repositories.user import AuditLogRepository

logger = get_logger(__name__)


class AuditService:
    """
    Records security and operational events to the audit_logs table.
    Every entry is immutable — no updates or deletes ever.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.repo = AuditLogRepository(session)

    async def record(
        self,
        event_type: AuditEventType,
        description: str,
        *,
        user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        severity: str = "info",
    ) -> AuditLog:
        """Write an audit log entry. Raises on failure (critical path)."""
        entry = await self.repo.log(
            event_type=event_type,
            description=description,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
            severity=severity,
        )
        # Mirror to structured logger for log aggregation pipelines
        log_fn = logger.warning if severity in ("warning", "critical") else logger.info
        log_fn(
            f"audit.{event_type.value}",
            audit_id=str(entry.id),
            user_id=str(user_id) if user_id else None,
            ip=ip_address,
            severity=severity,
        )
        return entry

    @classmethod
    def extract_request_meta(cls, request: Request) -> Dict[str, str]:
        """Extract IP and User-Agent from a FastAPI request."""
        # Handle proxy forwarding (X-Forwarded-For)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"

        user_agent = request.headers.get("User-Agent", "")
        return {"ip_address": ip, "user_agent": user_agent}
