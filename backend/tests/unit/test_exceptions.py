"""
Unit Tests — Exception Hierarchy
Tests that all exceptions carry correct status codes and error codes.
"""

import pytest
from app.core.exceptions import (
    NotFoundException,
    ConflictException,
    ForbiddenException,
    UnauthorizedException,
    BadRequestException,
    RateLimitException,
    ServiceUnavailableException,
    DatabaseException,
    ErrorCode,
)


class TestExceptionHierarchy:
    @pytest.mark.unit
    def test_not_found_status(self):
        exc = NotFoundException("Account not found")
        assert exc.http_status == 404
        assert exc.error_code == ErrorCode.NOT_FOUND
        assert exc.message == "Account not found"

    @pytest.mark.unit
    def test_conflict_status(self):
        exc = ConflictException()
        assert exc.http_status == 409
        assert exc.error_code == ErrorCode.CONFLICT

    @pytest.mark.unit
    def test_forbidden_status(self):
        exc = ForbiddenException()
        assert exc.http_status == 403
        assert exc.error_code == ErrorCode.FORBIDDEN

    @pytest.mark.unit
    def test_unauthorized_status(self):
        exc = UnauthorizedException()
        assert exc.http_status == 401
        assert exc.error_code == ErrorCode.UNAUTHORIZED

    @pytest.mark.unit
    def test_bad_request_status(self):
        exc = BadRequestException("Invalid IBAN")
        assert exc.http_status == 400
        assert exc.message == "Invalid IBAN"

    @pytest.mark.unit
    def test_rate_limit_status(self):
        exc = RateLimitException()
        assert exc.http_status == 429

    @pytest.mark.unit
    def test_service_unavailable_status(self):
        exc = ServiceUnavailableException()
        assert exc.http_status == 503

    @pytest.mark.unit
    def test_database_exception_status(self):
        exc = DatabaseException("Connection refused")
        assert exc.http_status == 503
        assert exc.error_code == ErrorCode.DB_CONNECTION_ERROR

    @pytest.mark.unit
    def test_exception_to_dict(self):
        exc = NotFoundException("User not found", detail={"id": "123"})
        d = exc.to_dict()
        assert d["error_code"] == "NOT_FOUND"
        assert d["message"] == "User not found"
        assert d["detail"] == {"id": "123"}

    @pytest.mark.unit
    def test_custom_error_code_override(self):
        exc = NotFoundException(
            "DB record missing", error_code=ErrorCode.DB_RECORD_NOT_FOUND
        )
        assert exc.error_code == ErrorCode.DB_RECORD_NOT_FOUND
