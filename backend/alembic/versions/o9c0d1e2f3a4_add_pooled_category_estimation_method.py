"""add POOLED_CATEGORY demand estimation method

Revision ID: o9c0d1e2f3a4
Revises: n8b9c0d1e2f3
"""

from collections.abc import Sequence

from alembic import op

revision: str = "o9c0d1e2f3a4"
down_revision: str | None = "n8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive: one new enum value; existing estimates are untouched.
    op.execute("ALTER TYPE demand_estimation_method ADD VALUE IF NOT EXISTS 'POOLED_CATEGORY'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value without rewriting the type; rows using it
    # stay readable, and turning DEMAND_RESPONSE_POOLING_ENABLED off stops their use.
    pass
