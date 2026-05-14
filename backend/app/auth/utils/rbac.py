"""
Role-Based Access Control (RBAC)
==================================
Defines permission sets per role and provides FastAPI dependency
decorators for protecting endpoints.

Permission hierarchy:
  admin > fraud_reviewer > employee > customer

Usage:
    @router.get("/admin-only")
    async def admin_endpoint(
        current_user: User = Depends(require_roles(UserRole.ADMIN))
    ): ...

    @router.get("/staff")
    async def staff_endpoint(
        current_user: User = Depends(require_roles(UserRole.EMPLOYEE, UserRole.ADMIN))
    ): ...
"""

from enum import Enum
from functools import lru_cache
from typing import Callable, Set

from fastapi import Depends

from app.core.exceptions import ForbiddenException
from app.core.logging import get_logger
from app.db.models.user import User, UserRole

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Permission Definitions
# ──────────────────────────────────────────────

class Permission(str, Enum):
    # Account permissions
    ACCOUNT_READ_OWN = "account:read:own"
    ACCOUNT_READ_ANY = "account:read:any"
    ACCOUNT_CREATE = "account:create"
    ACCOUNT_UPDATE_OWN = "account:update:own"
    ACCOUNT_UPDATE_ANY = "account:update:any"
    ACCOUNT_CLOSE = "account:close"

    # Transaction permissions
    TRANSACTION_READ_OWN = "transaction:read:own"
    TRANSACTION_READ_ANY = "transaction:read:any"
    TRANSACTION_CREATE = "transaction:create"
    TRANSACTION_REVERSE = "transaction:reverse"

    # User management
    USER_READ_OWN = "user:read:own"
    USER_READ_ANY = "user:read:any"
    USER_UPDATE_OWN = "user:update:own"
    USER_UPDATE_ANY = "user:update:any"
    USER_CREATE = "user:create"
    USER_DELETE = "user:delete"
    USER_CHANGE_ROLE = "user:change_role"

    # Fraud & compliance
    FRAUD_REVIEW = "fraud:review"
    FRAUD_FLAG = "fraud:flag"
    FRAUD_RESOLVE = "fraud:resolve"
    COMPLIANCE_READ = "compliance:read"
    AUDIT_LOG_READ = "audit:read"

    # System
    SYSTEM_CONFIG_READ = "system:config:read"
    SYSTEM_CONFIG_WRITE = "system:config:write"
    AI_AGENT_USE = "ai:agent:use"
    AI_AGENT_MANAGE = "ai:agent:manage"


# ──────────────────────────────────────────────
# Role → Permission Matrix
# ──────────────────────────────────────────────

ROLE_PERMISSIONS: dict[UserRole, Set[Permission]] = {

    UserRole.CUSTOMER: {
        Permission.ACCOUNT_READ_OWN,
        Permission.ACCOUNT_UPDATE_OWN,
        Permission.TRANSACTION_READ_OWN,
        Permission.TRANSACTION_CREATE,
        Permission.USER_READ_OWN,
        Permission.USER_UPDATE_OWN,
        Permission.AI_AGENT_USE,
    },

    UserRole.EMPLOYEE: {
        # All customer permissions
        *ROLE_PERMISSIONS.get(UserRole.CUSTOMER, set()) if False else set(),
        Permission.ACCOUNT_READ_OWN,
        Permission.ACCOUNT_READ_ANY,
        Permission.ACCOUNT_UPDATE_OWN,
        Permission.ACCOUNT_UPDATE_ANY,
        Permission.ACCOUNT_CREATE,
        Permission.TRANSACTION_READ_OWN,
        Permission.TRANSACTION_READ_ANY,
        Permission.TRANSACTION_CREATE,
        Permission.USER_READ_OWN,
        Permission.USER_READ_ANY,
        Permission.USER_UPDATE_OWN,
        Permission.FRAUD_REVIEW,
        Permission.COMPLIANCE_READ,
        Permission.AI_AGENT_USE,
    },

    UserRole.FRAUD_REVIEWER: {
        Permission.ACCOUNT_READ_ANY,
        Permission.TRANSACTION_READ_ANY,
        Permission.TRANSACTION_REVERSE,
        Permission.USER_READ_ANY,
        Permission.USER_READ_OWN,
        Permission.FRAUD_REVIEW,
        Permission.FRAUD_FLAG,
        Permission.FRAUD_RESOLVE,
        Permission.COMPLIANCE_READ,
        Permission.AUDIT_LOG_READ,
        Permission.AI_AGENT_USE,
    },

    UserRole.ADMIN: {
        # Full access — all permissions
        *list(Permission),
    },
}

# Fix employee permissions properly (Python dict ordering)
ROLE_PERMISSIONS[UserRole.EMPLOYEE] = {
    Permission.ACCOUNT_READ_OWN,
    Permission.ACCOUNT_READ_ANY,
    Permission.ACCOUNT_UPDATE_OWN,
    Permission.ACCOUNT_UPDATE_ANY,
    Permission.ACCOUNT_CREATE,
    Permission.TRANSACTION_READ_OWN,
    Permission.TRANSACTION_READ_ANY,
    Permission.TRANSACTION_CREATE,
    Permission.USER_READ_OWN,
    Permission.USER_READ_ANY,
    Permission.USER_UPDATE_OWN,
    Permission.FRAUD_REVIEW,
    Permission.COMPLIANCE_READ,
    Permission.AI_AGENT_USE,
}


@lru_cache(maxsize=None)
def get_permissions(role: UserRole) -> frozenset:
    """Return cached frozenset of permissions for a role."""
    return frozenset(ROLE_PERMISSIONS.get(role, set()))


def has_permission(user: User, permission: Permission) -> bool:
    """Check if a user's role grants a specific permission."""
    return permission in get_permissions(user.role)


# ──────────────────────────────────────────────
# FastAPI Dependency Factories
# ──────────────────────────────────────────────

def require_roles(*allowed_roles: UserRole) -> Callable:
    """
    Dependency factory — restricts endpoint to specific roles.

    Usage:
        Depends(require_roles(UserRole.ADMIN, UserRole.EMPLOYEE))
    """
    from app.auth.dependencies import get_current_active_user

    async def role_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in allowed_roles:
            logger.warning(
                "rbac.access_denied",
                user_id=str(current_user.id),
                user_role=current_user.role,
                required_roles=[r.value for r in allowed_roles],
            )
            raise ForbiddenException(
                f"This action requires one of these roles: "
                f"{', '.join(r.value for r in allowed_roles)}."
            )
        return current_user

    return role_checker


def require_permission(permission: Permission) -> Callable:
    """
    Dependency factory — restricts endpoint to users with a specific permission.

    Usage:
        Depends(require_permission(Permission.FRAUD_REVIEW))
    """
    from app.auth.dependencies import get_current_active_user

    async def permission_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if not has_permission(current_user, permission):
            logger.warning(
                "rbac.permission_denied",
                user_id=str(current_user.id),
                user_role=current_user.role,
                required_permission=permission.value,
            )
            raise ForbiddenException(
                f"You do not have the required permission: {permission.value}."
            )
        return current_user

    return permission_checker


# ──────────────────────────────────────────────
# Convenience Role Dependencies
# ──────────────────────────────────────────────

RequireAdmin = require_roles(UserRole.ADMIN)
RequireEmployee = require_roles(UserRole.EMPLOYEE, UserRole.ADMIN)
RequireFraudReviewer = require_roles(UserRole.FRAUD_REVIEWER, UserRole.ADMIN)
RequireStaff = require_roles(UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.FRAUD_REVIEWER)
RequireAnyRole = require_roles(*list(UserRole))
