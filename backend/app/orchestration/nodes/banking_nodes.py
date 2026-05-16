"""
Banking Workflow Nodes
========================
Core nodes used across banking workflows.

Nodes:
  - IntentClassifierNode  : Classify user intent and route to sub-graph
  - DocumentVerifierNode  : Verify uploaded documents via LLM + RAG
  - CreditAssessmentNode  : Assess creditworthiness from applicant profile
  - FraudScreeningNode    : Screen for fraud indicators
  - RiskScoringNode       : Compute aggregate risk score
  - HumanEscalationNode   : Route to human reviewer when confidence is low
  - ResponseSynthesisNode : Generate final structured response
"""

import json
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.orchestration.nodes.base_node import BaseNode
from app.orchestration.states.graph_states import AgentDecision, RiskLevel, WorkflowStatus

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Intent Classifier
# ──────────────────────────────────────────────

class IntentClassifierNode(BaseNode):
    """
    Classifies incoming requests and routes to the correct sub-graph.
    Outputs: intent, intent_confidence, intent_params
    """

    name = "intent_classifier"
    description = "Classify user intent for workflow routing"

    VALID_INTENTS = [
        "loan_assessment", "fraud_detection",
        "document_verification", "customer_support",
        "account_inquiry", "general_query",
    ]

    SYSTEM_PROMPT = """You are an intent classifier for an enterprise banking AI platform.
Classify the user's request into exactly one of these intents:
- loan_assessment: User wants to apply for or inquire about a loan
- fraud_detection: Suspected fraud or suspicious activity needs investigation
- document_verification: Document needs to be verified or reviewed
- customer_support: General customer support, account questions, complaints
- account_inquiry: Questions about account balance, transactions, statements
- general_query: General banking information or guidance

Respond ONLY with valid JSON matching this schema:
{
  "intent": "<one of the valid intents>",
  "confidence": <float 0.0-1.0>,
  "params": {<extracted parameters relevant to the intent>},
  "reasoning": "<brief explanation>"
}"""

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = self._extract_query(state) or ""

        response_text, tok_in, tok_out = await self.invoke_llm(
            system_prompt=self.SYSTEM_PROMPT,
            human_message=f"Classify this request:\n\n{query}",
        )

        try:
            result = json.loads(response_text.strip())
            intent = result.get("intent", "general_query")
            confidence = float(result.get("confidence", 0.5))
            params = result.get("params", {})
        except (json.JSONDecodeError, ValueError):
            intent = "general_query"
            confidence = 0.4
            params = {}

        logger.info(
            "intent_classifier.result",
            intent=intent,
            confidence=confidence,
        )

        return {
            "intent": intent,
            "intent_confidence": confidence,
            "intent_params": params,
            "confidence_score": confidence,
            "status": WorkflowStatus.RUNNING,
            "token_usage": {**state.get("token_usage", {}), self.name: tok_in + tok_out},
        }


# ──────────────────────────────────────────────
# Document Verifier Node
# ──────────────────────────────────────────────

class DocumentVerifierNode(BaseNode):
    """
    Uses LLM + RAG context to verify document authenticity and completeness.
    """

    name = "document_verifier"
    description = "Verify document authenticity and extract key fields"

    SYSTEM_PROMPT = """You are a document verification expert for a banking platform.
Analyze the extracted text from the document and verify:
1. Format validity (correct patterns for document type)
2. Required fields presence and completeness
3. Consistency of information
4. Signs of tampering or inconsistency

Respond ONLY with valid JSON:
{
  "is_valid": <boolean>,
  "is_authentic": <boolean>,
  "confidence": <float 0.0-1.0>,
  "fields_verified": {<field_name>: <extracted_value>},
  "missing_fields": [<list of missing required fields>],
  "issues": [<list of issues found>],
  "recommendation": "approve|reject|manual_review"
}"""

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        doc_type = state.get("document_type", "unknown")
        ocr_text = state.get("ocr_text", "")
        extracted = state.get("extracted_fields", {})
        context = state.get("verification_guidelines", "")

        human_msg = f"""Document Type: {doc_type}

Verification Guidelines:
{context[:2000] if context else 'Apply standard verification rules.'}

Extracted OCR Text:
{ocr_text[:3000]}

Previously Extracted Fields:
{json.dumps(extracted, indent=2)[:1000]}

Verify this document."""

        response_text, tok_in, tok_out = await self.invoke_llm(
            system_prompt=self.SYSTEM_PROMPT,
            human_message=human_msg,
        )

        try:
            result = json.loads(response_text.strip())
        except json.JSONDecodeError:
            result = {
                "is_valid": False,
                "is_authentic": False,
                "confidence": 0.3,
                "issues": ["Could not parse verification result"],
                "recommendation": "manual_review",
            }

        confidence = float(result.get("confidence", 0.5))
        decision = (
            AgentDecision.APPROVE if result.get("recommendation") == "approve"
            else AgentDecision.REJECT if result.get("recommendation") == "reject"
            else AgentDecision.ESCALATE
        )

        return {
            "format_check": result,
            "is_valid": result.get("is_valid", False),
            "is_authentic": result.get("is_authentic", False),
            "rejection_reasons": result.get("issues", []),
            "verification_notes": json.dumps(result.get("fields_verified", {})),
            "confidence_score": confidence,
            "final_decision": decision,
            "token_usage": {**state.get("token_usage", {}), self.name: tok_in + tok_out},
        }


