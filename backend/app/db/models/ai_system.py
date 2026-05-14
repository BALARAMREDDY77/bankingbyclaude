"""
AI & System Models
===================
Models for AI-generated reports, chat history, agent execution traces,
system alerts, and platform metrics.

These support Phase 4 (AI Agents) but the DB schema is defined here.
"""

import uuid
from decimal import Decimal
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    BigInteger, Boolean, Enum, ForeignKey,
    Index, Integer, Numeric, String, Text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, FullAuditMixin, TimestampMixin, UUIDPrimaryKeyMixin


# ──────────────────────────────────────────────
# AI Report
# ──────────────────────────────────────────────

class ReportType(str, PyEnum):
    CREDIT_ASSESSMENT = "credit_assessment"
    FRAUD_ANALYSIS = "fraud_analysis"
    DOCUMENT_VERIFICATION = "document_verification"
    RISK_SCORING = "risk_scoring"
    LOAN_RECOMMENDATION = "loan_recommendation"
    FINANCIAL_HEALTH = "financial_health"
    COMPLIANCE_CHECK = "compliance_check"
    MARKET_ANALYSIS = "market_analysis"


class ReportStatus(str, PyEnum):
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class AIReport(Base, FullAuditMixin):
    __tablename__ = "ai_reports"

    # Context
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    loan_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Classification
    report_type: Mapped[ReportType] = mapped_column(
        Enum(ReportType), nullable=False, index=True
    )
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus), nullable=False,
        default=ReportStatus.GENERATING, index=True
    )

    # AI metadata
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    agent_trace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # Report content
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    full_report: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    recommendations: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Scores
    overall_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Performance
    generation_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User")
    loan_application: Mapped[Optional["LoanApplication"]] = relationship(
        "LoanApplication", back_populates="ai_reports"
    )

    __table_args__ = (
        Index("ix_ai_reports_user_type", "user_id", "report_type"),
        Index("ix_ai_reports_status", "status"),
        Index("ix_ai_reports_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AIReport id={self.id} type={self.report_type} status={self.status}>"


# ──────────────────────────────────────────────
# Chat History
# ──────────────────────────────────────────────

class MessageRole(str, PyEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ChatSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    loan_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    agent_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    session_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ended_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan",
        order_by="ChatMessage.created_at"
    )
    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_chat_sessions_user", "user_id"),
        Index("ix_chat_sessions_created_at", "created_at"),
    )


class ChatMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_input: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tool_output: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    message_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")

    __table_args__ = (
        Index("ix_chat_messages_session", "session_id"),
        Index("ix_chat_messages_role", "role"),
        Index("ix_chat_messages_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} role={self.role} session={self.session_id}>"


# ──────────────────────────────────────────────
# Agent Trace
# ──────────────────────────────────────────────

class AgentTraceStatus(str, PyEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class AgentTrace(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Execution trace for AI agent runs.
    Records every step, tool call, and decision for observability and debugging.
    """
    __tablename__ = "agent_traces"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    loan_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Agent identity
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    agent_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    workflow_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    run_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)

    # Status
    status: Mapped[AgentTraceStatus] = mapped_column(
        Enum(AgentTraceStatus), nullable=False,
        default=AgentTraceStatus.RUNNING, index=True
    )

    # Execution details
    input_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    steps: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)   # Full step trace
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Performance
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    total_tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_agent_traces_agent_status", "agent_name", "status"),
        Index("ix_agent_traces_run_id", "run_id"),
        Index("ix_agent_traces_created_at", "created_at"),
        Index("ix_agent_traces_user", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<AgentTrace id={self.id} agent={self.agent_name} status={self.status}>"


# ──────────────────────────────────────────────
# Alert
# ──────────────────────────────────────────────

class AlertType(str, PyEnum):
    FRAUD_DETECTED = "fraud_detected"
    SUSPICIOUS_LOGIN = "suspicious_login"
    LARGE_TRANSACTION = "large_transaction"
    DOCUMENT_EXPIRED = "document_expired"
    LOAN_OVERDUE = "loan_overdue"
    CREDIT_SCORE_DROP = "credit_score_drop"
    ACCOUNT_LOCKED = "account_locked"
    COMPLIANCE_BREACH = "compliance_breach"
    SYSTEM_ERROR = "system_error"
    AI_ANOMALY = "ai_anomaly"
    RATE_LIMIT_BREACH = "rate_limit_breach"
    DATA_QUALITY = "data_quality"


class AlertSeverity(str, PyEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, PyEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"


class Alert(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "alerts"

    # Context
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    loan_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    assigned_to_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Classification
    alert_type: Mapped[AlertType] = mapped_column(
        Enum(AlertType), nullable=False, index=True
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity), nullable=False,
        default=AlertSeverity.WARNING, index=True
    )
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus), nullable=False,
        default=AlertStatus.OPEN, index=True
    )

    # Content
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Delivery
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    read_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sent_email: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_sms: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_push: Mapped[bool] = mapped_column(Boolean, default=False)

    # Resolution
    resolved_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    loan_application: Mapped[Optional["LoanApplication"]] = relationship(
        "LoanApplication", back_populates="alerts"
    )
    assigned_to: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[assigned_to_id]
    )

    __table_args__ = (
        Index("ix_alerts_user_status", "user_id", "status"),
        Index("ix_alerts_type_severity", "alert_type", "severity"),
        Index("ix_alerts_is_read", "is_read"),
        Index("ix_alerts_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Alert id={self.id} type={self.alert_type} severity={self.severity}>"


# ──────────────────────────────────────────────
# System Metrics
# ──────────────────────────────────────────────

class MetricType(str, PyEnum):
    API_LATENCY = "api_latency"
    DB_QUERY_TIME = "db_query_time"
    CACHE_HIT_RATE = "cache_hit_rate"
    ERROR_RATE = "error_rate"
    ACTIVE_USERS = "active_users"
    LOAN_APPLICATIONS_PER_HOUR = "loan_applications_per_hour"
    AI_INFERENCE_TIME = "ai_inference_time"
    FRAUD_DETECTION_RATE = "fraud_detection_rate"
    QUEUE_DEPTH = "queue_depth"
    MEMORY_USAGE = "memory_usage"
    CPU_USAGE = "cpu_usage"
    TOKEN_USAGE = "token_usage"


class SystemMetric(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Time-series style metrics storage.
    In production, prefer TimescaleDB extension or push to Prometheus.
    This table is a fallback / audit trail for critical metrics.
    """
    __tablename__ = "system_metrics"

    metric_type: Mapped[MetricType] = mapped_column(
        Enum(MetricType), nullable=False, index=True
    )
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    service: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    endpoint: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    host: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    period_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_metrics_type_created", "metric_type", "created_at"),
        Index("ix_metrics_service_created", "service", "created_at"),
        Index("ix_metrics_name_created", "metric_name", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SystemMetric type={self.metric_type} value={self.value} at={self.created_at}>"
