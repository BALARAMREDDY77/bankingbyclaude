"""
Standard API Response Schemas
===============================
All API endpoints MUST return responses using these schemas.
This ensures a consistent envelope format across the entire platform.

Success envelope:
{
  "success": true,
  "data": { ... },
  "meta": { "page": 1, "total": 100 },
  "request_id": "uuid"
}

Error envelope (see exceptions/handlers.py):
{
  "success": false,
  "error": { "code": "...", "message": "...", "detail": ... },
  "request_id": "uuid"
}
"""

from typing import Any, Generic, List, Optional, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field
from pydantic.generics import GenericModel

DataT = TypeVar("DataT")


# ──────────────────────────────────────────────
# Pagination Meta
# ──────────────────────────────────────────────

class PaginationMeta(BaseModel):
    page: int = Field(..., ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(..., ge=1, le=500, description="Items per page")
    total_items: int = Field(..., ge=0, description="Total items across all pages")
    total_pages: int = Field(..., ge=0, description="Total page count")
    has_next: bool
    has_prev: bool

    @classmethod
    def build(cls, *, page: int, page_size: int, total_items: int) -> "PaginationMeta":
        total_pages = max(1, -(-total_items // page_size))  # Ceiling division
        return cls(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        )


# ──────────────────────────────────────────────
# Success Response
# ──────────────────────────────────────────────

class APIResponse(GenericModel, Generic[DataT]):
    """Standard success response envelope."""

    success: bool = True
    data: DataT
    meta: Optional[PaginationMeta] = None
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    message: Optional[str] = None

    @classmethod
    def ok(
        cls,
        data: DataT,
        *,
        message: Optional[str] = None,
        meta: Optional[PaginationMeta] = None,
        request_id: Optional[str] = None,
    ) -> "APIResponse[DataT]":
        return cls(
            data=data,
            message=message,
            meta=meta,
            request_id=request_id or str(uuid4()),
        )


class PaginatedAPIResponse(GenericModel, Generic[DataT]):
    """Standard paginated list response envelope."""

    success: bool = True
    data: List[DataT]
    meta: PaginationMeta
    request_id: str = Field(default_factory=lambda: str(uuid4()))


# ──────────────────────────────────────────────
# Pagination Query Params
# ──────────────────────────────────────────────

class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size
