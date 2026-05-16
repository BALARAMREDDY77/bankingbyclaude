"""
Orchestration API Endpoints
==============================
POST /orchestration/run              — Run a workflow synchronously
POST /orchestration/run/stream       — Run a workflow with SSE streaming
POST /orchestration/loan-assessment  — Dedicated loan assessment endpoint
GET  /orchestration/traces/{run_id}  — Get execution trace
GET  /orchestration/workflows        — List available workflows
"""

import json
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.orchestration import (
    LoanAssessmentRequest,
    TraceResponse,
    TraceStepResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowStatusResponse,
)
from app.api.v1.schemas.response import APIResponse
from app.auth.dependencies import CurrentUser
from app.auth.utils.rbac import RequireStaff
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.logging import get_logger
from app.db.session import get_db
from app.orchestration.services.orchestrator import OrchestratorEngine

logger = get_logger(__name__)

router = APIRouter(prefix="/orchestration", tags=["Orchestration"])

AVAILABLE_WORKFLOWS = [
    {
        "name": "loan_assessment",
        "description": "End-to-end loan application assessment with credit, fraud, and document analysis",
        "nodes": ["document_verifier", "credit_assessor", "fraud_screener", "risk_scorer"],
        "supports_streaming": True,
    },
    {
        "name": "fraud_detection",
        "description": "Fraud detection and investigation workflow",
        "nodes": ["fraud_screener", "risk_scorer"],
        "supports_streaming": True,
    },
    {
        "name": "document_verification",
        "description": "Automated document verification pipeline",
        "nodes": ["document_verifier"],
        "supports_streaming": False,
    },
]


# ──────────────────────────────────────────────
# Run Workflow
# ──────────────────────────────────────────────

@router.post(
    "/run",
    summary="Run a named workflow synchronously",
    response_model=APIResponse[WorkflowRunResponse],
)
async def run_workflow(
    body: WorkflowRunRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[WorkflowRunResponse]:
    valid = [w["name"] for w in AVAILABLE_WORKFLOWS]
    if body.workflow not in valid:
        raise BadRequestException(f"Unknown workflow '{body.workflow}'. Valid: {valid}")

    engine = OrchestratorEngine(db)
    result = await engine.run(
        workflow=body.workflow,
        input_data=body.input_data,
        user_id=str(current_user.id),
        session_id=str(body.session_id) if body.session_id else None,
    )

    await db.commit()

    return APIResponse.ok(
        data=WorkflowRunResponse(
            run_id=result.get("run_id", ""),
            workflow=body.workflow,
            status=result.get("status", "completed"),
            output=result,
            decision=result.get("decision"),
            error=result.get("error"),
        )
    )


# ──────────────────────────────────────────────
# Streaming Run
# ──────────────────────────────────────────────

@router.post(
    "/run/stream",
    summary="Run workflow with Server-Sent Events streaming",
)
async def run_workflow_stream(
    body: WorkflowRunRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    valid = [w["name"] for w in AVAILABLE_WORKFLOWS]
    if body.workflow not in valid:
        raise BadRequestException(f"Unknown workflow: {body.workflow}")

    engine = OrchestratorEngine(db)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for chunk in engine.stream(
                workflow=body.workflow,
                input_data=body.input_data,
                user_id=str(current_user.id),
                session_id=str(body.session_id) if body.session_id else None,
            ):
                yield f"data: {json.dumps(chunk)}\n\n"
            await db.commit()
        except Exception as exc:
            yield f"data: {json.dumps({'event': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────────────────────────
# Loan Assessment (dedicated endpoint)
# ──────────────────────────────────────────────

@router.post(
    "/loan-assessment",
    summary="Run end-to-end loan assessment workflow",
    response_model=APIResponse[WorkflowRunResponse],
)
async def run_loan_assessment(
    body: LoanAssessmentRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[WorkflowRunResponse]:
    engine = OrchestratorEngine(db)

    input_data = {
        "loan_application_id": str(body.loan_application_id),
        "loan_type": body.loan_type,
        "requested_amount": body.requested_amount,
        "requested_tenure_months": body.requested_tenure_months,
        "employment_type": body.employment_type,
        "monthly_income": body.monthly_income,
        "annual_income": body.annual_income,
        "existing_emi": body.existing_emi,
        "credit_score": body.credit_score,
        "document_types": body.document_types,
        "currency": body.currency,
        "applicant_name": current_user.full_name,
        "applicant_email": current_user.email,
    }

    result = await engine.run(
        workflow="loan_assessment",
        input_data=input_data,
        user_id=str(current_user.id),
        session_id=str(body.session_id) if body.session_id else None,
    )

    await db.commit()

    logger.info(
        "loan_assessment.completed",
        user_id=str(current_user.id),
        loan_id=str(body.loan_application_id),
        decision=result.get("decision"),
    )

    return APIResponse.ok(
        data=WorkflowRunResponse(
            run_id=result.get("run_id", ""),
            workflow="loan_assessment",
            status=result.get("status", "completed"),
            output=result,
            decision=result.get("decision"),
            error=result.get("error"),
        ),
        message="Loan assessment completed.",
    )


# ──────────────────────────────────────────────
# Get Trace
# ──────────────────────────────────────────────

@router.get(
    "/traces/{run_id}",
    summary="Get execution trace for a workflow run",
    response_model=APIResponse[TraceResponse],
)
async def get_trace(
    run_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TraceResponse]:
    from sqlalchemy import text
    result = await db.execute(
        text("SELECT * FROM agent_traces WHERE run_id = :run_id"),
        {"run_id": run_id},
    )
    row = result.fetchone()
    if not row:
        raise NotFoundException(f"No trace found for run_id: {run_id}")

    steps_raw = row.steps or []
    if isinstance(steps_raw, str):
        import ast
        try:
            steps_raw = ast.literal_eval(steps_raw)
        except Exception:
            steps_raw = []

    steps = [
        TraceStepResponse(
            index=s.get("index", i),
            node=s.get("node", ""),
            latency_ms=s.get("latency_ms"),
            decision=s.get("decision"),
            confidence=s.get("confidence"),
            error=s.get("error"),
            timestamp=s.get("timestamp", ""),
        )
        for i, s in enumerate(steps_raw)
    ]

    return APIResponse.ok(
        data=TraceResponse(
            run_id=run_id,
            workflow_name=row.workflow_name or row.agent_name,
            total_steps=row.total_steps or len(steps),
            total_ms=row.duration_ms,
            steps=steps,
        )
    )


# ──────────────────────────────────────────────
# List Workflows
# ──────────────────────────────────────────────

@router.get(
    "/workflows",
    summary="List available workflows",
    response_model=APIResponse[list],
)
async def list_workflows(current_user: CurrentUser) -> APIResponse[list]:
    return APIResponse.ok(data=AVAILABLE_WORKFLOWS)
