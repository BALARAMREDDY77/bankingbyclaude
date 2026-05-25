"""
Transaction Analysis Agent
============================
Analyzes bank statements for income verification, spending patterns,
EMI burden, savings rate, and creditworthiness signals.
"""

import json
from typing import Any, Dict

from app.agents.shared.base_agent import BaseAgent
from app.agents.shared.prompts.templates import TRANSACTION_SYSTEM_PROMPT, TRANSACTION_HUMAN_TEMPLATE, build_prompt
from app.agents.shared.schemas.outputs import (
    AgentDecisionEnum, RiskLevelEnum, TransactionAgentOutput, TransactionInsight,
)
from app.agents.shared.tools.banking_tools import get_transaction_history
from app.core.logging import get_logger

logger = get_logger(__name__)


class TransactionAnalysisAgent(BaseAgent):
    agent_name = "transaction_analysis_agent"
    system_prompt = TRANSACTION_SYSTEM_PROMPT

    async def build_context(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        user_id = input_data.get("user_id", "")
        months = input_data.get("months", 6)
        loan_application_id = input_data.get("loan_application_id", "")

        tx_history = await get_transaction_history(user_id, months=months)

        # Build statement summary
        statement_summary = {
            "period_months": months,
            "total_credit": tx_history.get("total_credit"),
            "total_debit": tx_history.get("total_debit"),
            "net_cashflow": tx_history.get("net_cashflow"),
            "avg_monthly_credit": tx_history.get("avg_monthly_credit"),
            "avg_monthly_debit": tx_history.get("avg_monthly_debit"),
            "estimated_salary": tx_history.get("estimated_monthly_salary"),
            "estimated_emi": tx_history.get("estimated_monthly_emi"),
        }

        # RAG — retrieve underwriting guidelines
        underwriting_context = ""
        if self.session:
            try:
                from app.rag.services.hybrid_retrieval import HybridRetrievalService
                svc = HybridRetrievalService(self.session)
                results, _ = await svc.retrieve(
                    query="bank statement analysis income verification loan underwriting",
                    knowledge_base="loan_underwriting", top_k=3,
                )
                underwriting_context = "\n".join(r.chunk_text for r in results)
            except Exception:
                underwriting_context = "Apply standard income verification norms."

        return {
            "user_id": user_id,
            "period": f"Last {months} months",
            "loan_application_id": loan_application_id,
            "statement_summary_json": json.dumps(statement_summary, indent=2),
            "transactions_json": json.dumps(tx_history.get("transactions", [])[:20], indent=2),
            "underwriting_context": underwriting_context[:2000],
        }

    def build_prompt(self, context: Dict[str, Any]) -> str:
        return build_prompt(TRANSACTION_HUMAN_TEMPLATE, context)

    def parse_output(self, raw: str, run_id: str) -> TransactionAgentOutput:
        data = self._parse_json_output(raw)
        categories = [
            TransactionInsight(
                category=c.get("category", "Other"),
                amount=float(c.get("amount", 0)),
                percentage_of_total=float(c.get("percentage_of_total", 0)),
                trend=c.get("trend", "stable"),
            )
            for c in data.get("spending_categories", [])
        ]
        confidence = float(data.get("confidence", 0.6))
        return TransactionAgentOutput(
            run_id=run_id,
            decision=AgentDecisionEnum(data.get("decision", "pass")),
            confidence=confidence,
            risk_level=RiskLevelEnum(data.get("risk_level", "medium")),
            reasoning=data.get("reasoning", ""),
            key_factors=data.get("key_factors", []),
            escalation_required=data.get("escalation_required", False),
            escalation_reason=data.get("escalation_reason"),
            warnings=data.get("warnings", []),
            total_transactions=int(data.get("total_transactions", 0)),
            total_credit=float(data.get("total_credit", 0)),
            total_debit=float(data.get("total_debit", 0)),
            net_cashflow=float(data.get("net_cashflow", 0)),
            avg_monthly_balance=data.get("avg_monthly_balance"),
            spending_categories=categories,
            irregular_transactions=data.get("irregular_transactions", []),
            salary_detected=data.get("salary_detected", False),
            estimated_monthly_income=data.get("estimated_monthly_income"),
            emi_detected=data.get("emi_detected", False),
            estimated_emi_burden=data.get("estimated_emi_burden"),
            savings_rate=data.get("savings_rate"),
            creditworthiness_signal=data.get("creditworthiness_signal", "moderate"),
            anomalies=data.get("anomalies", []),
            summary=data.get("summary", ""),
        )

    def _error_output(self, run_id: str, error: str, elapsed: float) -> TransactionAgentOutput:
        return TransactionAgentOutput(
            run_id=run_id, decision=AgentDecisionEnum.ESCALATE,
            confidence=0.0, risk_level=RiskLevelEnum.HIGH,
            reasoning=f"Agent error: {error}", key_factors=["System error"],
            escalation_required=True, escalation_reason=error,
            total_transactions=0, total_credit=0, total_debit=0, net_cashflow=0,
            spending_categories=[], irregular_transactions=[],
            salary_detected=False, emi_detected=False,
            creditworthiness_signal="poor", summary="Analysis failed.",
            warnings=[error], processing_time_ms=int(elapsed * 1000),
        )
