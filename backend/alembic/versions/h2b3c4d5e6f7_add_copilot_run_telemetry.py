"""add seller-scoped Copilot run telemetry

Revision ID: h2b3c4d5e6f7
Revises: g1a2b3c4d5e6
Create Date: 2026-07-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "h2b3c4d5e6f7"
down_revision = "g1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "copilot_run_telemetry" in sa.inspect(bind).get_table_names():
        return

    op.create_table(
        "copilot_run_telemetry",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_mode", sa.String(length=24), nullable=False),
        sa.Column("question_type", sa.String(length=64), nullable=False),
        sa.Column("selected_domains_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selected_metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selected_tools_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("planner_status", sa.String(length=32), nullable=False),
        sa.Column("planner_fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("clarification_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tools_succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tools_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rag_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rag_result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_data_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("final_confidence", sa.String(length=32), nullable=True),
        sa.Column("result_status", sa.String(length=32), nullable=False),
        sa.Column("planner_miss_reasons_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("planner_duration_ms", sa.Integer(), nullable=True),
        sa.Column("tool_duration_ms", sa.Integer(), nullable=True),
        sa.Column("rag_duration_ms", sa.Integer(), nullable=True),
        sa.Column("groq_duration_ms", sa.Integer(), nullable=True),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["copilot_conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_copilot_run_telemetry_run_id"),
        sa.CheckConstraint("tools_succeeded >= 0", name="ck_copilot_telemetry_tools_succeeded_nonnegative"),
        sa.CheckConstraint("tools_failed >= 0", name="ck_copilot_telemetry_tools_failed_nonnegative"),
        sa.CheckConstraint("rag_result_count >= 0", name="ck_copilot_telemetry_rag_result_count_nonnegative"),
        sa.CheckConstraint("evidence_count >= 0", name="ck_copilot_telemetry_evidence_count_nonnegative"),
        sa.CheckConstraint("missing_data_count >= 0", name="ck_copilot_telemetry_missing_data_count_nonnegative"),
    )
    op.create_index("ix_copilot_telemetry_seller_created", "copilot_run_telemetry", ["seller_id", "created_at"])
    op.create_index("ix_copilot_telemetry_conversation_created", "copilot_run_telemetry", ["conversation_id", "created_at"])
    op.create_index("ix_copilot_telemetry_planner_status", "copilot_run_telemetry", ["planner_status"])
    op.create_index("ix_copilot_telemetry_result_status", "copilot_run_telemetry", ["result_status"])


def downgrade() -> None:
    bind = op.get_bind()
    if "copilot_run_telemetry" not in sa.inspect(bind).get_table_names():
        return
    op.drop_index("ix_copilot_telemetry_result_status", table_name="copilot_run_telemetry")
    op.drop_index("ix_copilot_telemetry_planner_status", table_name="copilot_run_telemetry")
    op.drop_index("ix_copilot_telemetry_conversation_created", table_name="copilot_run_telemetry")
    op.drop_index("ix_copilot_telemetry_seller_created", table_name="copilot_run_telemetry")
    op.drop_table("copilot_run_telemetry")
