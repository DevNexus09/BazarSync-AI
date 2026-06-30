"""add market opportunities

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-29 00:00:03.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TYPE_VALUES = ("COMPETITOR_OUT_OF_STOCK", "COMPETITOR_PRICE_RISE", "COMPETITOR_REMOVED")
LEVEL_VALUES = ("LOW", "MEDIUM", "HIGH")
STATUS_VALUES = ("OPEN", "ACKNOWLEDGED", "DISMISSED", "EXPIRED", "RESOLVED")
ACTION_VALUES = ("PRICE_LOWER", "PRICE_RAISE", "HOLD", "REORDER")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    for name, values in {
        "market_opportunity_type": TYPE_VALUES,
        "market_opportunity_level": LEVEL_VALUES,
        "market_opportunity_status": STATUS_VALUES,
        "market_opportunity_action": ACTION_VALUES,
    }.items():
        if name not in enum_names:
            postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    if "market_opportunities" not in set(inspector.get_table_names()):
        op.create_table(
            "market_opportunities",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("competitor_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("trigger_event_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("opportunity_type", postgresql.ENUM(*TYPE_VALUES, name="market_opportunity_type", create_type=False), nullable=False),
            sa.Column("opportunity_level", postgresql.ENUM(*LEVEL_VALUES, name="market_opportunity_level", create_type=False), nullable=False),
            sa.Column("opportunity_score", sa.Numeric(precision=8, scale=4), nullable=False),
            sa.Column("estimated_revenue", sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column("estimated_revenue_currency", sa.String(length=3), server_default="BDT", nullable=False),
            sa.Column("recommended_action", postgresql.ENUM(*ACTION_VALUES, name="market_opportunity_action", create_type=False), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("confidence_score", sa.Numeric(precision=8, scale=4), nullable=False),
            sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("status", postgresql.ENUM(*STATUS_VALUES, name="market_opportunity_status", create_type=False), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["trigger_event_id"], ["competitor_events.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("trigger_event_id", name="uq_market_opportunities_trigger_event_id"),
        )
        op.create_index("ix_market_opportunities_seller_status_detected", "market_opportunities", ["seller_id", "status", "detected_at"])
        op.create_index("ix_market_opportunities_product_detected", "market_opportunities", ["product_id", "detected_at"])
        op.create_index("ix_market_opportunities_level_detected", "market_opportunities", ["opportunity_level", "detected_at"])
        op.create_index("ix_market_opportunities_scrape_run_id", "market_opportunities", ["scrape_run_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "market_opportunities" in set(inspector.get_table_names()):
        op.drop_index("ix_market_opportunities_scrape_run_id", table_name="market_opportunities")
        op.drop_index("ix_market_opportunities_level_detected", table_name="market_opportunities")
        op.drop_index("ix_market_opportunities_product_detected", table_name="market_opportunities")
        op.drop_index("ix_market_opportunities_seller_status_detected", table_name="market_opportunities")
        op.drop_table("market_opportunities")
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    for name in ("market_opportunity_action", "market_opportunity_status", "market_opportunity_level", "market_opportunity_type"):
        if name in enum_names:
            postgresql.ENUM(name=name).drop(bind, checkfirst=True)
