"""
Central Orchestrator Engine
==============================
Entry point for all agentic workflow execution.
Manages graph lifecycle, streaming, tracing, and DB persistence.

Usage:
    engine = OrchestratorEngine(session)
    result = await engine.run(
        workflow="loan_assessment",
        input_data={...},
        user_id="...",
        stream=False,
    )
"""

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.orchestration.states.graph_states import WorkflowStatus
from app.orchestration.utils.tracer import WorkflowTracer

logger = get_logger(__name__)

REGISTERED_GRAPHS = {
    "loan_assessment": "app.orchestration.graphs.loan_assessment",
    "fraud_detection": "app.orchestration.graphs.loan_assessment",   # Reuse for now
    "document_verification": "app.orchestration.graphs.loan_assessment",
}


class OrchestratorEngine:
    """
    Central engine that routes requests to the correct LangGraph workflow,
    manages execution, streaming, and persists traces.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(
        self,
        workflow: str,
        input_data: Dict[str, Any],
        user_id: str,
        session_id: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a named workflow synchronously.
        Returns the final state output dict.
        """
        run_id = str(uuid.uuid4())
        tracer = WorkflowTracer(run_id, workflow)

        logger.info(
            "orchestrator.run_started",
            run_id=run_id,
            workflow=workflow,
            user_id=user_id,
        )

        # Persist initial trace record
        await self._create_trace_record(run_id, workflow, user_id, session_id, input_data)

        try:
            graph, initial_state = await self._build_graph_and_state(
                workflow, run_id, user_id, session_id, input_data
            )

            config = {
                "recursion_limit": settings.orchestration.recursion_limit,
                "configurable": {"run_id": run_id},
            }

            final_state = await graph.ainvoke(initial_state, config=config)

            output = final_state.get("output") or {
                "decision": str(final_state.get("final_decision")),
                "response": final_state.get("final_response", ""),
                "status": str(final_state.get("status", WorkflowStatus.COMPLETED)),
            }

            await self._complete_trace_record(run_id, final_state, tracer)
            logger.info("orchestrator.run_completed", run_id=run_id, workflow=workflow)
            return output

        except Exception as exc:
            logger.exception("orchestrator.run_failed", run_id=run_id, error=str(exc))
            await self._fail_trace_record(run_id, str(exc))
            return {
                "error": str(exc),
                "status": WorkflowStatus.FAILED,
                "run_id": run_id,
            }

    async def stream(
        self,
        workflow: str,
        input_data: Dict[str, Any],
        user_id: str,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute a workflow with streaming output.
        Yields state patches as they are emitted by each node.
        """
        run_id = str(uuid.uuid4())
        await self._create_trace_record(run_id, workflow, user_id, session_id, input_data)

        try:
            graph, initial_state = await self._build_graph_and_state(
                workflow, run_id, user_id, session_id, input_data
            )
            config = {"recursion_limit": settings.orchestration.recursion_limit}

            async for chunk in graph.astream(initial_state, config=config):
                for node_name, node_output in chunk.items():
                    yield {
                        "event": "node_complete",
                        "node": node_name,
                        "run_id": run_id,
                        "data": {
                            "status": str(node_output.get("status", "")),
                            "decision": str(node_output.get("final_decision", "")),
                            "confidence": node_output.get("confidence_score"),
                            "current_node": node_output.get("current_node"),
                        },
                    }

            yield {"event": "complete", "run_id": run_id}

        except Exception as exc:
            logger.exception("orchestrator.stream_failed", run_id=run_id)
            yield {"event": "error", "run_id": run_id, "error": str(exc)}
            await self._fail_trace_record(run_id, str(exc))

    # ──────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────

    async def _build_graph_and_state(
        self,
        workflow: str,
        run_id: str,
        user_id: str,
        session_id: Optional[str],
        input_data: Dict[str, Any],
    ):
        if workflow == "loan_assessment":
            from app.orchestration.graphs.loan_assessment import (
                create_loan_state,
                get_loan_assessment_graph,
            )
            graph = get_loan_assessment_graph()
            state = create_loan_state(
                loan_application_id=input_data.get("loan_application_id", ""),
                user_id=user_id,
                loan_data=input_data,
                session_id=session_id,
            )
            state["run_id"] = run_id
            return graph, state
        else:
            raise ValueError(f"Unknown workflow: '{workflow}'")

    async def _create_trace_record(
        self,
        run_id: str,
        workflow: str,
        user_id: str,
        session_id: Optional[str],
        input_data: Dict[str, Any],
    ) -> None:
        try:
            from sqlalchemy import text
            await self.session.execute(
                text("""
                    INSERT INTO agent_traces
                    (id, run_id, agent_name, workflow_name, user_id, session_id,
                     status, input_data, total_steps, total_tool_calls, total_tokens,
                     created_at, updated_at)
                    VALUES
                    (gen_random_uuid(), :run_id, :agent, :workflow, :user_id::uuid,
                     :session_id::uuid, 'running',
                     :input_data::jsonb, 0, 0, 0, NOW(), NOW())
                """),
                {
                    "run_id": run_id,
                    "agent": workflow,
                    "workflow": workflow,
                    "user_id": user_id,
                    "session_id": session_id,
                    "input_data": str(
                        {k: v for k, v in input_data.items()
                         if k not in {"password", "token"}}
                    ),
                },
            )
            await self.session.flush()
        except Exception as exc:
            logger.warning("orchestrator.trace_create_failed", error=str(exc))

    async def _complete_trace_record(
        self, run_id: str, final_state: Dict, tracer: WorkflowTracer
    ) -> None:
        await tracer.persist(self.session)

    async def _fail_trace_record(self, run_id: str, error: str) -> None:
        try:
            from sqlalchemy import text
            await self.session.execute(
                text("""
                    UPDATE agent_traces
                    SET status = 'failed', error_message = :error,
                        completed_at = NOW(), updated_at = NOW()
                    WHERE run_id = :run_id
                """),
                {"run_id": run_id, "error": error[:2000]},
            )
            await self.session.flush()
        except Exception as exc:
            logger.warning("orchestrator.trace_fail_update_failed", error=str(exc))
