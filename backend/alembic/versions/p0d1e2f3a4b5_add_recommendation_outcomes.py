"""add recommendation outcomes and reorder ordered_at

Revision ID: p0d1e2f3a4b5
Revises: o9c0d1e2f3a4
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "p0d1e2f3a4b5"
down_revision: str | None = "o9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OUTCOME_TYPE = postgresql.ENUM("PRICING", "REORDER", "RECOVERY", name="recommendation_outcome_type", create_type=False)
OUTCOME_STATUS = postgresql.ENUM("OBSERVED", "UNAVAILABLE", name="recommendation_outcome_status", create_type=False)


def upgrade() -> None:
    # Additive: a new table and one nullable column; existing rows are untouched.
    OUTCOME_TYPE.create(op.get_bind(), checkfirst=True)
    OUTCOME_STATUS.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "recommendation_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_type", OUTCOME_TYPE, nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_value", sa.Numeric(14, 4), nullable=True),
        sa.Column("observed_value", sa.Numeric(14, 4), nullable=True),
        sa.Column("observed_status", OUTCOME_STATUS, nullable=False),
        sa.Column("hit", sa.Boolean(), nullable=True),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("calculation_version", sa.String(length=40), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_id", "window_days", name="uq_recommendation_outcomes_recommendation_window"),
    )
    op.create_index(
        "ix_recommendation_outcomes_seller_type_evaluated",
        "recommendation_outcomes",
        ["seller_id", "recommendation_type", "evaluated_at"],
    )
    op.add_column("reorder_recommendations", sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reorder_recommendations", "ordered_at")
    op.drop_index("ix_recommendation_outcomes_seller_type_evaluated", table_name="recommendation_outcomes")
    op.drop_table("recommendation_outcomes")
    OUTCOME_STATUS.drop(op.get_bind(), checkfirst=True)
    OUTCOME_TYPE.drop(op.get_bind(), checkfirst=True)
