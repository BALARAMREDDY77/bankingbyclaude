"""
Customer Support Agent
=======================
Multilingual customer support using RAG-retrieved KB articles.
Detects language, responds in same language, escalates when needed.
"""

import json
from typing import Any, Dict

from app.agents.shared.base_agent import BaseAgent
from app.agents.shared.prompts.templates import SUPPORT_SYSTEM_PROMPT, SUPPORT_HUMAN_TEMPLATE, build_prompt
from app.agents.shared.schemas.outputs import (
    AgentDecisionEnum, CustomerSupportOutput, LanguageEnum, RiskLevelEnum, SupportCitation,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def _detect_language(text: str) -> LanguageEnum:
    """Simple heuristic language detection."""
    try:
        from langdetect import detect
        lang = detect(text)
        mapping = {"hi": LanguageEnum.HI, "te": LanguageEnum.TE, "ta": LanguageEnum.TA,
                   "kn": LanguageEnum.KN, "mr": LanguageEnum.MR}
        return mapping.get(lang, LanguageEnum.EN)
    except Exception:
        return LanguageEnum.EN


class CustomerSupportAgent(BaseAgent):
    agent_name = "customer_support_agent"
    system_prompt = SUPPORT_SYSTEM_PROMPT

    async def build_context(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        customer_id = input_data.get("customer_id", "")
        customer_name = input_data.get("customer_name", "Valued Customer")
        account_status = input_data.get("account_status", "active")
        user_query = input_data.get("user_query", "")
        interaction_history = input_data.get("interaction_history", [])

        # Detect language
        detected_lang = _detect_language(user_query)

        # RAG retrieval — search general banking KB
        kb_context = ""
        citations = []
        if self.session and user_query:
            try:
                from app.rag.services.hybrid_retrieval import HybridRetrievalService
                svc = HybridRetrievalService(self.session)
                results, obs = await svc.retrieve(
                    query=user_query,
                    knowledge_base="general_banking",
                    top_k=5,
                    filters={"language": detected_lang.value} if detected_lang != LanguageEnum.EN else {},
                )
                kb_context = "\n\n".join(
                    f"[Article {i+1}] {r.chunk_text}"
                    for i, r in enumerate(results)
                )
                citations = [
                    {"source": f"KB Article {i+1}", "relevance": r.hybrid_score, "excerpt": r.chunk_text[:150]}
                    for i, r in enumerate(results[:3])
                ]
            except Exception:
                kb_context = "General banking assistance. Refer to official bank website for detailed information."

        return {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "account_status": account_status,
            "detected_language": detected_lang.value,
            "customer_query": user_query,
            "kb_context": kb_context[:4000],
            "interaction_history": json.dumps(interaction_history[-3:], indent=2),
            "_citations": citations,  # Pass through for output
        }

    def build_prompt(self, context: Dict[str, Any]) -> str:
        return build_prompt(SUPPORT_HUMAN_TEMPLATE, context)

    def parse_output(self, raw: str, run_id: str) -> CustomerSupportOutput:
        data = self._parse_json_output(raw)
        confidence = float(data.get("confidence", 0.7))

        citations = [
            SupportCitation(
                source=c.get("source", "KB"),
                relevance_score=float(c.get("relevance", 0.5)),
                excerpt=c.get("excerpt", ""),
            )
            for c in data.get("citations", [])
        ]

        lang_str = data.get("detected_language", "en")
        resp_lang_str = data.get("response_language", lang_str)
        try:
            detected_lang = LanguageEnum(lang_str)
            response_lang = LanguageEnum(resp_lang_str)
        except ValueError:
            detected_lang = response_lang = LanguageEnum.EN

        return CustomerSupportOutput(
            run_id=run_id,
            decision=AgentDecisionEnum(data.get("decision", "pass")),
            confidence=confidence,
            risk_level=RiskLevelEnum.LOW,
            reasoning=data.get("reasoning", ""),
            key_factors=data.get("key_factors", []),
            escalation_required=data.get("escalation_required", False),
            escalation_reason=data.get("escalation_reason"),
            human_handoff=data.get("needs_human", False),
            warnings=data.get("warnings", []),
            query_intent=data.get("query_intent", "general_inquiry"),
            detected_language=detected_lang,
            response=data.get("response", ""),
            response_language=response_lang,
            citations=citations,
            follow_up_questions=data.get("follow_up_questions", []),
            related_topics=data.get("related_topics", []),
            sentiment=data.get("sentiment", "neutral"),
            ticket_required=data.get("ticket_required", False),
            ticket_category=data.get("ticket_category"),
            resolution_confidence=confidence,
            needs_human=data.get("needs_human", False),
        )

    def _error_output(self, run_id: str, error: str, elapsed: float) -> CustomerSupportOutput:
        return CustomerSupportOutput(
            run_id=run_id, decision=AgentDecisionEnum.ESCALATE,
            confidence=0.0, risk_level=RiskLevelEnum.LOW,
            reasoning=f"Agent error: {error}", key_factors=["System error"],
            escalation_required=True, human_handoff=True,
            query_intent="unknown", detected_language=LanguageEnum.EN,
            response="I'm unable to process your request right now. Please contact our support team.",
            response_language=LanguageEnum.EN,
            needs_human=True, resolution_confidence=0.0,
            warnings=[error], processing_time_ms=int(elapsed * 1000),
        )
