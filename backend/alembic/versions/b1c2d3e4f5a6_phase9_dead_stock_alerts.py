"""phase9 dead stock alerts

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-07-03 00:00:01.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ALERT_ENUM = "telegram_inventory_alert_type"
TABLE = "telegram_inventory_alerts"


def upgrade() -> None:
    for value in (
        "DEAD_STOCK_CLASSIFIED",
        "DEAD_STOCK_CRITICAL_RISK",
        "DEAD_STOCK_LOCKED_CAPITAL",
        "DEAD_STOCK_RECOVERY_AVAILABLE",
        "DEAD_STOCK_AGED",
    ):
        op.execute(f"ALTER TYPE {ALERT_ENUM} ADD VALUE IF NOT EXISTS '{value}'")
    op.alter_column(TABLE, "risk_assessment_id", nullable=True)


def downgrade() -> None:
    op.alter_column(TABLE, "risk_assessment_id", nullable=False)
