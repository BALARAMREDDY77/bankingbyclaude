"""
Agent API Endpoints
=====================
POST /agents/run                    — Run any single agent
POST /agents/pipeline/loan          — Full loan assessment pipeline
POST /agents/pipeline/fraud         — Fraud investigation pipeline
POST /agents/pipeline/kyc           — KYC onboarding pipeline
POST /agents/support                — Customer support query
GET  /agents/registry               — List all available agents
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.agents import (
    AgentRunResponse, FraudInvestigationRequest, KYCRequest,
    LoanPipelineRequest, PipelineSummary, SingleAgentRequest, SupportRequest,
)
from app.api.v1.schemas.response import APIResponse
from app.auth.dependencies import CurrentUser
from app.auth.utils.rbac import RequireStaff
from app.core.exceptions import BadRequestException
from app.core.logging import get_logger
from app.db.session import get_db
from app.agents.services.agent_service import AGENT_REGISTRY, AgentService

logger = get_logger(__name__)
router = APIRouter(prefix="/agents", tags=["AI Agents"])

REGISTRY_INFO = [
    {"name": "kyc", "description": "KYC Identity Verification", "input_fields": ["customer_id", "name", "pan_number", "aadhaar_uid", "documents"]},
    {"name": "fraud", "description": "Fraud Detection & AML Screening", "input_fields": ["user_id", "transaction_data", "behavioral_context"]},
    {"name": "transaction", "description": "Bank Statement Transaction Analysis", "input_fields": ["user_id", "months", "loan_application_id"]},
    {"name": "risk", "description": "Composite Risk Scoring & Loan Eligibility", "input_fields": ["user_id", "pan_number", "requested_amount", "loan_type"]},
    {"name": "support", "description": "Multilingual Customer Support (RAG)", "input_fields": ["customer_id", "user_query"]},
    {"name": "report", "description": "Structured Report Generation", "input_fields": ["report_type", "data_inputs", "agent_outputs"]},
]


# ──────────────────────────────────────────────
# Single Agent Run
# ──────────────────────────────────────────────

@router.post(
    "/run",
    summary="Run a single AI agent",
    response_model=APIResponse[dict],
)
async def run_single_agent(
    body: SingleAgentRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    if body.agent not in AGENT_REGISTRY:
        raise BadRequestException(f"Unknown agent '{body.agent}'. Valid: {list(AGENT_REGISTRY.keys())}")

    svc = AgentService(db)
    result = await svc.run_agent(body.agent, body.input_data, language=body.language)

    logger.info("api.agent_run", agent=body.agent, user=str(current_user.id),
                decision=result.get("decision"), confidence=result.get("confidence"))

    return APIResponse.ok(
        data=result,
        message=f"Agent '{body.agent}' completed with decision: {result.get('decision')}",
    )


# ──────────────────────────────────────────────
# Loan Pipeline
# ──────────────────────────────────────────────

@router.post(
    "/pipeline/loan",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Full loan assessment pipeline (KYC → Transaction → Risk → Report)",
    response_model=APIResponse[dict],
)
async def run_loan_pipeline(
    body: LoanPipelineRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    svc = AgentService(db)
    result = await svc.run_full_loan_pipeline(
        input_data={
            **body.model_dump(exclude={"language"}),
            "loan_application_id": str(body.loan_application_id),
            "user_id": str(current_user.id),
            "customer_id": str(current_user.id),
        },
        language=body.language,
    )
    summary = result.get("pipeline_summary", {})
    logger.info("api.loan_pipeline", user=str(current_user.id),
                loan_id=str(body.loan_application_id), eligible=summary.get("loan_eligible"))

    return APIResponse.ok(data=result, message="Loan assessment pipeline completed.")


# ──────────────────────────────────────────────
# Fraud Investigation Pipeline
# ──────────────────────────────────────────────

@router.post(
    "/pipeline/fraud",
    summary="Fraud investigation pipeline (Fraud → Risk → Report)",
    response_model=APIResponse[dict],
)
async def run_fraud_pipeline(
    body: FraudInvestigationRequest,
    current_user: CurrentUser = Depends(RequireStaff),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    svc = AgentService(db)
    result = await svc.run_fraud_investigation(
        input_data=body.model_dump(exclude={"language"}),
        language=body.language,
    )
    summary = result.get("pipeline_summary", {})
    logger.info("api.fraud_pipeline", user=str(current_user.id),
                subject=body.user_id, is_fraud=summary.get("is_fraudulent"))

    return APIResponse.ok(data=result, message="Fraud investigation completed.")


# ──────────────────────────────────────────────
# KYC Onboarding Pipeline
# ──────────────────────────────────────────────

@router.post(
    "/pipeline/kyc",
    summary="KYC onboarding pipeline (KYC → Report)",
    response_model=APIResponse[dict],
)
async def run_kyc_pipeline(
    body: KYCRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    svc = AgentService(db)
    result = await svc.run_kyc_onboarding(
        input_data=body.model_dump(exclude={"language"}),
        language=body.language,
    )
    logger.info("api.kyc_pipeline", user=str(current_user.id),
                verified=result.get("pipeline_summary", {}).get("identity_verified"))

    return APIResponse.ok(data=result, message="KYC verification completed.")


# ──────────────────────────────────────────────
# Customer Support
# ──────────────────────────────────────────────

@router.post(
    "/support",
    summary="Multilingual customer support query",
    response_model=APIResponse[dict],
)
async def customer_support(
    body: SupportRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    svc = AgentService(db)
    result = await svc.run_agent(
        "support",
        {
            **body.model_dump(exclude={"language"}),
            "customer_id": str(current_user.id),
        },
        language=body.language,
    )
    return APIResponse.ok(data=result, message="Support response generated.")


# ──────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────

@router.get(
    "/registry",
    summary="List all available AI agents",
    response_model=APIResponse[list],
)
async def list_agents(current_user: CurrentUser) -> APIResponse[list]:
    return APIResponse.ok(data=REGISTRY_INFO)
