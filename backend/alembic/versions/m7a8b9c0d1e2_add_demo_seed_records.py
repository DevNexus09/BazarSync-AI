"""add demo seed ownership records

Revision ID: m7a8b9c0d1e2
Revises: l6f7a8b9c0d1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "m7a8b9c0d1e2"
down_revision: str | None = "l6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_seed_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_name", sa.String(length=80), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "seed_name", "record_type", "external_key",
            name="uq_demo_seed_records_identity",
        ),
    )
    op.create_index("ix_demo_seed_records_seller", "demo_seed_records", ["seller_id"])
    op.create_index(
        "ix_demo_seed_records_entity",
        "demo_seed_records",
        ["record_type", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_demo_seed_records_entity", table_name="demo_seed_records")
    op.drop_index("ix_demo_seed_records_seller", table_name="demo_seed_records")
    op.drop_table("demo_seed_records")