# ──────────────────────────────────────────────
# Credit Assessment Node
# ──────────────────────────────────────────────

class CreditAssessmentNode(BaseNode):
    """
    Assesses creditworthiness using applicant profile + retrieved loan policies.
    Outputs structured credit assessment with scores.
    """

    name = "credit_assessor"
    description = "Assess applicant creditworthiness using financial profile and policies"

    SYSTEM_PROMPT = """You are a senior credit analyst at a banking institution.
Assess the loan applicant's creditworthiness based on their financial profile
and the retrieved lending policies.

Evaluate:
1. Income adequacy (EMI-to-income ratio should be < 50%)
2. Credit score interpretation
3. Debt burden analysis
4. Employment stability
5. Loan purpose appropriateness

Respond ONLY with valid JSON:
{
  "income_adequacy_score": <float 0.0-1.0>,
  "credit_risk_score": <float 0.0-1.0, higher=riskier>,
  "debt_burden_assessment": "low|medium|high|very_high",
  "employment_stability": "stable|moderate|unstable",
  "recommended_amount": <float or null>,
  "recommended_tenure_months": <int or null>,
  "recommended_interest_rate": <float or null>,
  "emi_calculated": <float or null>,
  "conditions": [<list of approval conditions>],
  "confidence": <float 0.0-1.0>,
  "assessment_summary": "<brief summary>",
  "recommendation": "approve|conditional_approve|reject"
}"""

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        profile = {
            "loan_type": state.get("loan_type"),
            "requested_amount": state.get("requested_amount"),
            "requested_tenure_months": state.get("requested_tenure_months"),
            "employment_type": state.get("employment_type"),
            "monthly_income": state.get("monthly_income"),
            "annual_income": state.get("annual_income"),
            "existing_emi": state.get("existing_emi", 0),
            "credit_score": state.get("credit_score"),
            "debt_to_income": state.get("debt_to_income_ratio"),
            "extracted_income": state.get("extracted_income"),
        }

        policy_context = state.get("policy_context", "Apply standard lending criteria.")

        human_msg = f"""Lending Policies:
{policy_context[:3000]}

Applicant Financial Profile:
{json.dumps(profile, indent=2)}

Provide credit assessment."""

        response_text, tok_in, tok_out = await self.invoke_llm(
            system_prompt=self.SYSTEM_PROMPT,
            human_message=human_msg,
        )

        try:
            result = json.loads(response_text.strip())
        except json.JSONDecodeError:
            result = {
                "credit_risk_score": 0.5,
                "income_adequacy_score": 0.5,
                "confidence": 0.3,
                "recommendation": "reject",
                "assessment_summary": "Could not complete assessment",
                "conditions": [],
            }

        confidence = float(result.get("confidence", 0.5))
        rec = result.get("recommendation", "reject")
        decision = (
            AgentDecision.APPROVE if rec == "approve"
            else AgentDecision.PASS if rec == "conditional_approve"
            else AgentDecision.REJECT
        )

        return {
            "credit_assessment": result,
            "credit_risk_score": float(result.get("credit_risk_score", 0.5)),
            "income_adequacy_score": float(result.get("income_adequacy_score", 0.5)),
            "recommended_amount": result.get("recommended_amount"),
            "recommended_tenure_months": result.get("recommended_tenure_months"),
            "recommended_interest_rate": result.get("recommended_interest_rate"),
            "emi_calculated": result.get("emi_calculated"),
            "conditions": result.get("conditions", []),
            "confidence_score": confidence,
            "final_decision": decision,
            "decision_reason": result.get("assessment_summary", ""),
            "token_usage": {**state.get("token_usage", {}), self.name: tok_in + tok_out},
        }


# ──────────────────────────────────────────────
# Fraud Screening Node
# ──────────────────────────────────────────────

