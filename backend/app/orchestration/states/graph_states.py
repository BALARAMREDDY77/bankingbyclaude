"""
LangGraph State Definitions
==============================
All typed state classes for the banking orchestration graphs.
States are TypedDicts — LangGraph merges them with reducers.

State design principles:
  - Every field is Optional with a sensible default
  - Lists use append-reducer (new items concat, not replaced)
  - Immutable audit fields (timestamps, IDs)
  - Confidence scoring on every agent output
  - Error state carries full traceback for debugging
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"
    AWAITING_HUMAN = "awaiting_human"


class AgentDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    REQUEST_MORE_INFO = "request_more_info"
    PASS = "pass"                          # No decision — pass to next node


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ──────────────────────────────────────────────
# Base State
# ──────────────────────────────────────────────

class BaseGraphState(TypedDict, total=False):
    """
    Fields shared across ALL banking workflow graphs.
    Every graph state extends this.
    """
    # Execution identity
    run_id: str                             # Unique run identifier
    workflow_name: str                      # Graph name
    session_id: Optional[str]              # Chat session ID
    user_id: str                           # Initiating user
    created_at: str                        # ISO timestamp

    # Status tracking
    status: WorkflowStatus
    current_node: str                      # Currently executing node
    completed_nodes: List[str]             # Nodes that have run
    iteration_count: int                   # Guard against infinite loops

    # Message history (append-reducer — messages accumulate)
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Error handling
    error: Optional[str]                   # Last error message
    error_node: Optional[str]             # Node where error occurred
    retry_count: int                       # Current retry attempt
    fallback_triggered: bool              # Whether fallback was used

    # Confidence & decisions
    confidence_score: float               # 0.0–1.0 overall confidence
    final_decision: Optional[AgentDecision]
    decision_reason: Optional[str]
    escalation_reason: Optional[str]

    # Observability
    trace: List[Dict[str, Any]]           # Step-by-step execution trace
    latency_ms: Dict[str, int]           # Per-node latency tracking
    token_usage: Dict[str, int]          # Per-node token consumption

    # Output
    output: Optional[Dict[str, Any]]     # Final structured output
    streaming_buffer: List[str]          # Streaming text chunks


# ──────────────────────────────────────────────
# Loan Assessment State
# ──────────────────────────────────────────────

class LoanAssessmentState(BaseGraphState, total=False):
    """State for the loan underwriting assessment workflow."""

    # Loan application context
    loan_application_id: str
    loan_type: str
    requested_amount: float
    requested_tenure_months: int
    currency: str

    # Applicant profile
    applicant_name: str
    applicant_email: str
    employment_type: str
    monthly_income: float
    annual_income: float
    existing_emi: float
    credit_score: Optional[int]
    debt_to_income_ratio: Optional[float]

    # Document analysis results
    documents_verified: bool
    document_types_present: List[str]
    missing_documents: List[str]
    document_confidence: float
    extracted_income: Optional[float]      # From salary slip OCR
    extracted_bank_balance: Optional[float]

    # RAG retrieval context
    retrieved_policies: List[Dict[str, Any]]
    policy_context: str                    # Formatted context window
    applicable_guidelines: List[str]

    # Agent assessments (parallel nodes)
    credit_assessment: Optional[Dict[str, Any]]
    income_assessment: Optional[Dict[str, Any]]
    document_assessment: Optional[Dict[str, Any]]
    risk_assessment: Optional[Dict[str, Any]]
    fraud_screening: Optional[Dict[str, Any]]

    # Computed scores
    credit_risk_score: float               # 0.0–1.0 (higher = riskier)
    income_adequacy_score: float           # 0.0–1.0 (higher = better)
    document_completeness_score: float
    fraud_risk_score: float
    overall_risk_level: RiskLevel

    # Decision
    recommended_amount: Optional[float]
    recommended_tenure_months: Optional[int]
    recommended_interest_rate: Optional[float]
    emi_calculated: Optional[float]
    conditions: List[str]                  # Conditions for approval


# ──────────────────────────────────────────────
# Fraud Detection State
# ──────────────────────────────────────────────

class FraudDetectionState(BaseGraphState, total=False):
    """State for the fraud detection workflow."""

    # Subject
    transaction_id: Optional[str]
    loan_application_id: Optional[str]
    user_id_subject: str                   # User being investigated

    # Transaction context
    amount: Optional[float]
    currency: Optional[str]
    transaction_type: Optional[str]
    channel: Optional[str]
    ip_address: Optional[str]
    device_fingerprint: Optional[str]

    # Behavioral analysis
    transaction_velocity: Optional[Dict[str, Any]]
    location_analysis: Optional[Dict[str, Any]]
    time_pattern_analysis: Optional[Dict[str, Any]]
    amount_pattern_analysis: Optional[Dict[str, Any]]

    # ML / Rule outputs
    rule_engine_flags: List[str]
    ml_fraud_score: float                  # 0.0–1.0 (higher = more fraudulent)
    anomaly_score: float

    # RAG retrieved fraud patterns
    matching_fraud_patterns: List[Dict[str, Any]]
    aml_flags: List[str]

    # Agent assessments
    pattern_analysis: Optional[Dict[str, Any]]
    document_fraud_analysis: Optional[Dict[str, Any]]
    identity_verification: Optional[Dict[str, Any]]

    # Investigation
    fraud_indicators: List[str]
    risk_factors: List[str]
    evidence: List[Dict[str, Any]]
    recommended_action: Optional[str]      # block | flag | monitor | clear
    report_required: bool


# ──────────────────────────────────────────────
# Document Verification State
# ──────────────────────────────────────────────

class DocumentVerificationState(BaseGraphState, total=False):
    """State for the automated document verification workflow."""

    # Document context
    document_id: str
    document_type: str
    loan_application_id: Optional[str]

    # OCR results (from Phase 4)
    ocr_text: str
    ocr_confidence: float
    ocr_method: str
    is_scanned: bool

    # Extracted fields
    extracted_fields: Dict[str, Any]
    extraction_confidence: float

    # Verification checks
    format_check: Optional[Dict[str, Any]]      # Format/pattern validation
    authenticity_check: Optional[Dict[str, Any]] # Tamper detection
    consistency_check: Optional[Dict[str, Any]]  # Cross-doc consistency
    expiry_check: Optional[Dict[str, Any]]

    # RAG context
    verification_guidelines: str

    # Results
    is_authentic: Optional[bool]
    is_valid: Optional[bool]
    rejection_reasons: List[str]
    verification_notes: str


# ──────────────────────────────────────────────
# Customer Support State
# ──────────────────────────────────────────────

class CustomerSupportState(BaseGraphState, total=False):
    """State for the customer support / Q&A workflow."""

    # Customer context
    customer_name: str
    customer_email: str
    account_status: str
    loan_applications: List[Dict[str, Any]]

    # Query
    user_query: str
    query_intent: Optional[str]            # Classified intent
    query_language: Optional[str]
    query_entities: List[str]             # Extracted entities

    # RAG retrieval
    knowledge_base: str
    retrieved_chunks: List[Dict[str, Any]]
    context_window: str
    retrieval_quality: str

    # Response generation
    draft_response: Optional[str]
    final_response: Optional[str]
    response_language: Optional[str]
    citations: List[str]
    follow_up_suggestions: List[str]

    # Routing
    needs_human_handoff: bool
    handoff_reason: Optional[str]
    sentiment: Optional[str]              # positive | neutral | negative


# ──────────────────────────────────────────────
# Orchestrator Meta-State
# ──────────────────────────────────────────────

class OrchestratorState(BaseGraphState, total=False):
    """
    Top-level meta-state for the central orchestrator.
    Routes to sub-graphs based on intent.
    """
    # Intent classification
    intent: Optional[str]                  # loan_assessment | fraud_detection | ...
    intent_confidence: float
    intent_params: Dict[str, Any]         # Params extracted from the request

    # Sub-graph results
    sub_graph_result: Optional[Dict[str, Any]]
    sub_graph_name: Optional[str]

    # Guardrail results
    input_guardrail_passed: bool
    output_guardrail_passed: bool
    guardrail_violations: List[str]
