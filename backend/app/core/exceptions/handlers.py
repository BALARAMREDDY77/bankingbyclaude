"""
Centralized Exception Handling
================================
Defines the full exception hierarchy for the platform.
All domain exceptions extend PlatformException, which maps to structured
HTTP error responses via registered FastAPI exception handlers.

Exception → HTTP Status mapping is explicit and auditable.
"""

from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Error Codes Enum
# ──────────────────────────────────────────────

class ErrorCode(str, Enum):
    # Generic
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFLICT = "CONFLICT"
    FORBIDDEN = "FORBIDDEN"
    UNAUTHORIZED = "UNAUTHORIZED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    BAD_REQUEST = "BAD_REQUEST"

    # Database
    DB_CONNECTION_ERROR = "DB_CONNECTION_ERROR"
    DB_CONSTRAINT_VIOLATION = "DB_CONSTRAINT_VIOLATION"
    DB_RECORD_NOT_FOUND = "DB_RECORD_NOT_FOUND"

    # Configuration
    CONFIG_ERROR = "CONFIG_ERROR"

    # External services
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    CACHE_ERROR = "CACHE_ERROR"


# ──────────────────────────────────────────────
# Base Platform Exception
# ──────────────────────────────────────────────

class PlatformException(Exception):
    """
    Base exception for all platform-level errors.
    Carries structured metadata for consistent error responses.
    """

    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: Optional[str] = None,
        detail: Optional[Any] = None,
        error_code: Optional[ErrorCode] = None,
    ) -> None:
        self.message = message or self.default_message
        self.detail = detail
        if error_code:
            self.error_code = error_code
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "detail": self.detail,
        }


# ──────────────────────────────────────────────
# HTTP-Mapped Exceptions
# ──────────────────────────────────────────────

class NotFoundException(PlatformException):
    http_status = status.HTTP_404_NOT_FOUND
    error_code = ErrorCode.NOT_FOUND
    default_message = "The requested resource was not found."


class ConflictException(PlatformException):
    http_status = status.HTTP_409_CONFLICT
    error_code = ErrorCode.CONFLICT
    default_message = "A conflict occurred with the current state of the resource."


class ForbiddenException(PlatformException):
    http_status = status.HTTP_403_FORBIDDEN
    error_code = ErrorCode.FORBIDDEN
    default_message = "You do not have permission to perform this action."


class UnauthorizedException(PlatformException):
    http_status = status.HTTP_401_UNAUTHORIZED
    error_code = ErrorCode.UNAUTHORIZED
    default_message = "Authentication is required to access this resource."


class BadRequestException(PlatformException):
    http_status = status.HTTP_400_BAD_REQUEST
    error_code = ErrorCode.BAD_REQUEST
    default_message = "The request is malformed or contains invalid parameters."


class RateLimitException(PlatformException):
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = ErrorCode.RATE_LIMITED
    default_message = "Too many requests. Please slow down."


class ServiceUnavailableException(PlatformException):
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.SERVICE_UNAVAILABLE
    default_message = "The service is temporarily unavailable. Please try again later."


# ──────────────────────────────────────────────
# Domain-Specific Exceptions
# ──────────────────────────────────────────────

class DatabaseException(PlatformException):
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.DB_CONNECTION_ERROR
    default_message = "A database error occurred."


class CacheException(PlatformException):
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.CACHE_ERROR
    default_message = "A cache error occurred."


class ExternalServiceException(PlatformException):
    http_status = status.HTTP_502_BAD_GATEWAY
    error_code = ErrorCode.EXTERNAL_SERVICE_ERROR
    default_message = "An external service returned an unexpected response."


# ──────────────────────────────────────────────
# Error Response Builder
# ──────────────────────────────────────────────

def _build_error_response(
    status_code: int,
    error_code: str,
    message: str,
    detail: Any = None,
    request_id: Optional[str] = None,
) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": error_code,
                "message": message,
                "detail": detail,
            },
            "request_id": request_id or str(uuid4()),
        },
    )


# ──────────────────────────────────────────────
# Exception Handlers
# ──────────────────────────────────────────────

async def platform_exception_handler(
    request: Request, exc: PlatformException
) -> ORJSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    logger.warning(
        "platform.exception",
        error_code=exc.error_code.value,
        message=exc.message,
        path=request.url.path,
        method=request.method,
        request_id=request_id,
    )
    return _build_error_response(
        status_code=exc.http_status,
        error_code=exc.error_code.value,
        message=exc.message,
        detail=exc.detail,
        request_id=request_id,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> ORJSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    errors = [
        {
            "field": " -> ".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    logger.info(
        "request.validation_failed",
        errors=errors,
        path=request.url.path,
        request_id=request_id,
    )
    return _build_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error_code=ErrorCode.VALIDATION_ERROR.value,
        message="Request validation failed.",
        detail=errors,
        request_id=request_id,
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> ORJSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    logger.exception(
        "unhandled.exception",
        exc_info=exc,
        path=request.url.path,
        method=request.method,
        request_id=request_id,
    )
    return _build_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code=ErrorCode.INTERNAL_ERROR.value,
        message="An internal server error occurred.",
        request_id=request_id,
    )


# ──────────────────────────────────────────────
# Registration Helper
# ──────────────────────────────────────────────

def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""
    app.add_exception_handler(PlatformException, platform_exception_handler)  # type: ignore
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore
