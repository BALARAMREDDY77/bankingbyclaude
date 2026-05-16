"""Orchestration API Pydantic schemas."""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WorkflowRunRequest(BaseModel):
    workflow: str = Field(..., description="Workflow name: loan_assessment | fraud_detection | document_verification")
    input_data: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[uuid.UUID] = None
    stream: bool = Field(default=False)


class WorkflowRunResponse(BaseModel):
    run_id: str
    workflow: str
    status: str
    output: Optional[Dict[str, Any]] = None
    decision: Optional[str] = None
    confidence: Optional[float] = None
    error: Optional[str] = None


class LoanAssessmentRequest(BaseModel):
    loan_application_id: uuid.UUID
    loan_type: str = Field(default="personal")
    requested_amount: float = Field(..., gt=0)
    requested_tenure_months: int = Field(..., gt=0)
    employment_type: str = Field(default="salaried")
    monthly_income: float = Field(..., gt=0)
    annual_income: float = Field(..., gt=0)
    existing_emi: float = Field(default=0.0, ge=0)
    credit_score: Optional[int] = Field(default=None, ge=300, le=900)
    document_types: List[str] = Field(default_factory=list)
    currency: str = Field(default="INR")
    session_id: Optional[uuid.UUID] = None
    stream: bool = Field(default=False)


class WorkflowStatusResponse(BaseModel):
    run_id: str
    workflow_name: str
    status: str
    agent_name: str
    total_steps: int
    total_tokens: int
    duration_ms: Optional[int]
    error_message: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


class TraceStepResponse(BaseModel):
    index: int
    node: str
    latency_ms: Optional[int]
    decision: Optional[str]
    confidence: Optional[float]
    error: Optional[str]
    timestamp: str


class TraceResponse(BaseModel):
    run_id: str
    workflow_name: str
    total_steps: int
    total_ms: Optional[int]
    steps: List[TraceStepResponse]