class FraudScreeningNode(BaseNode):
    """
    Screens loan applications and transactions for fraud indicators.
    Uses retrieved fraud patterns from RAG.
    """

    name = "fraud_screener"
    description = "Screen for fraud indicators using patterns and behavioral analysis"

    SYSTEM_PROMPT = """You are a fraud detection specialist at a banking institution.
Screen the provided information for fraud indicators based on known patterns.

Analyze:
1. Identity consistency across documents
2. Income verification plausibility
3. Application pattern anomalies
4. Known fraud indicators from patterns database
5. AML (Anti-Money Laundering) red flags

Respond ONLY with valid JSON:
{
  "fraud_risk_score": <float 0.0-1.0, higher=riskier>,
  "risk_level": "low|medium|high|critical",
  "fraud_indicators": [<list of detected indicators>],
  "aml_flags": [<list of AML concerns>],
  "recommended_action": "clear|monitor|flag|block",
  "report_required": <boolean>,
  "confidence": <float 0.0-1.0>,
  "summary": "<brief fraud assessment>"
}"""

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        context_data = {
            "user_id": state.get("user_id"),
            "loan_type": state.get("loan_type"),
            "requested_amount": state.get("requested_amount"),
            "employment_type": state.get("employment_type"),
            "monthly_income": state.get("monthly_income"),
            "documents_verified": state.get("documents_verified"),
            "document_types": state.get("document_types_present", []),
            "credit_score": state.get("credit_score"),
        }

        fraud_patterns = state.get("matching_fraud_patterns", [])
        patterns_text = json.dumps(fraud_patterns[:5], indent=2) if fraud_patterns else "None found"

        human_msg = f"""Known Fraud Patterns from Database:
{patterns_text}

Application Data:
{json.dumps(context_data, indent=2)}

Screen for fraud indicators."""

        response_text, tok_in, tok_out = await self.invoke_llm(
            system_prompt=self.SYSTEM_PROMPT,
            human_message=human_msg,
        )

        try:
            result = json.loads(response_text.strip())
        except json.JSONDecodeError:
            result = {
                "fraud_risk_score": 0.3,
                "risk_level": "low",
                "fraud_indicators": [],
                "aml_flags": [],
                "recommended_action": "monitor",
                "report_required": False,
                "confidence": 0.4,
                "summary": "Could not complete fraud screening",
            }

        risk_level_map = {
            "low": RiskLevel.LOW,
            "medium": RiskLevel.MEDIUM,
            "high": RiskLevel.HIGH,
            "critical": RiskLevel.CRITICAL,
        }

        return {
            "fraud_screening": result,
            "fraud_risk_score": float(result.get("fraud_risk_score", 0.3)),
            "overall_risk_level": risk_level_map.get(result.get("risk_level", "low"), RiskLevel.LOW),
            "fraud_indicators": result.get("fraud_indicators", []),
            "aml_flags": result.get("aml_flags", []),
            "report_required": result.get("report_required", False),
            "confidence_score": float(result.get("confidence", 0.5)),
            "token_usage": {**state.get("token_usage", {}), self.name: tok_in + tok_out},
        }


# ──────────────────────────────────────────────
# Risk Scoring Node (aggregator)
# ──────────────────────────────────────────────

