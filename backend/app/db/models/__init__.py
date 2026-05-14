"""
Domain Models Package
======================
All models imported here so Alembic autogenerate detects every table.
Import order respects FK dependencies.
"""

# Base (must be first)
from app.db.models.base import Base, FullAuditMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

# Phase 2 — Auth models
from app.db.models.user import AuditEventType, AuditLog, RefreshToken, User, UserRole, UserStatus

# Phase 3 — Domain models
from app.db.models.bank import Bank, BankStatus, BankTier
from app.db.models.loan import EmploymentType, LoanApplication, LoanPurpose, LoanStatus, LoanType
from app.db.models.transaction import Transaction, TransactionChannel, TransactionStatus, TransactionType
from app.db.models.document import DocumentStatus, DocumentType, UploadedDocument
from app.db.models.fraud import FraudReport, FraudSeverity, FraudStatus, FraudType, FraudSource
from app.db.models.ai_system import (
    AIReport, AgentTrace, AgentTraceStatus,
    Alert, AlertSeverity, AlertStatus, AlertType,
    ChatMessage, ChatSession, MessageRole,
    ReportStatus, ReportType,
    SystemMetric, MetricType,
)

__all__ = [
    "Base", "FullAuditMixin", "SoftDeleteMixin", "TimestampMixin", "UUIDPrimaryKeyMixin",
    "User", "UserRole", "UserStatus", "RefreshToken", "AuditLog", "AuditEventType",
    "Bank", "BankStatus", "BankTier",
    "LoanApplication", "LoanType", "LoanStatus", "LoanPurpose", "EmploymentType",
    "Transaction", "TransactionType", "TransactionStatus", "TransactionChannel",
    "UploadedDocument", "DocumentType", "DocumentStatus",
    "FraudReport", "FraudType", "FraudSeverity", "FraudStatus", "FraudSource",
    "AIReport", "ReportType", "ReportStatus",
    "ChatSession", "ChatMessage", "MessageRole",
    "AgentTrace", "AgentTraceStatus",
    "Alert", "AlertType", "AlertSeverity", "AlertStatus",
    "SystemMetric", "MetricType",
]
