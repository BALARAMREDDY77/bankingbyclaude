"""
Agent Service
==============
Orchestrates multi-agent pipelines for complex banking workflows.

Pipelines:
  - full_loan_pipeline     : KYC → Transaction → Risk → Report
  - fraud_investigation    : Fraud → Risk → Report
  - kyc_onboarding         : KYC → Report
  - customer_query         : Support (standalone)
  - custom                 : Single agent run
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.fraud.fraud_agent import FraudDetectionAgent
from app.agents.kyc.kyc_agent import KYCVerificationAgent
from app.agents.reporting.report_agent import ReportGenerationAgent
from app.agents.risk.risk_agent import RiskScoringAgent
from app.agents.support.support_agent import CustomerSupportAgent
from app.agents.transaction.transaction_agent import TransactionAnalysisAgent
from app.core.logging import get_logger

logger = get_logger(__name__)

AGENT_REGISTRY = {
    "kyc": KYCVerificationAgent,
    "fraud": FraudDetectionAgent,
    "transaction": TransactionAnalysisAgent,
    "risk": RiskScoringAgent,
    "support": CustomerSupportAgent,
    "report": ReportGenerationAgent,
}


class AgentService:
    """Orchestrates single and multi-agent pipelines."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _agent(self, name: str):
        cls = AGENT_REGISTRY.get(name)
        if not cls:
            raise ValueError(f"Unknown agent: '{name}'")
        return cls(session=self.session)

    # ──────────────────────────────────────────
    # Single Agent Run
    # ──────────────────────────────────────────

    async def run_agent(
        self,
        agent_name: str,
        input_data: Dict[str, Any],
        run_id: Optional[str] = None,
        language: str = "en",
    ) -> Dict[str, Any]:
        """Run a single named agent and return its output as dict."""
        run_id = run_id or str(uuid.uuid4())
        agent = self._agent(agent_name)
        result = await agent.run(input_data, run_id=run_id, language=language)
        return result.model_dump()

    # ──────────────────────────────────────────
    # Full Loan Pipeline
    # ──────────────────────────────────────────

    async def run_full_loan_pipeline(
        self,
        input_data: Dict[str, Any],
        language: str = "en",
    ) -> Dict[str, Any]:
        """
        Full loan assessment pipeline:
        KYC → Transaction Analysis → Risk Scoring → Report Generation
        """
        pipeline_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        results: Dict[str, Any] = {"pipeline_id": pipeline_id, "started_at": started_at}

        logger.info("pipeline.loan.started", pipeline_id=pipeline_id)

        # ── Step 1: KYC ──────────────────────
        kyc_result = await self._agent("kyc").run(input_data, run_id=f"{pipeline_id}_kyc", language=language)
        results["kyc"] = kyc_result.model_dump()
        logger.info("pipeline.kyc_complete", confidence=kyc_result.confidence, decision=str(kyc_result.decision))

        # ── Step 2: Transaction Analysis ─────
        tx_result = await self._agent("transaction").run(input_data, run_id=f"{pipeline_id}_tx", language=language)
        results["transaction"] = tx_result.model_dump()
        logger.info("pipeline.transaction_complete", signal=tx_result.creditworthiness_signal)

        # ── Step 3: Risk Scoring ──────────────
        risk_input = {
            **input_data,
            "kyc_result": kyc_result.model_dump(),
            "transaction_result": tx_result.model_dump(),
        }
        risk_result = await self._agent("risk").run(risk_input, run_id=f"{pipeline_id}_risk", language=language)
        results["risk"] = risk_result.model_dump()
        logger.info("pipeline.risk_complete", composite=risk_result.composite_risk_score, eligible=risk_result.loan_eligible)

        # ── Step 4: Report Generation ─────────
        report_input = {
            "report_type": "credit_assessment",
            "report_period": datetime.now(timezone.utc).strftime("%B %Y"),
            "generated_for": input_data.get("name", "Applicant"),
            "confidentiality_level": "confidential",
            "data_inputs": input_data,
            "agent_outputs": {
                "kyc": results["kyc"],
                "transaction": results["transaction"],
                "risk": results["risk"],
            },
        }
        report_result = await self._agent("report").run(report_input, run_id=f"{pipeline_id}_report", language=language)
        results["report"] = report_result.model_dump()

        # ── Summary ───────────────────────────
        results["pipeline_summary"] = {
            "pipeline_id": pipeline_id,
            "loan_eligible": risk_result.loan_eligible,
            "composite_risk_score": risk_result.composite_risk_score,
            "kyc_verified": kyc_result.identity_verified,
            "creditworthiness_signal": tx_result.creditworthiness_signal,
            "final_decision": str(risk_result.decision),
            "max_eligible_amount": risk_result.max_eligible_amount,
            "recommended_rate": risk_result.recommended_interest_rate,
            "escalation_required": any([
                kyc_result.escalation_required,
                risk_result.escalation_required,
            ]),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("pipeline.loan.completed", pipeline_id=pipeline_id,
                    eligible=risk_result.loan_eligible, decision=str(risk_result.decision))
        return results

    # ──────────────────────────────────────────
    # Fraud Investigation Pipeline
    # ──────────────────────────────────────────

    async def run_fraud_investigation(
        self,
        input_data: Dict[str, Any],
        language: str = "en",
    ) -> Dict[str, Any]:
        """Fraud Detection → Risk → Report pipeline."""
        pipeline_id = str(uuid.uuid4())
        results: Dict[str, Any] = {"pipeline_id": pipeline_id}

        fraud_result = await self._agent("fraud").run(input_data, run_id=f"{pipeline_id}_fraud", language=language)
        results["fraud"] = fraud_result.model_dump()

        risk_input = {**input_data, "fraud_result": fraud_result.model_dump()}
        risk_result = await self._agent("risk").run(risk_input, run_id=f"{pipeline_id}_risk", language=language)
        results["risk"] = risk_result.model_dump()

        report_input = {
            "report_type": "fraud_investigation",
            "report_period": datetime.now(timezone.utc).strftime("%B %Y"),
            "confidentiality_level": "restricted",
            "data_inputs": input_data,
            "agent_outputs": {"fraud": results["fraud"], "risk": results["risk"]},
        }
        report_result = await self._agent("report").run(report_input, run_id=f"{pipeline_id}_report")
        results["report"] = report_result.model_dump()

        results["pipeline_summary"] = {
            "is_fraudulent": fraud_result.is_fraudulent,
            "fraud_score": fraud_result.fraud_score,
            "recommended_action": fraud_result.recommended_action,
            "block_account": fraud_result.block_account,
            "report_to_fiu": fraud_result.report_to_fiu,
            "escalation_required": fraud_result.escalation_required,
        }
        logger.info("pipeline.fraud.completed", pipeline_id=pipeline_id,
                    is_fraud=fraud_result.is_fraudulent, action=fraud_result.recommended_action)
        return results

    # ──────────────────────────────────────────
    # KYC Onboarding Pipeline
    # ──────────────────────────────────────────

    async def run_kyc_onboarding(
        self,
        input_data: Dict[str, Any],
        language: str = "en",
    ) -> Dict[str, Any]:
        """KYC Verification → Report."""
        pipeline_id = str(uuid.uuid4())
        kyc_result = await self._agent("kyc").run(input_data, run_id=f"{pipeline_id}_kyc", language=language)

        report_input = {
            "report_type": "kyc_summary",
            "generated_for": input_data.get("name", "Customer"),
            "confidentiality_level": "confidential",
            "data_inputs": input_data,
            "agent_outputs": {"kyc": kyc_result.model_dump()},
        }
        report_result = await self._agent("report").run(report_input, run_id=f"{pipeline_id}_report")

        return {
            "pipeline_id": pipeline_id,
            "kyc": kyc_result.model_dump(),
            "report": report_result.model_dump(),
            "pipeline_summary": {
                "identity_verified": kyc_result.identity_verified,
                "kyc_level": kyc_result.kyc_level,
                "decision": str(kyc_result.decision),
                "missing_documents": kyc_result.missing_documents,
                "escalation_required": kyc_result.escalation_required,
            },
        }