class RiskScoringNode(BaseNode):
    """
    Aggregates all agent assessments into a final risk score and decision.
    Pure computation — no LLM call needed.
    """

    name = "risk_scorer"
    description = "Aggregate all agent scores into final risk decision"
    use_guardrails = False

    WEIGHTS = {
        "credit_risk_score": 0.35,
        "fraud_risk_score": 0.30,
        "income_adequacy_score": 0.20,
        "document_completeness_score": 0.15,
    }

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        credit_risk = state.get("credit_risk_score", 0.5)
        fraud_risk = state.get("fraud_risk_score", 0.3)
        income_score = state.get("income_adequacy_score", 0.5)
        doc_score = state.get("document_completeness_score", 0.8)

        # Weighted aggregate risk (higher = riskier)
        aggregate_risk = (
            credit_risk * self.WEIGHTS["credit_risk_score"]
            + fraud_risk * self.WEIGHTS["fraud_risk_score"]
            + (1 - income_score) * self.WEIGHTS["income_adequacy_score"]
            + (1 - doc_score) * self.WEIGHTS["document_completeness_score"]
        )

        # Determine risk level
        if aggregate_risk < 0.25:
            risk_level = RiskLevel.LOW
        elif aggregate_risk < 0.50:
            risk_level = RiskLevel.MEDIUM
        elif aggregate_risk < 0.75:
            risk_level = RiskLevel.HIGH
        else:
            risk_level = RiskLevel.CRITICAL

        # Determine decision
        fraud_risk_f = float(fraud_risk)
        if fraud_risk_f >= 0.7 or risk_level == RiskLevel.CRITICAL:
            decision = AgentDecision.REJECT
            reason = "High fraud/credit risk score."
        elif aggregate_risk < 0.35 and income_score >= 0.6:
            decision = AgentDecision.APPROVE
            reason = "Risk profile within acceptable range."
        elif aggregate_risk < 0.55:
            decision = AgentDecision.PASS  # Conditional — needs conditions
            reason = "Moderate risk — conditional approval with requirements."
        else:
            decision = AgentDecision.ESCALATE
            reason = "Risk profile requires human review."

        # Confidence = inverse of risk uncertainty
        confidence = round(1 - abs(aggregate_risk - 0.5) * 0.5, 3)

        logger.info(
            "risk_scorer.result",
            aggregate_risk=round(aggregate_risk, 3),
            risk_level=risk_level,
            decision=decision,
            confidence=confidence,
        )

        return {
            "risk_assessment": {
                "aggregate_risk": round(aggregate_risk, 4),
                "weights": self.WEIGHTS,
                "component_scores": {
                    "credit_risk": credit_risk,
                    "fraud_risk": fraud_risk,
                    "income_adequacy": income_score,
                    "document_completeness": doc_score,
                },
            },
            "overall_risk_level": risk_level,
            "confidence_score": confidence,
            "final_decision": decision,
            "decision_reason": reason,
        }


# ──────────────────────────────────────────────
# Human Escalation Node
# ──────────────────────────────────────────────

class HumanEscalationNode(BaseNode):
    """
    Routes to human reviewer when confidence is below threshold.
    Creates an alert in the DB for staff attention.
    """

    name = "human_escalator"
    description = "Escalate to human reviewer when AI confidence is insufficient"
    use_guardrails = False

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        reason = state.get("escalation_reason") or (
            f"Confidence score {state.get('confidence_score', 0):.2f} "
            f"below threshold {settings.orchestration.escalation_threshold}"
        )

        logger.warning(
            "escalation.triggered",
            run_id=state.get("run_id"),
            reason=reason,
            confidence=state.get("confidence_score"),
        )

        return {
            "status": WorkflowStatus.AWAITING_HUMAN,
            "final_decision": AgentDecision.ESCALATE,
            "escalation_reason": reason,
            "output": {
                "escalated": True,
                "reason": reason,
                "message": (
                    "This application requires human review. "
                    "A banking specialist will contact you within 2 business days."
                ),
            },
        }


# ──────────────────────────────────────────────
# Response Synthesis Node
# ──────────────────────────────────────────────

class ResponseSynthesisNode(BaseNode):
    """
    Synthesizes all agent outputs into a clear, structured final response.
    Used as the terminal node in most workflows.
    """

    name = "response_synthesizer"
    description = "Synthesize agent outputs into final structured response"

    SYSTEM_PROMPT = """You are a professional banking assistant synthesizing a final response.
Create a clear, accurate, and professional response based on the assessment results.

Guidelines:
- Be factual and cite specific findings
- Use clear language appropriate for banking customers
- If approved: state conditions clearly
- If rejected: be respectful and provide actionable guidance
- If escalated: reassure the customer and explain next steps
- Keep response under 400 words"""

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        decision = state.get("final_decision")
        reason = state.get("decision_reason", "")
        conditions = state.get("conditions", [])
        risk_level = state.get("overall_risk_level", "medium")

        context = f"""Decision: {decision}
Reason: {reason}
Risk Level: {risk_level}
Conditions: {', '.join(conditions) if conditions else 'None'}
Recommended Amount: {state.get('recommended_amount', 'N/A')}
Recommended Rate: {state.get('recommended_interest_rate', 'N/A')}%
EMI: {state.get('emi_calculated', 'N/A')}"""

        query = self._extract_query(state) or "Loan application assessment"

        response_text, tok_in, tok_out = await self.invoke_llm(
            system_prompt=self.SYSTEM_PROMPT,
            human_message=f"Original request:\n{query}\n\nAssessment results:\n{context}",
        )

        return {
            "final_response": response_text,
            "status": WorkflowStatus.COMPLETED,
            "output": {
                "decision": str(decision),
                "response": response_text,
                "risk_level": str(risk_level),
                "conditions": conditions,
                "recommended_amount": state.get("recommended_amount"),
                "recommended_rate": state.get("recommended_interest_rate"),
                "emi": state.get("emi_calculated"),
            },
            "token_usage": {**state.get("token_usage", {}), self.name: tok_in + tok_out},
        }
