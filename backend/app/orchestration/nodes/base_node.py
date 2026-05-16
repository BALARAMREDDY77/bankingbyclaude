"""
Base Node
===========
Abstract base class for all LangGraph nodes.
Provides: LLM client, tracer hooks, retry, guardrails, structured output.

Every node:
  1. Receives typed state dict
  2. Runs execute() with automatic retry
  3. Returns state patch (partial dict)
  4. Records trace step
"""

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Type

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.orchestration.guardrails.guardrails import get_input_guardrail, get_output_guardrail
from app.orchestration.states.graph_states import BaseGraphState, WorkflowStatus
from app.orchestration.utils.retry import DEFAULT_POLICY, RetryPolicy, with_retry

logger = get_logger(__name__)


class BaseNode(ABC):
    """
    Abstract base for all banking workflow nodes.
    Subclasses implement execute() — everything else is handled here.
    """

    name: str = "base_node"
    description: str = ""
    retry_policy: RetryPolicy = DEFAULT_POLICY
    use_guardrails: bool = True
    use_fallback_model: bool = True

    def __init__(self) -> None:
        self._primary_llm: Optional[ChatAnthropic] = None
        self._fallback_llm: Optional[ChatAnthropic] = None
        self._input_guardrail = get_input_guardrail()
        self._output_guardrail = get_output_guardrail()

    @property
    def llm(self) -> ChatAnthropic:
        if self._primary_llm is None:
            self._primary_llm = ChatAnthropic(
                model=settings.orchestration.default_model,
                api_key=settings.orchestration.anthropic_api_key,
                max_tokens=settings.orchestration.max_tokens,
                temperature=settings.orchestration.temperature,
            )
        return self._primary_llm

    @property
    def fallback_llm(self) -> ChatAnthropic:
        if self._fallback_llm is None:
            self._fallback_llm = ChatAnthropic(
                model=settings.orchestration.fallback_model,
                api_key=settings.orchestration.anthropic_api_key,
                max_tokens=settings.orchestration.max_tokens,
                temperature=settings.orchestration.temperature,
            )
        return self._fallback_llm

    @abstractmethod
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Core node logic. Returns a partial state dict (patch).
        Must be implemented by every subclass.
        """
        raise NotImplementedError

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        LangGraph-callable entry point.
        Wraps execute() with retry, tracing, and guardrails.
        """
        start = time.perf_counter()
        trace = state.get("trace", [])
        completed = state.get("completed_nodes", [])
        retry_count = state.get("retry_count", 0)

        logger.info(
            "node.started",
            node=self.name,
            run_id=state.get("run_id", ""),
            iteration=state.get("iteration_count", 0),
        )

        try:
            # Input guardrail check
            if self.use_guardrails:
                query = self._extract_query(state)
                if query:
                    result = self._input_guardrail.check(query)
                    if not result.passed:
                        return self._error_patch(
                            state,
                            f"Input guardrail failed: {'; '.join(result.violations)}",
                            start,
                        )

            # Execute with retry
            patch = await self._execute_with_retry(state)

            # Output guardrail check
            if self.use_guardrails:
                response_text = self._extract_response_text(patch)
                confidence = patch.get("confidence_score", 1.0)
                if response_text:
                    out_result = self._output_guardrail.check(response_text, confidence)
                    if not out_result.passed:
                        patch["output_guardrail_passed"] = False
                        patch.setdefault("guardrail_violations", []).extend(out_result.violations)
                    else:
                        patch["output_guardrail_passed"] = True
                    if out_result.sanitized_text and out_result.sanitized_text != response_text:
                        patch = self._update_response_text(patch, out_result.sanitized_text)

            latency_ms = int((time.perf_counter() - start) * 1000)
            trace.append({
                "node": self.name,
                "latency_ms": latency_ms,
                "decision": patch.get("final_decision"),
                "confidence": patch.get("confidence_score"),
                "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            logger.info(
                "node.completed",
                node=self.name,
                latency_ms=latency_ms,
                decision=patch.get("final_decision"),
                confidence=patch.get("confidence_score"),
            )

            return {
                **patch,
                "current_node": self.name,
                "completed_nodes": completed + [self.name],
                "trace": trace,
                "latency_ms": {
                    **state.get("latency_ms", {}),
                    self.name: latency_ms,
                },
            }

        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("node.failed", node=self.name, error=str(exc))
            trace.append({
                "node": self.name,
                "latency_ms": latency_ms,
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return self._error_patch(state, str(exc), start, trace=trace)

    async def _execute_with_retry(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute with retry policy."""
        import asyncio
        last_error = None
        for attempt in range(self.retry_policy.max_retries + 1):
            try:
                if attempt > 0 and self.use_fallback_model:
                    # Use fallback model on retry
                    self._primary_llm = self.fallback_llm
                return await self.execute(state)
            except Exception as exc:
                last_error = exc
                if not self.retry_policy.should_retry(exc, attempt):
                    raise
                delay = self.retry_policy.get_delay(attempt)
                logger.warning(
                    "node.retrying",
                    node=self.name,
                    attempt=attempt + 1,
                    delay=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
        raise last_error

    def _error_patch(
        self,
        state: Dict[str, Any],
        error: str,
        start: float,
        trace: Optional[list] = None,
    ) -> Dict[str, Any]:
        return {
            "status": WorkflowStatus.FAILED,
            "error": error,
            "error_node": self.name,
            "current_node": self.name,
            "trace": trace or state.get("trace", []),
            "completed_nodes": state.get("completed_nodes", []),
        }

    async def invoke_llm(
        self,
        system_prompt: str,
        human_message: str,
        use_fallback: bool = False,
    ) -> tuple[str, int, int]:
        """
        Invoke LLM and return (response_text, input_tokens, output_tokens).
        """
        model = self.fallback_llm if use_fallback else self.llm
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ]
        response = await model.ainvoke(messages)
        text = response.content if isinstance(response.content, str) else str(response.content)
        usage = getattr(response, "usage_metadata", {}) or {}
        return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)

    @staticmethod
    def _extract_query(state: Dict[str, Any]) -> Optional[str]:
        if state.get("user_query"):
            return state["user_query"]
        msgs = state.get("messages", [])
        for msg in reversed(msgs):
            if hasattr(msg, "content") and isinstance(msg.content, str):
                return msg.content
        return None

    @staticmethod
    def _extract_response_text(patch: Dict[str, Any]) -> Optional[str]:
        return (
            patch.get("final_response")
            or patch.get("draft_response")
            or patch.get("decision_reason")
        )

    @staticmethod
    def _update_response_text(patch: Dict[str, Any], text: str) -> Dict[str, Any]:
        if "final_response" in patch:
            patch["final_response"] = text
        elif "draft_response" in patch:
            patch["draft_response"] = text
        return patch
