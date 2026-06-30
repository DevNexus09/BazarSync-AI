"""add competitor events

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-29 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EVENT_TYPES = (
    "PRICE_DROP",
    "PRICE_RISE",
    "OUT_OF_STOCK",
    "BACK_IN_STOCK",
    "NEW_COMPETITOR",
    "COMPETITOR_REMOVED",
)
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}

    if "competitor_event_type" not in enum_names:
        postgresql.ENUM(*EVENT_TYPES, name="competitor_event_type").create(bind, checkfirst=True)
    if "competitor_event_severity" not in enum_names:
        postgresql.ENUM(*SEVERITIES, name="competitor_event_severity").create(bind, checkfirst=True)

    if "competitor_events" not in set(inspector.get_table_names()):
        op.create_table(
            "competitor_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("competitor_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("previous_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("current_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "event_type",
                postgresql.ENUM(*EVENT_TYPES, name="competitor_event_type", create_type=False),
                nullable=False,
            ),
            sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("price_change_amount", sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column("price_change_percent", sa.Numeric(precision=8, scale=4), nullable=True),
            sa.Column(
                "severity",
                postgresql.ENUM(*SEVERITIES, name="competitor_event_severity", create_type=False),
                nullable=False,
            ),
            sa.Column("dedupe_key", sa.String(length=500), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["previous_snapshot_id"], ["competitor_snapshots.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["current_snapshot_id"], ["competitor_snapshots.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("dedupe_key", name="uq_competitor_events_dedupe_key"),
        )
        op.create_index("ix_competitor_events_product_detected", "competitor_events", ["product_id", "detected_at"])
        op.create_index("ix_competitor_events_competitor_detected", "competitor_events", ["competitor_id", "detected_at"])
        op.create_index("ix_competitor_events_type_detected", "competitor_events", ["event_type", "detected_at"])
        op.create_index("ix_competitor_events_scrape_run_id", "competitor_events", ["scrape_run_id"])
        op.create_index("ix_competitor_events_seller_detected", "competitor_events", ["seller_id", "detected_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "competitor_events" in set(inspector.get_table_names()):
        op.drop_index("ix_competitor_events_seller_detected", table_name="competitor_events")
        op.drop_index("ix_competitor_events_scrape_run_id", table_name="competitor_events")
        op.drop_index("ix_competitor_events_type_detected", table_name="competitor_events")
        op.drop_index("ix_competitor_events_competitor_detected", table_name="competitor_events")
        op.drop_index("ix_competitor_events_product_detected", table_name="competitor_events")
        op.drop_table("competitor_events")

    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "competitor_event_severity" in enum_names:
        postgresql.ENUM(name="competitor_event_severity").drop(bind, checkfirst=True)
    if "competitor_event_type" in enum_names:
        postgresql.ENUM(name="competitor_event_type").drop(bind, checkfirst=True)
