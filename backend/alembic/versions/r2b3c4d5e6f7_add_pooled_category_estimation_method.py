"""add POOLED_CATEGORY demand estimation method

Revision ID: r2b3c4d5e6f7
Revises: q1a2b3c4d5e6

Originally shipped under o9c0d1e2f3a4, which another migration also used, so Alembic
skipped it. Re-chained as the newest head; IF NOT EXISTS keeps it safe where it already ran.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "r2b3c4d5e6f7"
down_revision: str | None = "q1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive: one new enum value; existing estimates are untouched.
    op.execute("ALTER TYPE demand_estimation_method ADD VALUE IF NOT EXISTS 'POOLED_CATEGORY'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value without rewriting the type; rows using it
    # stay readable, and turning DEMAND_RESPONSE_POOLING_ENABLED off stops their use.
    pass
