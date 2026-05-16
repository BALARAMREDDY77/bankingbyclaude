"""
Orchestration Tracer
======================
Records every node execution, decision, and LLM call
for full observability of LangGraph workflow runs.

Trace structure:
  run_id → list of TraceStep (one per node execution)
  Each step: node_name, input_snapshot, output_snapshot,
              latency_ms, tokens, error, timestamp
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TraceStep:
    step_index: int
    node_name: str
    started_at: str
    ended_at: Optional[str] = None
    latency_ms: Optional[int] = None
    input_snapshot: Optional[Dict[str, Any]] = None
    output_snapshot: Optional[Dict[str, Any]] = None
    llm_model: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    error: Optional[str] = None
    decision: Optional[str] = None
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def complete(
        self,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        decision: Optional[str] = None,
        confidence: Optional[float] = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
    ) -> None:
        self.ended_at = datetime.now(timezone.utc).isoformat()
        if self.started_at:
            start = datetime.fromisoformat(self.started_at)
            self.latency_ms = int(
                (datetime.now(timezone.utc) - start).total_seconds() * 1000
            )
        self.output_snapshot = output
        self.error = error
        self.decision = decision
        self.confidence = confidence
        self.tokens_input = tokens_input
        self.tokens_output = tokens_output


class WorkflowTracer:
    """
    Collects trace steps during a LangGraph run.
    Attach to state["trace"] list — persisted to DB after run.
    """

    def __init__(self, run_id: str, workflow_name: str) -> None:
        self.run_id = run_id
        self.workflow_name = workflow_name
        self.steps: List[TraceStep] = []
        self._active_steps: Dict[str, TraceStep] = {}
        self._run_start = time.perf_counter()

    def start_node(
        self,
        node_name: str,
        input_snapshot: Optional[Dict[str, Any]] = None,
    ) -> TraceStep:
        step = TraceStep(
            step_index=len(self.steps),
            node_name=node_name,
            started_at=datetime.now(timezone.utc).isoformat(),
            input_snapshot=self._safe_snapshot(input_snapshot),
        )
        self.steps.append(step)
        self._active_steps[node_name] = step
        logger.info(
            "trace.node_started",
            run_id=self.run_id,
            node=node_name,
            step=step.step_index,
        )
        return step

    def end_node(
        self,
        node_name: str,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        decision: Optional[str] = None,
        confidence: Optional[float] = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
    ) -> Optional[TraceStep]:
        step = self._active_steps.pop(node_name, None)
        if step:
            step.complete(
                output=self._safe_snapshot(output),
                error=error,
                decision=decision,
                confidence=confidence,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
            )
            log_fn = logger.error if error else logger.info
            log_fn(
                "trace.node_ended",
                run_id=self.run_id,
                node=node_name,
                latency_ms=step.latency_ms,
                decision=decision,
                confidence=confidence,
                error=error,
            )
        return step

    def to_dict(self) -> Dict[str, Any]:
        total_ms = int((time.perf_counter() - self._run_start) * 1000)
        return {
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "total_steps": len(self.steps),
            "total_ms": total_ms,
            "steps": [
                {
                    "index": s.step_index,
                    "node": s.node_name,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "latency_ms": s.latency_ms,
                    "decision": s.decision,
                    "confidence": s.confidence,
                    "tokens_in": s.tokens_input,
                    "tokens_out": s.tokens_output,
                    "error": s.error,
                }
                for s in self.steps
            ],
        }

    @staticmethod
    def _safe_snapshot(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Sanitize snapshot — remove sensitive fields before storing."""
        if data is None:
            return None
        SENSITIVE = {"password", "hashed_password", "token", "secret", "api_key"}
        return {
            k: "***REDACTED***" if k.lower() in SENSITIVE else v
            for k, v in data.items()
            if not isinstance(v, (bytes, bytearray))
        }

    async def persist(self, session=None) -> None:
        """Save trace to agent_traces table."""
        if not settings.orchestration.trace_persist or not session:
            return
        try:
            from sqlalchemy import text
            trace_data = self.to_dict()
            await session.execute(
                text("""
                    UPDATE agent_traces
                    SET steps = :steps,
                        total_steps = :total_steps,
                        total_tokens = :total_tokens,
                        duration_ms = :duration_ms,
                        status = 'completed',
                        completed_at = NOW()
                    WHERE run_id = :run_id
                """),
                {
                    "run_id": self.run_id,
                    "steps": str(trace_data["steps"]),
                    "total_steps": trace_data["total_steps"],
                    "total_tokens": sum(
                        s.tokens_input + s.tokens_output for s in self.steps
                    ),
                    "duration_ms": trace_data["total_ms"],
                },
            )
            await session.flush()
        except Exception as exc:
            logger.warning("trace.persist_failed", error=str(exc))
