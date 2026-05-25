"""
Report Generation Agent
=========================
Generates structured banking reports from agent outputs and data.
Supports: credit assessment, fraud investigation, KYC summary,
          transaction summary, risk report, compliance report.
"""

import json
from typing import Any, Dict

from app.agents.shared.base_agent import BaseAgent
from app.agents.shared.prompts.templates import REPORT_SYSTEM_PROMPT, REPORT_HUMAN_TEMPLATE, build_prompt
from app.agents.shared.schemas.outputs import (
    AgentDecisionEnum, ReportAgentOutput, ReportSection, RiskLevelEnum,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class ReportGenerationAgent(BaseAgent):
    agent_name = "report_generation_agent"
    system_prompt = REPORT_SYSTEM_PROMPT

    async def build_context(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        report_type = input_data.get("report_type", "credit_assessment")
        data_inputs = input_data.get("data_inputs", {})
        agent_outputs = input_data.get("agent_outputs", {})

        # RAG — retrieve report template context
        report_template_context = ""
        if self.session:
            try:
                from app.rag.services.hybrid_retrieval import HybridRetrievalService
                svc = HybridRetrievalService(self.session)
                results, _ = await svc.retrieve(
                    query=f"banking {report_type.replace('_', ' ')} report format template",
                    knowledge_base="general_banking", top_k=3,
                )
                report_template_context = "\n".join(r.chunk_text for r in results)
            except Exception:
                report_template_context = "Generate a professional structured banking report."

        return {
            "report_type": report_type,
            "report_period": input_data.get("report_period", "Current"),
            "generated_for": input_data.get("generated_for", "Internal Use"),
            "confidentiality_level": input_data.get("confidentiality_level", "internal"),
            "data_inputs_json": json.dumps(data_inputs, indent=2)[:3000],
            "agent_outputs_json": json.dumps(agent_outputs, indent=2)[:3000],
            "report_template_context": report_template_context[:2000],
        }

    def build_prompt(self, context: Dict[str, Any]) -> str:
        return build_prompt(REPORT_HUMAN_TEMPLATE, context)

    def parse_output(self, raw: str, run_id: str) -> ReportAgentOutput:
        data = self._parse_json_output(raw)
        sections = [
            ReportSection(
                section_title=s.get("section_title", "Section"),
                content=s.get("content", ""),
                data_points=s.get("data_points", []),
                charts_required=s.get("charts_required", []),
            )
            for s in data.get("sections", [])
        ]
        full_text = " ".join(s.content for s in sections)
        confidence = float(data.get("confidence", 0.8))

        return ReportAgentOutput(
            run_id=run_id,
            decision=AgentDecisionEnum(data.get("decision", "pass")),
            confidence=confidence,
            risk_level=RiskLevelEnum(data.get("risk_level", "low")),
            reasoning=data.get("reasoning", "Report generated successfully."),
            key_factors=data.get("key_factors", []),
            escalation_required=data.get("escalation_required", False),
            warnings=data.get("warnings", []),
            report_type=data.get("report_type", "general"),
            report_title=data.get("report_title", "Banking Report"),
            executive_summary=data.get("executive_summary", ""),
            sections=sections,
            key_findings=data.get("key_findings", []),
            recommendations=data.get("recommendations", []),
            data_sources=data.get("data_sources", ["Internal Banking System"]),
            report_period=data.get("report_period"),
            generated_for=data.get("generated_for"),
            confidentiality_level=data.get("confidentiality_level", "internal"),
            word_count=len(full_text.split()),
            requires_review=data.get("requires_review", True),
        )

    def _error_output(self, run_id: str, error: str, elapsed: float) -> ReportAgentOutput:
        return ReportAgentOutput(
            run_id=run_id, decision=AgentDecisionEnum.ESCALATE,
            confidence=0.0, risk_level=RiskLevelEnum.HIGH,
            reasoning=f"Agent error: {error}", key_factors=["System error"],
            escalation_required=True,
            report_type="error", report_title="Report Generation Failed",
            executive_summary=f"Report generation failed: {error}",
            sections=[], key_findings=[], recommendations=[],
            data_sources=[], requires_review=True,
            warnings=[error], processing_time_ms=int(elapsed * 1000),
        )
