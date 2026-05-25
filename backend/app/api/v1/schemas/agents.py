"""Agent API request/response schemas."""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SingleAgentRequest(BaseModel):
    agent: str = Field(..., description="Agent name: kyc|fraud|transaction|risk|support|report")
    input_data: Dict[str, Any] = Field(default_factory=dict)
    language: str = Field(default="en")


class LoanPipelineRequest(BaseModel):
    loan_application_id: uuid.UUID
    name: str
    pan_number: Optional[str] = None
    aadhaar_uid: Optional[str] = None
    dob: Optional[str] = None
    monthly_income: float = Field(..., gt=0)
    annual_income: float = Field(..., gt=0)
    existing_emi: float = Field(default=0.0, ge=0)
    employment_type: str = Field(default="salaried")
    loan_type: str = Field(default="personal")
    requested_amount: float = Field(..., gt=0)
    requested_tenure_months: int = Field(..., gt=0)
    currency: str = Field(default="INR")
    documents: List[Dict[str, Any]] = Field(default_factory=list)
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    language: str = Field(default="en")


class FraudInvestigationRequest(BaseModel):
    user_id: str
    name: Optional[str] = None
    pan_number: Optional[str] = None
    subject_id: str = Field(..., description="Transaction or application ID")
    event_type: str = Field(default="transaction")
    transaction_data: Dict[str, Any] = Field(default_factory=dict)
    behavioral_context: Dict[str, Any] = Field(default_factory=dict)
    language: str = Field(default="en")


class KYCRequest(BaseModel):
    customer_id: str
    name: str
    pan_number: Optional[str] = None
    aadhaar_uid: Optional[str] = None
    dob: Optional[str] = None
    application_type: str = Field(default="account_opening")
    documents: List[Dict[str, Any]] = Field(default_factory=list)
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    language: str = Field(default="en")


class SupportRequest(BaseModel):
    customer_id: str
    customer_name: str = "Valued Customer"
    account_status: str = "active"
    user_query: str = Field(..., min_length=2, max_length=2000)
    interaction_history: List[Dict[str, Any]] = Field(default_factory=list)
    language: str = Field(default="en")


class AgentRunResponse(BaseModel):
    agent: str
    run_id: str
    decision: str
    confidence: float
    risk_level: str
    reasoning: str
    key_factors: List[str]
    escalation_required: bool
    human_handoff: bool
    warnings: List[str]
    result: Dict[str, Any]
    processing_time_ms: Optional[int]
    model_used: str
    fallback_triggered: bool


class PipelineSummary(BaseModel):
    pipeline_id: str
    pipeline_type: str
    final_decision: Optional[str]
    escalation_required: bool
    agents_run: List[str]
    result: Dict[str, Any]
