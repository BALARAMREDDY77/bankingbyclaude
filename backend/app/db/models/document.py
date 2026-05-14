"""
Uploaded Document Model
========================
Tracks documents uploaded by users for loan applications and KYC.
Supports versioning, verification status, and secure storage references.
"""

import uuid
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Enum, ForeignKey,
    Index, Integer, String, Text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, FullAuditMixin


class DocumentType(str, PyEnum):
    # Identity
    AADHAAR = "aadhaar"
    PAN_CARD = "pan_card"
    PASSPORT = "passport"
    VOTER_ID = "voter_id"
    DRIVING_LICENSE = "driving_license"

    # Financial
    BANK_STATEMENT = "bank_statement"
    SALARY_SLIP = "salary_slip"
    ITR = "itr"                         # Income Tax Return
    FORM_16 = "form_16"
    BALANCE_SHEET = "balance_sheet"
    PROFIT_LOSS = "profit_loss"
    GST_RETURN = "gst_return"

    # Property
    PROPERTY_DEED = "property_deed"
    SALE_AGREEMENT = "sale_agreement"
    NOC = "noc"
    ENCUMBRANCE_CERTIFICATE = "encumbrance_certificate"

    # Business
    INCORPORATION_CERTIFICATE = "incorporation_certificate"
    MOA = "moa"                        # Memorandum of Association
    BUSINESS_LICENSE = "business_license"
    UDYAM_CERTIFICATE = "udyam_certificate"

    # Other
    PHOTOGRAPH = "photograph"
    SIGNATURE = "signature"
    OTHER = "other"


class DocumentStatus(str, PyEnum):
    UPLOADED = "uploaded"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"
    RESUBMISSION_REQUIRED = "resubmission_required"


class UploadedDocument(Base, FullAuditMixin):
    __tablename__ = "uploaded_documents"

    # Ownership
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    loan_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verified_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Classification
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType), nullable=False, index=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), nullable=False,
        default=DocumentStatus.UPLOADED, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # File details
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256

    # Storage (S3 / GCS / Azure path — never store raw file in DB)
    storage_bucket: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    storage_region: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Document metadata
    document_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    issued_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    issued_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    expiry_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_expired: Mapped[bool] = mapped_column(Boolean, default=False)

    # Verification
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ocr_extracted_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ai_verification_score: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Security
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=True)
    encryption_key_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    malware_scan_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    malware_scanned_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    loan_application: Mapped[Optional["LoanApplication"]] = relationship(
        "LoanApplication", back_populates="documents"
    )
    verified_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[verified_by_id]
    )

    __table_args__ = (
        Index("ix_docs_user_type", "user_id", "document_type"),
        Index("ix_docs_loan_status", "loan_application_id", "status"),
        Index("ix_docs_file_hash", "file_hash"),
        Index("ix_docs_status", "status"),
        Index("ix_docs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<UploadedDocument id={self.id} "
            f"type={self.document_type} status={self.status}>"
        )
