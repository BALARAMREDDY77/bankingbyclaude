"""
Authentication Pydantic Schemas
=================================
Request/Response schemas for all auth endpoints.
All input schemas validate and sanitize data before it reaches the service.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ──────────────────────────────────────────────
# Request Schemas
# ──────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=12, max_length=128)
    confirm_password: str = Field(..., min_length=12, max_length=128)
    first_name: str = Field(..., min_length=1, max_length=100, strip_whitespace=True)
    last_name: str = Field(..., min_length=1, max_length=100, strip_whitespace=True)
    phone: Optional[str] = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def passwords_match(self) -> "RegisterRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        digits = "".join(c for c in v if c.isdigit() or c in "+-() ")
        if len(digits.replace(" ", "").replace("-", "").replace("+", "")) < 7:
            raise ValueError("Phone number appears invalid.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip()


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)
    logout_everywhere: bool = Field(default=False)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=12, max_length=128)
    confirm_new_password: str = Field(..., min_length=12, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_new_password:
            raise ValueError("New passwords do not match.")
        return self


class RequestPasswordResetRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip()


class CompletePasswordResetRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=12, max_length=128)
    confirm_new_password: str = Field(..., min_length=12, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> "CompletePasswordResetRequest":
        if self.new_password != self.confirm_new_password:
            raise ValueError("Passwords do not match.")
        return self


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=10)


# ──────────────────────────────────────────────
# Response Schemas
# ──────────────────────────────────────────────

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    full_name: str
    phone: Optional[str]
    role: str
    status: str
    is_email_verified: bool
    mfa_enabled: bool
    last_login_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user: object) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            full_name=user.full_name,
            phone=user.phone,
            role=user.role.value,
            status=user.status.value,
            is_email_verified=user.is_email_verified,
            mfa_enabled=user.mfa_enabled,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
        )


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class LoginResponse(BaseModel):
    user: UserResponse
    tokens: TokenResponse
    is_suspicious: bool = False


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    message: str


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    description: str
    ip_address: Optional[str]
    severity: str
    metadata: Optional[dict]
    created_at: datetime

    model_config = {"from_attributes": True}
