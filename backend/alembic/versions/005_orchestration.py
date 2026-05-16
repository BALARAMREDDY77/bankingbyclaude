"""add_orchestration_settings

Revision ID: 005_orchestration
Revises: 004_vector_store
Create Date: 2026-05-14

Adds orchestration-related columns to agent_traces table
and creates workflow_runs audit table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "005_orchestration"
down_revision = "004_vector_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extend agent_traces with orchestration fields ───────
    with op.batch_alter_table("agent_traces") as batch_op:
        batch_op.add_column(
            sa.Column("session_id", UUID(as_uuid=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("confidence_score", sa.Numeric(5, 4), nullable=True)
        )
        batch_op.add_column(
            sa.Column("final_decision", sa.String(50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("decision_reason", sa.Text, nullable=True)
        )
        batch_op.add_column(
            sa.Column("escalated", sa.Boolean, server_default="false")
        )
        batch_op.add_column(
            sa.Column("fallback_triggered", sa.Boolean, server_default="false")
        )
        batch_op.add_column(
            sa.Column("token_usage", JSONB, nullable=True)
        )
        batch_op.add_column(
            sa.Column("latency_ms_per_node", JSONB, nullable=True)
        )

    # ── workflow_runs — high-level audit of orchestration runs ──
    op.create_table(
        "workflow_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", sa.String(100), nullable=False, unique=True),
        sa.Column("workflow_name", sa.String(100), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("loan_application_id", UUID(as_uuid=True),
                  sa.ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("final_decision", sa.String(50), nullable=True),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=True),
        sa.Column("total_nodes", sa.Integer, server_default="0"),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("escalated", sa.Boolean, server_default="false"),
        sa.Column("fallback_triggered", sa.Boolean, server_default="false"),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_runs_run_id", "workflow_runs", ["run_id"], unique=True)
    op.create_index("ix_workflow_runs_user_id", "workflow_runs", ["user_id"])
    op.create_index("ix_workflow_runs_workflow", "workflow_runs", ["workflow_name"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("ix_workflow_runs_created_at", "workflow_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("workflow_runs")

    with op.batch_alter_table("agent_traces") as batch_op:
        for col in [
            "session_id", "confidence_score", "final_decision",
            "decision_reason", "escalated", "fallback_triggered",
            "token_usage", "latency_ms_per_node",
        ]:
            batch_op.drop_column(col)
