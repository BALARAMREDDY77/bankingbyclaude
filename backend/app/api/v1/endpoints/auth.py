"""
Authentication Endpoints
==========================
All public and protected auth routes.

Public  (no auth required):
  POST /auth/register
  POST /auth/login
  POST /auth/refresh
  POST /auth/password/reset/request
  POST /auth/password/reset/complete
  POST /auth/email/verify

Protected (auth required):
  GET  /auth/me
  POST /auth/logout
  PUT  /auth/password/change
  GET  /auth/audit-log
  GET  /auth/sessions
"""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.auth import (
    AuditLogResponse,
    ChangePasswordRequest,
    CompletePasswordResetRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MessageResponse,
    RefreshResponse,
    RefreshTokenRequest,
    RegisterRequest,
    RequestPasswordResetRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from app.api.v1.schemas.response import APIResponse
from app.auth.dependencies import (
    CurrentUser,
    get_auth_service,
)
from app.auth.services.auth_service import AuthService
from app.auth.services.audit_service import AuditService
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user import AuditEventType
from app.db.repositories.user import AuditLogRepository
from app.db.session import get_db

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ── Helpers ──────────────────────────────────────────────────

def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set HttpOnly secure auth cookies for browser-based clients."""
    cookie_kwargs = dict(
        httponly=settings.auth.cookie_httponly,
        secure=settings.auth.cookie_secure,
        samesite=settings.auth.cookie_samesite,
    )
    response.set_cookie(
        "access_token", access_token,
        max_age=settings.auth.access_token_expire_minutes * 60,
        **cookie_kwargs,
    )
    response.set_cookie(
        "refresh_token", refresh_token,
        max_age=settings.auth.refresh_token_expire_days * 86400,
        path="/api/v1/auth/refresh",       # Restrict refresh cookie to refresh endpoint
        **cookie_kwargs,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token", path="/api/v1/auth/refresh")


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Public Routes ─────────────────────────────────────────────

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    response_model=APIResponse[UserResponse],
)
async def register(
    request: Request,
    body: RegisterRequest,
    auth_svc: AuthService = Depends(get_auth_service),
) -> APIResponse[UserResponse]:
    ip = _get_client_ip(request)
    user = await auth_svc.register_user(
        email=body.email,
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        ip_address=ip,
    )
    return APIResponse.ok(
        data=UserResponse.from_user(user),
        message="Account created. Please check your email to verify your account.",
    )


@router.post(
    "/login",
    summary="Authenticate and obtain tokens",
    response_model=APIResponse[LoginResponse],
)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    auth_svc: AuthService = Depends(get_auth_service),
) -> APIResponse[LoginResponse]:
    ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")

    access_token, refresh_token, user = await auth_svc.authenticate_user(
        email=body.email,
        password=body.password,
        ip_address=ip,
        user_agent=user_agent,
    )

    _set_auth_cookies(response, access_token, refresh_token)

    return APIResponse.ok(
        data=LoginResponse(
            user=UserResponse.from_user(user),
            tokens=TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=settings.auth.access_token_expire_minutes * 60,
            ),
        ),
        message="Login successful.",
    )


@router.post(
    "/refresh",
    summary="Refresh access token using refresh token",
    response_model=APIResponse[RefreshResponse],
)
async def refresh_token(
    request: Request,
    response: Response,
    body: RefreshTokenRequest,
    auth_svc: AuthService = Depends(get_auth_service),
) -> APIResponse[RefreshResponse]:
    ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")

    new_access, new_refresh = await auth_svc.refresh_tokens(
        refresh_token=body.refresh_token,
        ip_address=ip,
        user_agent=user_agent,
    )

    _set_auth_cookies(response, new_access, new_refresh)

    return APIResponse.ok(
        data=RefreshResponse(
            access_token=new_access,
            refresh_token=new_refresh,
        )
    )


@router.post(
    "/password/reset/request",
    summary="Request a password reset email",
    response_model=APIResponse[MessageResponse],
)
async def request_password_reset(
    request: Request,
    body: RequestPasswordResetRequest,
    auth_svc: AuthService = Depends(get_auth_service),
) -> APIResponse[MessageResponse]:
    ip = _get_client_ip(request)
    # Reset token returned here; in production, send via email service
    reset_token = await auth_svc.request_password_reset(body.email, ip)

    # Always return same message to prevent email enumeration
    return APIResponse.ok(
        data=MessageResponse(
            message="If an account exists for this email, a reset link has been sent."
        )
    )


@router.post(
    "/password/reset/complete",
    summary="Complete password reset with token",
    response_model=APIResponse[MessageResponse],
)
async def complete_password_reset(
    request: Request,
    body: CompletePasswordResetRequest,
    auth_svc: AuthService = Depends(get_auth_service),
) -> APIResponse[MessageResponse]:
    ip = _get_client_ip(request)
    await auth_svc.complete_password_reset(body.token, body.new_password, ip)
    return APIResponse.ok(
        data=MessageResponse(message="Password reset successful. Please log in with your new password.")
    )


@router.post(
    "/email/verify",
    summary="Verify email address with token",
    response_model=APIResponse[UserResponse],
)
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    auth_svc: AuthService = Depends(get_auth_service),
) -> APIResponse[UserResponse]:
    ip = _get_client_ip(request)
    user = await auth_svc.verify_email(body.token, ip)
    return APIResponse.ok(
        data=UserResponse.from_user(user),
        message="Email verified successfully. Your account is now active.",
    )


# ── Protected Routes ──────────────────────────────────────────

@router.get(
    "/me",
    summary="Get current authenticated user profile",
    response_model=APIResponse[UserResponse],
)
async def get_me(current_user: CurrentUser) -> APIResponse[UserResponse]:
    return APIResponse.ok(data=UserResponse.from_user(current_user))


@router.post(
    "/logout",
    summary="Logout current session or all sessions",
    response_model=APIResponse[MessageResponse],
)
async def logout(
    request: Request,
    response: Response,
    body: LogoutRequest,
    current_user: CurrentUser,
    auth_svc: AuthService = Depends(get_auth_service),
) -> APIResponse[MessageResponse]:
    ip = _get_client_ip(request)

    if body.logout_everywhere:
        await auth_svc.logout_everywhere(current_user.id, ip)
        msg = "Logged out from all devices."
    else:
        await auth_svc.logout(body.refresh_token, current_user.id, ip)
        msg = "Logged out successfully."

    _clear_auth_cookies(response)
    return APIResponse.ok(data=MessageResponse(message=msg))


@router.put(
    "/password/change",
    summary="Change password (requires current password)",
    response_model=APIResponse[MessageResponse],
)
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    auth_svc: AuthService = Depends(get_auth_service),
) -> APIResponse[MessageResponse]:
    ip = _get_client_ip(request)
    await auth_svc.change_password(
        user_id=current_user.id,
        current_password=body.current_password,
        new_password=body.new_password,
        ip_address=ip,
    )
    return APIResponse.ok(
        data=MessageResponse(
            message="Password changed. All active sessions have been revoked. Please log in again."
        )
    )


@router.get(
    "/audit-log",
    summary="Get current user's security audit log",
    response_model=APIResponse[List[AuditLogResponse]],
)
async def get_audit_log(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> APIResponse[List[AuditLogResponse]]:
    repo = AuditLogRepository(db)
    logs = await repo.get_recent_for_user(current_user.id, limit=min(limit, 200))
    return APIResponse.ok(
        data=[AuditLogResponse.model_validate(log) for log in logs]
    )


@router.get(
    "/sessions",
    summary="Get active sessions for current user",
    response_model=APIResponse[dict],
)
async def get_sessions(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    from app.db.repositories.user import RefreshTokenRepository
    repo = RefreshTokenRepository(db)
    active_count = await repo.get_active_count(current_user.id)
    return APIResponse.ok(
        data={"active_session_count": active_count}
    )
