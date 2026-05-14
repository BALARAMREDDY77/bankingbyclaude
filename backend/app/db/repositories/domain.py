"""
Domain Repositories — Phase 3
================================
Repositories for: Document, Fraud, AIReport,
ChatSession, AgentTrace, Alert, SystemMetric.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.document import DocumentStatus, DocumentType, UploadedDocument
from app.db.models.fraud import FraudReport, FraudSeverity, FraudStatus
from app.db.models.ai_system import (
    AIReport, AgentTrace, AgentTraceStatus,
    Alert, AlertStatus, AlertType,
    ChatMessage, ChatSession, MessageRole,
    SystemMetric, MetricType,
)
from app.db.repositories.base import BaseRepository


# ──────────────────────────────────────────────
# Document Repository
# ──────────────────────────────────────────────

class DocumentRepository(BaseRepository[UploadedDocument]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(UploadedDocument, session)

    async def get_for_loan(
        self, loan_id: uuid.UUID, doc_type: Optional[DocumentType] = None
    ) -> List[UploadedDocument]:
        q = select(UploadedDocument).where(
            and_(
                UploadedDocument.loan_application_id == loan_id,
                UploadedDocument.deleted_at.is_(None),
            )
        )
        if doc_type:
            q = q.where(UploadedDocument.document_type == doc_type)
        result = await self.session.execute(q.order_by(UploadedDocument.created_at.desc()))
        return list(result.scalars().all())

    async def get_for_user(
        self, user_id: uuid.UUID, doc_type: Optional[DocumentType] = None
    ) -> List[UploadedDocument]:
        q = select(UploadedDocument).where(
            and_(
                UploadedDocument.user_id == user_id,
                UploadedDocument.deleted_at.is_(None),
            )
        )
        if doc_type:
            q = q.where(UploadedDocument.document_type == doc_type)
        result = await self.session.execute(q.order_by(UploadedDocument.created_at.desc()))
        return list(result.scalars().all())

    async def get_by_hash(self, file_hash: str) -> Optional[UploadedDocument]:
        result = await self.session.execute(
            select(UploadedDocument).where(UploadedDocument.file_hash == file_hash)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        doc_id: uuid.UUID,
        status: DocumentStatus,
        verified_by: Optional[uuid.UUID] = None,
        rejection_reason: Optional[str] = None,
    ) -> None:
        from datetime import timezone
        values: dict = {"status": status}
        if verified_by:
            values["verified_by_id"] = verified_by
            values["verified_at"] = datetime.now(timezone.utc).isoformat()
        if rejection_reason:
            values["rejection_reason"] = rejection_reason
        await self.session.execute(
            update(UploadedDocument).where(UploadedDocument.id == doc_id).values(**values)
        )
        await self.session.flush()

    async def get_pending_verification(self, limit: int = 50) -> List[UploadedDocument]:
        result = await self.session.execute(
            select(UploadedDocument)
            .where(
                and_(
                    UploadedDocument.status == DocumentStatus.UNDER_REVIEW,
                    UploadedDocument.deleted_at.is_(None),
                )
            )
            .order_by(UploadedDocument.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())


# ──────────────────────────────────────────────
# Fraud Repository
# ──────────────────────────────────────────────

class FraudRepository(BaseRepository[FraudReport]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(FraudReport, session)

    async def get_open(
        self, severity: Optional[FraudSeverity] = None, limit: int = 100
    ) -> List[FraudReport]:
        q = select(FraudReport).where(
            and_(
                FraudReport.status.in_([FraudStatus.OPEN, FraudStatus.UNDER_INVESTIGATION]),
                FraudReport.deleted_at.is_(None),
            )
        )
        if severity:
            q = q.where(FraudReport.severity == severity)
        result = await self.session.execute(
            q.order_by(FraudReport.severity.desc(), FraudReport.created_at).limit(limit)
        )
        return list(result.scalars().all())

    async def get_for_user(self, user_id: uuid.UUID) -> List[FraudReport]:
        result = await self.session.execute(
            select(FraudReport)
            .where(
                and_(
                    FraudReport.reported_user_id == user_id,
                    FraudReport.deleted_at.is_(None),
                )
            )
            .order_by(FraudReport.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_report_number(self, number: str) -> Optional[FraudReport]:
        result = await self.session.execute(
            select(FraudReport).where(FraudReport.report_number == number)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self, report_id: uuid.UUID, status: FraudStatus, notes: Optional[str] = None
    ) -> None:
        from datetime import timezone
        values: dict = {"status": status}
        if notes:
            values["investigation_notes"] = notes
        if status in (FraudStatus.RESOLVED, FraudStatus.DISMISSED, FraudStatus.REPORTED_TO_AUTHORITIES):
            values["resolved_at"] = datetime.now(timezone.utc).isoformat()
        await self.session.execute(
            update(FraudReport).where(FraudReport.id == report_id).values(**values)
        )
        await self.session.flush()

    async def generate_report_number(self) -> str:
        from datetime import timezone
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        result = await self.session.execute(
            select(func.count())
            .select_from(FraudReport)
            .where(FraudReport.report_number.like(f"FRD-{today}-%"))
        )
        seq = (result.scalar_one() or 0) + 1
        return f"FRD-{today}-{seq:04d}"


# ──────────────────────────────────────────────
# AI Report Repository
# ──────────────────────────────────────────────

class AIReportRepository(BaseRepository[AIReport]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AIReport, session)

    async def get_latest_for_loan(
        self, loan_id: uuid.UUID, report_type: Optional[str] = None
    ) -> Optional[AIReport]:
        q = select(AIReport).where(
            and_(AIReport.loan_application_id == loan_id, AIReport.deleted_at.is_(None))
        )
        if report_type:
            q = q.where(AIReport.report_type == report_type)
        result = await self.session.execute(
            q.order_by(AIReport.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_for_user(self, user_id: uuid.UUID, limit: int = 20) -> List[AIReport]:
        result = await self.session.execute(
            select(AIReport)
            .where(and_(AIReport.user_id == user_id, AIReport.deleted_at.is_(None)))
            .order_by(AIReport.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ──────────────────────────────────────────────
# Chat Repository
# ──────────────────────────────────────────────

class ChatRepository(BaseRepository[ChatSession]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ChatSession, session)

    async def get_active_session(self, user_id: uuid.UUID) -> Optional[ChatSession]:
        result = await self.session.execute(
            select(ChatSession)
            .where(and_(ChatSession.user_id == user_id, ChatSession.is_active.is_(True)))
            .order_by(ChatSession.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_with_messages(
        self, session_id: uuid.UUID, message_limit: int = 100
    ) -> Optional[ChatSession]:
        result = await self.session.execute(
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def add_message(
        self,
        session_id: uuid.UUID,
        role: MessageRole,
        content: str,
        tokens_used: Optional[int] = None,
        latency_ms: Optional[int] = None,
        tool_name: Optional[str] = None,
        tool_input: Optional[dict] = None,
        tool_output: Optional[dict] = None,
    ) -> ChatMessage:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
        )
        self.session.add(msg)
        await self.session.flush()

        # Update session totals
        await self.session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(
                total_messages=ChatSession.total_messages + 1,
                total_tokens=ChatSession.total_tokens + (tokens_used or 0),
            )
        )
        await self.session.flush()
        return msg

    async def get_user_sessions(
        self, user_id: uuid.UUID, limit: int = 20
    ) -> List[ChatSession]:
        result = await self.session.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ──────────────────────────────────────────────
# Agent Trace Repository
# ──────────────────────────────────────────────

class AgentTraceRepository(BaseRepository[AgentTrace]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AgentTrace, session)

    async def get_by_run_id(self, run_id: str) -> Optional[AgentTrace]:
        result = await self.session.execute(
            select(AgentTrace).where(AgentTrace.run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_running(self, agent_name: Optional[str] = None) -> List[AgentTrace]:
        q = select(AgentTrace).where(AgentTrace.status == AgentTraceStatus.RUNNING)
        if agent_name:
            q = q.where(AgentTrace.agent_name == agent_name)
        result = await self.session.execute(q.order_by(AgentTrace.created_at))
        return list(result.scalars().all())

    async def complete_trace(
        self,
        trace_id: uuid.UUID,
        status: AgentTraceStatus,
        output_data: Optional[dict] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        from datetime import timezone
        await self.session.execute(
            update(AgentTrace)
            .where(AgentTrace.id == trace_id)
            .values(
                status=status,
                output_data=output_data,
                error_message=error_message,
                duration_ms=duration_ms,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        await self.session.flush()


# ──────────────────────────────────────────────
# Alert Repository
# ──────────────────────────────────────────────

class AlertRepository(BaseRepository[Alert]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Alert, session)

    async def get_unread_for_user(self, user_id: uuid.UUID) -> List[Alert]:
        result = await self.session.execute(
            select(Alert)
            .where(
                and_(
                    Alert.user_id == user_id,
                    Alert.is_read.is_(False),
                    Alert.status != AlertStatus.DISMISSED,
                )
            )
            .order_by(Alert.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_open_critical(self, limit: int = 50) -> List[Alert]:
        from app.db.models.ai_system import AlertSeverity
        result = await self.session.execute(
            select(Alert)
            .where(
                and_(
                    Alert.severity == AlertSeverity.CRITICAL,
                    Alert.status == AlertStatus.OPEN,
                )
            )
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_read(self, alert_id: uuid.UUID) -> None:
        from datetime import timezone
        await self.session.execute(
            update(Alert)
            .where(Alert.id == alert_id)
            .values(is_read=True, read_at=datetime.now(timezone.utc).isoformat())
        )
        await self.session.flush()

    async def resolve_alert(
        self, alert_id: uuid.UUID, notes: Optional[str] = None
    ) -> None:
        from datetime import timezone
        await self.session.execute(
            update(Alert)
            .where(Alert.id == alert_id)
            .values(
                status=AlertStatus.RESOLVED,
                resolved_at=datetime.now(timezone.utc).isoformat(),
                resolution_notes=notes,
            )
        )
        await self.session.flush()

    async def unread_count_for_user(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Alert)
            .where(and_(Alert.user_id == user_id, Alert.is_read.is_(False)))
        )
        return result.scalar_one()


# ──────────────────────────────────────────────
# System Metrics Repository
# ──────────────────────────────────────────────

class MetricsRepository(BaseRepository[SystemMetric]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(SystemMetric, session)

    async def record(
        self,
        metric_type: MetricType,
        metric_name: str,
        value: Decimal,
        unit: Optional[str] = None,
        service: Optional[str] = None,
        endpoint: Optional[str] = None,
        tags: Optional[dict] = None,
    ) -> SystemMetric:
        metric = SystemMetric(
            metric_type=metric_type,
            metric_name=metric_name,
            value=value,
            unit=unit,
            service=service,
            endpoint=endpoint,
            tags=tags,
        )
        self.session.add(metric)
        await self.session.flush()
        return metric

    async def get_recent(
        self,
        metric_type: MetricType,
        service: Optional[str] = None,
        limit: int = 100,
    ) -> List[SystemMetric]:
        q = select(SystemMetric).where(SystemMetric.metric_type == metric_type)
        if service:
            q = q.where(SystemMetric.service == service)
        result = await self.session.execute(
            q.order_by(SystemMetric.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def average(
        self,
        metric_name: str,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
    ) -> Optional[Decimal]:
        q = select(func.avg(SystemMetric.value)).where(
            SystemMetric.metric_name == metric_name
        )
        if from_dt:
            q = q.where(SystemMetric.created_at >= from_dt)
        if to_dt:
            q = q.where(SystemMetric.created_at <= to_dt)
        result = await self.session.execute(q)
        return result.scalar_one_or_none()
