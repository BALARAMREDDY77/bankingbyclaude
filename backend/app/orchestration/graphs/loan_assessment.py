"""
Loan Assessment Graph
=======================
LangGraph workflow for end-to-end loan application assessment.

Graph topology:
  START
    → document_verifier     (verify submitted docs)
    → [parallel fork]
        credit_assessor     (creditworthiness)
        fraud_screener      (fraud screening)
    → risk_scorer           (aggregate scores)
    → [conditional routing]
        ├── high_confidence + approve  → response_synthesizer → END
        ├── needs_conditions           → response_synthesizer → END
        └── low_confidence/escalate    → human_escalator → END
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.graph import CompiledGraph

from app.core.config import settings
from app.core.logging import get_logger
from app.orchestration.nodes.banking_nodes import (
    CreditAssessmentNode,
    DocumentVerifierNode,
    FraudScreeningNode,
    HumanEscalationNode,
    ResponseSynthesisNode,
    RiskScoringNode,
)
from app.orchestration.states.graph_states import (
    AgentDecision,
    LoanAssessmentState,
    WorkflowStatus,
)

logger = get_logger(__name__)

# ── Node instances (shared across requests) ──
_doc_verifier = DocumentVerifierNode()
_credit_assessor = CreditAssessmentNode()
_fraud_screener = FraudScreeningNode()
_risk_scorer = RiskScoringNode()
_human_escalator = HumanEscalationNode()
_response_synthesizer = ResponseSynthesisNode()


# ── Conditional routing functions ─────────────

def route_after_risk(state: LoanAssessmentState) -> Literal["response_synthesizer", "human_escalator"]:
    """Route based on risk score and confidence."""
    confidence = state.get("confidence_score", 0.5)
    decision = state.get("final_decision")
    fraud_risk = state.get("fraud_risk_score", 0.0)

    # Escalate if:
    # - confidence too low
    # - fraud risk is high
    # - decision is ESCALATE
    if (
        confidence < settings.orchestration.escalation_threshold
        or fraud_risk >= 0.7
        or decision == AgentDecision.ESCALATE
    ):
        return "human_escalator"
    return "response_synthesizer"


def route_after_doc_verify(state: LoanAssessmentState) -> Literal["parallel_assessment", "human_escalator"]:
    """Skip parallel assessment if docs are completely invalid."""
    if not state.get("is_valid") and state.get("document_completeness_score", 1.0) < 0.3:
        return "human_escalator"
    return "parallel_assessment"


# ── Graph builder ────────────────────────────

def build_loan_assessment_graph() -> CompiledGraph:
    """Build and compile the loan assessment StateGraph."""

    graph = StateGraph(LoanAssessmentState)

    # ── Register nodes ────────────────────────
    graph.add_node("document_verifier", _doc_verifier)
    graph.add_node("credit_assessor", _credit_assessor)
    graph.add_node("fraud_screener", _fraud_screener)
    graph.add_node("risk_scorer", _risk_scorer)
    graph.add_node("human_escalator", _human_escalator)
    graph.add_node("response_synthesizer", _response_synthesizer)

    # ── Edges ────────────────────────────────
    graph.add_edge(START, "document_verifier")

    # Parallel execution: credit + fraud run simultaneously after doc verify
    graph.add_edge("document_verifier", "credit_assessor")
    graph.add_edge("document_verifier", "fraud_screener")

    # Both parallel branches converge at risk_scorer
    graph.add_edge("credit_assessor", "risk_scorer")
    graph.add_edge("fraud_screener", "risk_scorer")

    # Conditional routing after risk scoring
    graph.add_conditional_edges(
        "risk_scorer",
        route_after_risk,
        {
            "response_synthesizer": "response_synthesizer",
            "human_escalator": "human_escalator",
        },
    )

    graph.add_edge("response_synthesizer", END)
    graph.add_edge("human_escalator", END)

    return graph.compile()


# ── Compiled graph singleton ─────────────────
_loan_graph: CompiledGraph = None


def get_loan_assessment_graph() -> CompiledGraph:
    global _loan_graph
    if _loan_graph is None:
        _loan_graph = build_loan_assessment_graph()
        logger.info("loan_assessment_graph.compiled")
    return _loan_graph


# ── State initializer ────────────────────────

def create_loan_state(
    loan_application_id: str,
    user_id: str,
    loan_data: Dict[str, Any],
    session_id: str = None,
) -> LoanAssessmentState:
    """Build initial state for a loan assessment run."""
    return LoanAssessmentState(
        run_id=str(uuid.uuid4()),
        workflow_name="loan_assessment",
        session_id=session_id,
        user_id=user_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        status=WorkflowStatus.PENDING,
        current_node="",
        completed_nodes=[],
        iteration_count=0,
        messages=[],
        error=None,
        error_node=None,
        retry_count=0,
        fallback_triggered=False,
        confidence_score=0.5,
        final_decision=None,
        decision_reason=None,
        escalation_reason=None,
        trace=[],
        latency_ms={},
        token_usage={},
        output=None,
        streaming_buffer=[],
        input_guardrail_passed=True,
        output_guardrail_passed=True,
        guardrail_violations=[],
        # Loan-specific
        loan_application_id=loan_application_id,
        loan_type=loan_data.get("loan_type", "personal"),
        requested_amount=float(loan_data.get("requested_amount", 0)),
        requested_tenure_months=int(loan_data.get("requested_tenure_months", 12)),
        currency=loan_data.get("currency", "INR"),
        applicant_name=loan_data.get("applicant_name", ""),
        applicant_email=loan_data.get("applicant_email", ""),
        employment_type=loan_data.get("employment_type", "salaried"),
        monthly_income=float(loan_data.get("monthly_income", 0)),
        annual_income=float(loan_data.get("annual_income", 0)),
        existing_emi=float(loan_data.get("existing_emi", 0)),
        credit_score=loan_data.get("credit_score"),
        document_types_present=loan_data.get("document_types", []),
        missing_documents=[],
        document_confidence=0.8,
        documents_verified=False,
        retrieved_policies=[],
        policy_context="",
        conditions=[],
        credit_risk_score=0.5,
        income_adequacy_score=0.5,
        document_completeness_score=0.8,
        fraud_risk_score=0.3,
        overall_risk_level=None,
    )
