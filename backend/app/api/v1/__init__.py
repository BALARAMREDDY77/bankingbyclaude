"""
API v1 Router
==============
Aggregates all v1 endpoint routers.
New feature routers are registered here as they are built in future phases.
"""

from fastapi import APIRouter

from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.documents import router as documents_router

# Root v1 router
api_v1_router = APIRouter()

# ── Core (Phase 1) ──────────────────────────
api_v1_router.include_router(health_router)

# ── Auth (Phase 2) ──────────────────────────
api_v1_router.include_router(auth_router)

# ── Documents (Phase 4) ─────────────────────
api_v1_router.include_router(documents_router)

# ── Future phases ────────────────────────────
# from app.api.v1.endpoints.accounts import router as accounts_router
# from app.api.v1.endpoints.transactions import router as transactions_router
# from app.api.v1.endpoints.agents import router as agents_router
