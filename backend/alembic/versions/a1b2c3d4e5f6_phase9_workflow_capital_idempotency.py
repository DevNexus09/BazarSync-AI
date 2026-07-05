"""phase9 workflow capital idempotency

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-07-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "a1b2c3d4e5f6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_capital_recovery_recommendation_version",
        "dead_stock_capital_recovery_estimates",
        ["recovery_recommendation_id", "calculation_version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_capital_recovery_recommendation_version",
        "dead_stock_capital_recovery_estimates",
        type_="unique",
    )
