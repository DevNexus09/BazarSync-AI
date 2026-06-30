"""add competitor rankings

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-29 00:00:02.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "competitor_rankings" not in set(inspector.get_table_names()):
        op.create_table(
            "competitor_rankings",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("competitor_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("price_score", sa.Numeric(precision=8, scale=4), nullable=False),
            sa.Column("rating_score", sa.Numeric(precision=8, scale=4), nullable=False),
            sa.Column("review_score", sa.Numeric(precision=8, scale=4), nullable=False),
            sa.Column("availability_score", sa.Numeric(precision=8, scale=4), nullable=False),
            sa.Column("total_score", sa.Numeric(precision=8, scale=4), nullable=False),
            sa.Column("market_rank", sa.Integer(), nullable=False),
            sa.Column("formula_version", sa.String(length=40), nullable=False),
            sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "scrape_run_id",
                "competitor_id",
                "formula_version",
                name="uq_competitor_rankings_run_competitor_formula",
            ),
        )
        op.create_index("ix_competitor_rankings_product_calculated", "competitor_rankings", ["product_id", "calculated_at"])
        op.create_index("ix_competitor_rankings_run_rank", "competitor_rankings", ["scrape_run_id", "market_rank"])
        op.create_index("ix_competitor_rankings_competitor_calculated", "competitor_rankings", ["competitor_id", "calculated_at"])
        op.create_index("ix_competitor_rankings_seller_calculated", "competitor_rankings", ["seller_id", "calculated_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "competitor_rankings" in set(inspector.get_table_names()):
        op.drop_index("ix_competitor_rankings_seller_calculated", table_name="competitor_rankings")
        op.drop_index("ix_competitor_rankings_competitor_calculated", table_name="competitor_rankings")
        op.drop_index("ix_competitor_rankings_run_rank", table_name="competitor_rankings")
        op.drop_index("ix_competitor_rankings_product_calculated", table_name="competitor_rankings")
        op.drop_table("competitor_rankings")
