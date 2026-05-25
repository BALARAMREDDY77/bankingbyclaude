"""
KYC Verification Agent
========================
Verifies customer identity using documents, PAN, Aadhaar,
sanctions screening, PEP checks, and OCR extracted data.
"""

import json
from typing import Any, Dict

from app.agents.shared.base_agent import BaseAgent
from app.agents.shared.prompts.templates import KYC_SYSTEM_PROMPT, KYC_HUMAN_TEMPLATE, build_prompt
from app.agents.shared.schemas.outputs import (
    AgentDecisionEnum, DocumentCheckResult, KYCAgentOutput, RiskLevelEnum,
)
from app.agents.shared.tools.banking_tools import (
    check_pep_database, check_sanctions_list, verify_aadhaar, verify_pan_number,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class KYCVerificationAgent(BaseAgent):
    agent_name = "kyc_verification_agent"
    system_prompt = KYC_SYSTEM_PROMPT

    async def build_context(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        customer_id = input_data.get("customer_id", "")
        name = input_data.get("name", "")
        pan = input_data.get("pan_number", "")
        aadhaar = input_data.get("aadhaar_uid", "")
        dob = input_data.get("dob", "")
        documents = input_data.get("documents", [])
        extracted_data = input_data.get("extracted_data", {})

        # Run tools concurrently
        import asyncio
        pan_result, aadhaar_result, sanctions_result, pep_result = await asyncio.gather(
            verify_pan_number(pan, name) if pan else asyncio.coroutine(lambda: {})(),
            verify_aadhaar(aadhaar, name, dob) if aadhaar else asyncio.coroutine(lambda: {})(),
            check_sanctions_list(name, pan) if name else asyncio.coroutine(lambda: {})(),
            check_pep_database(name, dob) if name else asyncio.coroutine(lambda: {})(),
        )

        # RAG context for KYC policies
        policy_context = ""
        if self.session:
            try:
                from app.rag.services.hybrid_retrieval import HybridRetrievalService
                svc = HybridRetrievalService(self.session)
                results, _ = await svc.retrieve(
                    query="KYC document verification requirements India banking",
                    knowledge_base="kyc_compliance",
                    top_k=3,
                )
                policy_context = "\n".join(r.chunk_text for r in results)
            except Exception:
                policy_context = "Apply standard KYC norms as per RBI Master Direction."

        return {
            "customer_id": customer_id,
            "application_type": input_data.get("application_type", "account_opening"),
            "documents_json": json.dumps(documents, indent=2),
            "extracted_data_json": json.dumps({
                **extracted_data,
                "pan_verification": pan_result,
                "aadhaar_verification": aadhaar_result,
                "sanctions_check": sanctions_result,
                "pep_check": pep_result,
            }, indent=2),
            "policy_context": policy_context,
        }

    def build_prompt(self, context: Dict[str, Any]) -> str:
        return build_prompt(KYC_HUMAN_TEMPLATE, context)

    def parse_output(self, raw: str, run_id: str) -> KYCAgentOutput:
        data = self._parse_json_output(raw)
        doc_checks = [
            DocumentCheckResult(
                document_type=d.get("document_type", "unknown"),
                is_present=d.get("is_present", False),
                is_valid=d.get("is_valid"),
                is_authentic=d.get("is_authentic"),
                extracted_field=d.get("extracted_field"),
                issues=d.get("issues", []),
            )
            for d in data.get("documents_checked", [])
        ]
        confidence = float(data.get("confidence", 0.5))
        return KYCAgentOutput(
            run_id=run_id,
            decision=AgentDecisionEnum(data.get("decision", "escalate")),
            confidence=confidence,
            risk_level=RiskLevelEnum(data.get("risk_level", "medium")),
            reasoning=data.get("reasoning", ""),
            key_factors=data.get("key_factors", []),
            escalation_required=data.get("escalation_required", confidence < 0.6),
            escalation_reason=data.get("escalation_reason"),
            human_handoff=data.get("human_handoff", False),
            warnings=data.get("warnings", []),
            identity_verified=data.get("identity_verified", False),
            documents_checked=doc_checks,
            name_match=data.get("name_match"),
            dob_match=data.get("dob_match"),
            address_verified=data.get("address_verified"),
            pan_verified=data.get("pan_verified"),
            aadhaar_verified=data.get("aadhaar_verified"),
            pep_check=data.get("pep_check", False),
            sanctions_check=data.get("sanctions_check", False),
            kyc_level=data.get("kyc_level", "basic"),
            missing_documents=data.get("missing_documents", []),
            resubmission_required=data.get("resubmission_required", []),
        )

    def _error_output(self, run_id: str, error: str, elapsed: float) -> KYCAgentOutput:
        return KYCAgentOutput(
            run_id=run_id, decision=AgentDecisionEnum.ESCALATE,
            confidence=0.0, risk_level=RiskLevelEnum.HIGH,
            reasoning=f"Agent error: {error}", key_factors=["System error"],
            escalation_required=True, escalation_reason=error,
            identity_verified=False, documents_checked=[],
            warnings=[error], processing_time_ms=int(elapsed * 1000),
        )
