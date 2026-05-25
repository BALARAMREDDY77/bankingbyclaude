"""
Fraud Detection Agent
======================
Detects fraud using transaction patterns, behavioral signals,
RAG-retrieved fraud patterns, and mock AML rules.
"""

import json
from typing import Any, Dict

from app.agents.shared.base_agent import BaseAgent
from app.agents.shared.prompts.templates import FRAUD_SYSTEM_PROMPT, FRAUD_HUMAN_TEMPLATE, build_prompt
from app.agents.shared.schemas.outputs import (
    AgentDecisionEnum, FraudAgentOutput, FraudIndicator, RiskLevelEnum,
)
from app.agents.shared.tools.banking_tools import (
    check_sanctions_list, get_fraud_case_history, get_transaction_history,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class FraudDetectionAgent(BaseAgent):
    agent_name = "fraud_detection_agent"
    system_prompt = FRAUD_SYSTEM_PROMPT

    async def build_context(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        import asyncio
        user_id = input_data.get("user_id", "")
        transaction_data = input_data.get("transaction_data", {})
        behavioral_context = input_data.get("behavioral_context", {})

        # Fetch tools concurrently
        tx_history, fraud_history, sanctions = await asyncio.gather(
            get_transaction_history(user_id, months=3) if user_id else asyncio.coroutine(lambda: {})(),
            get_fraud_case_history(user_id) if user_id else asyncio.coroutine(lambda: {})(),
            check_sanctions_list(input_data.get("name", ""), input_data.get("pan")) if input_data.get("name") else asyncio.coroutine(lambda: {})(),
        )

        # Merge transaction data
        combined_tx = {**transaction_data, "history_summary": tx_history}
        combined_behavioral = {**behavioral_context, "fraud_history": fraud_history, "sanctions": sanctions}

        # RAG — retrieve fraud patterns
        fraud_patterns_context, aml_context = "", ""
        if self.session:
            try:
                from app.rag.services.hybrid_retrieval import HybridRetrievalService
                svc = HybridRetrievalService(self.session)
                fraud_r, _ = await svc.retrieve(
                    query=f"fraud detection patterns banking {input_data.get('event_type', 'transaction')}",
                    knowledge_base="fraud_detection", top_k=4,
                )
                aml_r, _ = await svc.retrieve(
                    query="AML anti money laundering rules India PMLA",
                    knowledge_base="regulatory", top_k=3,
                )
                fraud_patterns_context = "\n".join(r.chunk_text for r in fraud_r)
                aml_context = "\n".join(r.chunk_text for r in aml_r)
            except Exception:
                fraud_patterns_context = "Apply standard fraud detection heuristics."
                aml_context = "Apply PMLA 2002 AML guidelines."

        return {
            "user_id": user_id,
            "subject_id": input_data.get("subject_id", ""),
            "event_type": input_data.get("event_type", "transaction"),
            "transaction_data_json": json.dumps(combined_tx, indent=2)[:3000],
            "behavioral_context_json": json.dumps(combined_behavioral, indent=2)[:2000],
            "fraud_patterns_context": fraud_patterns_context[:2000],
            "aml_context": aml_context[:1500],
        }

    def build_prompt(self, context: Dict[str, Any]) -> str:
        return build_prompt(FRAUD_HUMAN_TEMPLATE, context)

    def parse_output(self, raw: str, run_id: str) -> FraudAgentOutput:
        data = self._parse_json_output(raw)
        indicators = [
            FraudIndicator(
                indicator_name=i.get("indicator_name", "Unknown"),
                severity=i.get("severity", "medium"),
                description=i.get("description", ""),
                score_contribution=float(i.get("score_contribution", 0.0)),
            )
            for i in data.get("indicators", [])
        ]
        confidence = float(data.get("confidence", 0.5))
        fraud_score = float(data.get("fraud_score", 0.3))
        return FraudAgentOutput(
            run_id=run_id,
            decision=AgentDecisionEnum(data.get("decision", "flag")),
            confidence=confidence,
            risk_level=RiskLevelEnum(data.get("risk_level", "medium")),
            reasoning=data.get("reasoning", ""),
            key_factors=data.get("key_factors", []),
            escalation_required=data.get("escalation_required", fraud_score > 0.7),
            escalation_reason=data.get("escalation_reason"),
            human_handoff=data.get("human_handoff", False),
            warnings=data.get("warnings", []),
            fraud_score=fraud_score,
            is_fraudulent=data.get("is_fraudulent", fraud_score > 0.6),
            fraud_type=data.get("fraud_type"),
            indicators=indicators,
            aml_risk=data.get("aml_risk", False),
            aml_flags=data.get("aml_flags", []),
            transaction_velocity_flag=data.get("transaction_velocity_flag", False),
            geo_anomaly=data.get("geo_anomaly", False),
            device_anomaly=data.get("device_anomaly", False),
            pattern_match=data.get("pattern_match", []),
            recommended_action=data.get("recommended_action", "monitor"),
            block_account=data.get("block_account", False),
            report_to_fiu=data.get("report_to_fiu", False),
        )

    def _error_output(self, run_id: str, error: str, elapsed: float) -> FraudAgentOutput:
        return FraudAgentOutput(
            run_id=run_id, decision=AgentDecisionEnum.ESCALATE,
            confidence=0.0, risk_level=RiskLevelEnum.HIGH,
            reasoning=f"Agent error: {error}", key_factors=["System error"],
            escalation_required=True, escalation_reason=error,
            fraud_score=0.5, is_fraudulent=False,
            indicators=[], recommended_action="monitor",
            warnings=[error], processing_time_ms=int(elapsed * 1000),
        )
