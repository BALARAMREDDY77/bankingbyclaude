"""
Risk Scoring Agent
====================
Aggregates KYC, fraud, transaction, and credit signals
into a composite risk score with loan eligibility decision.
"""

import json
from typing import Any, Dict

from app.agents.shared.base_agent import BaseAgent
from app.agents.shared.prompts.templates import RISK_SYSTEM_PROMPT, RISK_HUMAN_TEMPLATE, build_prompt
from app.agents.shared.schemas.outputs import (
    AgentDecisionEnum, RiskAgentOutput, RiskFactor, RiskLevelEnum,
)
from app.agents.shared.tools.banking_tools import calculate_emi, get_credit_bureau_report
from app.core.logging import get_logger

logger = get_logger(__name__)


class RiskScoringAgent(BaseAgent):
    agent_name = "risk_scoring_agent"
    system_prompt = RISK_SYSTEM_PROMPT

    async def build_context(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        user_id = input_data.get("user_id", "")
        pan = input_data.get("pan_number", "")
        name = input_data.get("name", "")
        requested_amount = float(input_data.get("requested_amount", 0))
        loan_type = input_data.get("loan_type", "personal")
        currency = input_data.get("currency", "INR")

        # Credit bureau
        credit_report = {}
        if pan:
            credit_report = await get_credit_bureau_report(pan, name)

        # EMI calculation (assume 10.5% rate, requested tenure)
        emi_data = {}
        if requested_amount > 0:
            tenure = int(input_data.get("requested_tenure_months", 36))
            emi_data = calculate_emi(requested_amount, 10.5, tenure)

        credit_profile = {
            **credit_report,
            "monthly_income": input_data.get("monthly_income", 0),
            "existing_emi": input_data.get("existing_emi", 0),
            "employment_type": input_data.get("employment_type", "salaried"),
            "estimated_emi": emi_data.get("emi", 0),
            "emi_to_income_ratio": (
                (emi_data.get("emi", 0) + float(input_data.get("existing_emi", 0)))
                / max(float(input_data.get("monthly_income", 1)), 1)
            ),
        }

        # RAG — risk policy
        risk_policy_context = ""
        if self.session:
            try:
                from app.rag.services.hybrid_retrieval import HybridRetrievalService
                svc = HybridRetrievalService(self.session)
                results, _ = await svc.retrieve(
                    query=f"credit risk scoring {loan_type} loan eligibility RBI guidelines",
                    knowledge_base="loan_underwriting", top_k=4,
                )
                risk_policy_context = "\n".join(r.chunk_text for r in results)
            except Exception:
                risk_policy_context = "Apply standard RBI lending guidelines."

        return {
            "user_id": user_id,
            "loan_application_id": input_data.get("loan_application_id", ""),
            "loan_type": loan_type,
            "requested_amount": requested_amount,
            "currency": currency,
            "credit_profile_json": json.dumps(credit_profile, indent=2),
            "kyc_result_json": json.dumps(input_data.get("kyc_result", {}), indent=2)[:1000],
            "fraud_result_json": json.dumps(input_data.get("fraud_result", {}), indent=2)[:1000],
            "transaction_result_json": json.dumps(input_data.get("transaction_result", {}), indent=2)[:1000],
            "risk_policy_context": risk_policy_context[:2500],
        }

    def build_prompt(self, context: Dict[str, Any]) -> str:
        return build_prompt(RISK_HUMAN_TEMPLATE, context)

    def parse_output(self, raw: str, run_id: str) -> RiskAgentOutput:
        data = self._parse_json_output(raw)
        factors = [
            RiskFactor(
                factor_name=f.get("factor_name", ""),
                weight=float(f.get("weight", 0)),
                raw_score=float(f.get("raw_score", 0)),
                weighted_score=float(f.get("weighted_score", 0)),
                description=f.get("description", ""),
            )
            for f in data.get("risk_factors", [])
        ]
        confidence = float(data.get("confidence", 0.6))
        composite = float(data.get("composite_risk_score", 0.5))
        return RiskAgentOutput(
            run_id=run_id,
            decision=AgentDecisionEnum(data.get("decision", "review")),
            confidence=confidence,
            risk_level=RiskLevelEnum(data.get("risk_level", "medium")),
            reasoning=data.get("reasoning", ""),
            key_factors=data.get("key_factors", []),
            escalation_required=data.get("escalation_required", composite > 0.6),
            escalation_reason=data.get("escalation_reason"),
            warnings=data.get("warnings", []),
            composite_risk_score=composite,
            credit_risk_score=float(data.get("credit_risk_score", 0.5)),
            fraud_risk_score=float(data.get("fraud_risk_score", 0.3)),
            operational_risk_score=float(data.get("operational_risk_score", 0.2)),
            market_risk_score=float(data.get("market_risk_score", 0.1)),
            risk_factors=factors,
            recommended_credit_limit=data.get("recommended_credit_limit"),
            recommended_interest_rate=data.get("recommended_interest_rate"),
            loan_eligible=data.get("loan_eligible", composite < 0.5),
            max_eligible_amount=data.get("max_eligible_amount"),
            risk_mitigation_suggestions=data.get("risk_mitigation_suggestions", []),
            review_period_days=int(data.get("review_period_days", 90)),
        )

    def _error_output(self, run_id: str, error: str, elapsed: float) -> RiskAgentOutput:
        return RiskAgentOutput(
            run_id=run_id, decision=AgentDecisionEnum.ESCALATE,
            confidence=0.0, risk_level=RiskLevelEnum.HIGH,
            reasoning=f"Agent error: {error}", key_factors=["System error"],
            escalation_required=True, escalation_reason=error,
            composite_risk_score=0.8, credit_risk_score=0.8,
            fraud_risk_score=0.5, operational_risk_score=0.5,
            market_risk_score=0.3, risk_factors=[],
            loan_eligible=False, risk_mitigation_suggestions=[],
            warnings=[error], processing_time_ms=int(elapsed * 1000),
        )
