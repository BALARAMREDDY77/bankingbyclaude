"""
Base Agent
===========
Abstract base for all banking AI agents.
Provides: LLM invocation, retry, guardrails, tracing, structured output parsing.

All 6 agents extend BaseAgent and implement:
  - build_context()  : gather data from tools + RAG
  - build_prompt()   : render secure prompt template
  - parse_output()   : parse + validate LLM JSON response
  - run()            : orchestrate full agent execution
"""

import json
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Type, TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import get_logger
from app.orchestration.guardrails.guardrails import get_input_guardrail, get_output_guardrail
from app.orchestration.utils.retry import DEFAULT_POLICY, RetryPolicy

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class BaseAgent(ABC):
    """Abstract base agent with full production scaffolding."""

    agent_name: str = "base_agent"
    system_prompt: str = ""
    retry_policy: RetryPolicy = DEFAULT_POLICY
    output_schema: Type[BaseModel] = None

    def __init__(self, session=None) -> None:
        self.session = session
        self._llm: Optional[ChatAnthropic] = None
        self._fallback_llm: Optional[ChatAnthropic] = None
        self._input_guardrail = get_input_guardrail()
        self._output_guardrail = get_output_guardrail()

    @property
    def llm(self) -> ChatAnthropic:
        if self._llm is None:
            self._llm = ChatAnthropic(
                model=settings.orchestration.default_model,
                api_key=settings.orchestration.anthropic_api_key,
                max_tokens=settings.orchestration.max_tokens,
                temperature=0.0,           # Deterministic for financial decisions
            )
        return self._llm

    @property
    def fallback_llm(self) -> ChatAnthropic:
        if self._fallback_llm is None:
            self._fallback_llm = ChatAnthropic(
                model=settings.orchestration.fallback_model,
                api_key=settings.orchestration.anthropic_api_key,
                max_tokens=settings.orchestration.max_tokens,
                temperature=0.0,
            )
        return self._fallback_llm

    # ── Abstract methods ─────────────────────

    @abstractmethod
    async def build_context(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Gather all data needed for the agent — tools + RAG retrieval."""
        raise NotImplementedError

    @abstractmethod
    def build_prompt(self, context: Dict[str, Any]) -> str:
        """Render the secure prompt template with context data."""
        raise NotImplementedError

    @abstractmethod
    def parse_output(self, raw_output: str, run_id: str) -> BaseModel:
        """Parse LLM JSON output into validated Pydantic schema."""
        raise NotImplementedError

    # ── Main run() ───────────────────────────

    async def run(
        self,
        input_data: Dict[str, Any],
        run_id: Optional[str] = None,
        language: str = "en",
    ) -> BaseModel:
        """
        Full agent execution pipeline:
        1. Guardrail input check
        2. Build context (tools + RAG)
        3. Build prompt
        4. Invoke LLM (with retry)
        5. Parse + validate output
        6. Guardrail output check
        7. Return typed result
        """
        run_id = run_id or str(uuid.uuid4())
        start = time.perf_counter()
        fallback_triggered = False

        logger.info(
            "agent.started",
            agent=self.agent_name,
            run_id=run_id,
            language=language,
        )

        # ── Step 1: Input guardrail ───────────
        query_text = str(input_data.get("query") or input_data.get("user_query", ""))
        if query_text:
            guard_result = self._input_guardrail.check(query_text)
            if not guard_result.passed:
                return self._error_output(
                    run_id,
                    f"Input guardrail: {'; '.join(guard_result.violations)}",
                    time.perf_counter() - start,
                )

        # ── Step 2: Build context ─────────────
        try:
            context = await self.build_context(input_data)
            context["run_id"] = run_id
            context["language"] = language
        except Exception as exc:
            logger.error("agent.context_build_failed", agent=self.agent_name, error=str(exc))
            return self._error_output(run_id, f"Context build failed: {exc}", time.perf_counter() - start)

        # ── Step 3: Build prompt ──────────────
        human_message = self.build_prompt(context)

        # ── Step 4: Invoke LLM with retry ─────
        raw_output = ""
        tokens_in, tokens_out = 0, 0
        for attempt in range(self.retry_policy.max_retries + 1):
            try:
                model = self.fallback_llm if (attempt > 0 and fallback_triggered) else self.llm
                response = await model.ainvoke([
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=human_message),
                ])
                raw_output = response.content if isinstance(response.content, str) else str(response.content)
                usage = getattr(response, "usage_metadata", {}) or {}
                tokens_in = usage.get("input_tokens", 0)
                tokens_out = usage.get("output_tokens", 0)
                break
            except Exception as exc:
                logger.warning(
                    "agent.llm_retry",
                    agent=self.agent_name,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt == 0:
                    fallback_triggered = True
                if attempt >= self.retry_policy.max_retries:
                    return self._error_output(run_id, f"LLM failed: {exc}", time.perf_counter() - start)
                import asyncio
                await asyncio.sleep(self.retry_policy.get_delay(attempt))

        # ── Step 5: Parse output ──────────────
        try:
            result = self.parse_output(raw_output, run_id)
        except Exception as exc:
            logger.error("agent.parse_failed", agent=self.agent_name, error=str(exc), raw=raw_output[:200])
            return self._error_output(run_id, f"Output parse failed: {exc}", time.perf_counter() - start)

        # ── Step 6: Output guardrail ──────────
        response_text = getattr(result, "reasoning", "") or getattr(result, "response", "")
        if response_text:
            out_guard = self._output_guardrail.check(
                response_text,
                confidence=getattr(result, "confidence", 1.0),
            )
            if not out_guard.passed:
                logger.warning("agent.output_guardrail_failed", violations=out_guard.violations)
                result.warnings = getattr(result, "warnings", []) + out_guard.violations

        # ── Step 7: Finalize ──────────────────
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if hasattr(result, "processing_time_ms"):
            result.processing_time_ms = elapsed_ms
        if hasattr(result, "model_used"):
            result.model_used = (
                settings.orchestration.fallback_model if fallback_triggered
                else settings.orchestration.default_model
            )
        if hasattr(result, "fallback_triggered"):
            result.fallback_triggered = fallback_triggered

        logger.info(
            "agent.completed",
            agent=self.agent_name,
            run_id=run_id,
            confidence=getattr(result, "confidence", None),
            decision=str(getattr(result, "decision", "")),
            latency_ms=elapsed_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

        return result

    def _parse_json_output(self, raw: str) -> Dict[str, Any]:
        """Extract and parse JSON from LLM output, handling markdown fences."""
        import re
        clean = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            # Try to find JSON object in output
            match = re.search(r"\{.*\}", clean, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise ValueError(f"No valid JSON found in output: {clean[:200]}")

    @abstractmethod
    def _error_output(self, run_id: str, error: str, elapsed: float) -> BaseModel:
        """Return a safe error output conforming to the agent's schema."""
        raise NotImplementedError
