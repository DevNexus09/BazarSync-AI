"""add copilot hydration metadata

Revision ID: c1d2e3f4a5b7
Revises: c0d1e2f3a4b5
Create Date: 2026-07-06 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c1d2e3f4a5b7"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_type():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("copilot_messages")}
    message_columns = {
        "missing_data_json": _json_type(),
        "data_freshness_json": _json_type(),
        "tools_used_json": _json_type(),
        "domains_used_json": _json_type(),
        "recommended_next_steps_json": _json_type(),
        "action_proposal_json": _json_type(),
        "response_metadata_json": _json_type(),
    }
    for name, column_type in message_columns.items():
        if name not in columns:
            op.add_column("copilot_messages", sa.Column(name, column_type, nullable=True))

    columns = {column["name"] for column in inspector.get_columns("copilot_tool_calls")}
    for name in ("duration_ms", "evidence_count", "missing_data_count"):
        if name not in columns:
            op.add_column("copilot_tool_calls", sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("copilot_tool_calls")}
    for name in ("missing_data_count", "evidence_count", "duration_ms"):
        if name in columns:
            op.drop_column("copilot_tool_calls", name)

    columns = {column["name"] for column in inspector.get_columns("copilot_messages")}
    for name in (
        "response_metadata_json",
        "action_proposal_json",
        "recommended_next_steps_json",
        "domains_used_json",
        "tools_used_json",
        "data_freshness_json",
        "missing_data_json",
    ):
        if name in columns:
            op.drop_column("copilot_messages", name)
