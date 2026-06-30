"""add competitor snapshots

Revision ID: e5f6a7b8c9d0
Revises: 91e0e754a8e6
Create Date: 2026-06-29 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "91e0e754a8e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    scrape_run_columns = {column["name"] for column in inspector.get_columns("scrape_runs")}

    if "marketplace" not in scrape_run_columns:
        op.add_column(
            "scrape_runs",
            sa.Column(
                "marketplace",
                sa.String(length=120),
                server_default="Daraz Bangladesh",
                nullable=False,
            ),
        )
    if "run_key" not in scrape_run_columns:
        op.add_column("scrape_runs", sa.Column("run_key", sa.String(length=255), nullable=True))
        op.execute("UPDATE scrape_runs SET run_key = 'legacy:' || id::text WHERE run_key IS NULL")
        op.alter_column("scrape_runs", "run_key", nullable=False)
    if "completed_at" not in scrape_run_columns:
        op.add_column("scrape_runs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE scrape_runs SET completed_at = finished_at WHERE lower(status) = 'completed'")
    if "failed_at" not in scrape_run_columns:
        op.add_column("scrape_runs", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE scrape_runs SET failed_at = finished_at WHERE lower(status) = 'failed'")
    if "discovered_competitor_count" not in scrape_run_columns:
        op.add_column("scrape_runs", sa.Column("discovered_competitor_count", sa.Integer(), nullable=True))
        op.execute("UPDATE scrape_runs SET discovered_competitor_count = total_results")
    if "snapshot_count" not in scrape_run_columns:
        op.add_column("scrape_runs", sa.Column("snapshot_count", sa.Integer(), nullable=True))
    if "failure_code" not in scrape_run_columns:
        op.add_column("scrape_runs", sa.Column("failure_code", sa.String(length=120), nullable=True))
    if "updated_at" not in scrape_run_columns:
        op.add_column(
            "scrape_runs",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    op.execute(
        """
        UPDATE scrape_runs
        SET status = CASE lower(status)
            WHEN 'pending' THEN 'PENDING'
            WHEN 'running' THEN 'RUNNING'
            WHEN 'completed' THEN 'COMPLETED'
            WHEN 'failed' THEN 'FAILED'
            WHEN 'partial' THEN 'PARTIAL'
            ELSE status
        END
        """
    )
    op.alter_column("scrape_runs", "status", server_default="PENDING", existing_type=sa.String(length=30))

    existing_indexes = {index["name"] for index in inspector.get_indexes("scrape_runs")}
    if "ix_scrape_runs_product_status_finished" not in existing_indexes:
        op.create_index(
            "ix_scrape_runs_product_status_finished",
            "scrape_runs",
            ["product_id", "status", "finished_at"],
            unique=False,
        )
    if "ix_scrape_runs_product_marketplace_created" not in existing_indexes:
        op.create_index(
            "ix_scrape_runs_product_marketplace_created",
            "scrape_runs",
            ["product_id", "marketplace", "created_at"],
            unique=False,
        )

    existing_unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("scrape_runs")}
    if "uq_scrape_runs_scope_run_key" not in existing_unique_constraints:
        op.create_unique_constraint(
            "uq_scrape_runs_scope_run_key",
            "scrape_runs",
            ["seller_id", "product_id", "marketplace", "run_key"],
        )
    existing_check_constraints = {constraint["name"] for constraint in inspector.get_check_constraints("scrape_runs")}
    if "ck_scrape_runs_status" not in existing_check_constraints:
        op.create_check_constraint(
            "ck_scrape_runs_status",
            "scrape_runs",
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'PARTIAL')",
        )

    existing_tables = set(inspector.get_table_names())
    if "competitor_snapshots" not in existing_tables:
        op.create_table(
            "competitor_snapshots",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("competitor_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column("currency", sa.String(length=3), server_default="BDT", nullable=False),
            sa.Column("rating", sa.Numeric(precision=3, scale=2), nullable=True),
            sa.Column("review_count", sa.Integer(), nullable=True),
            sa.Column("stock_status", sa.String(length=20), nullable=False),
            sa.Column("raw_stock_text", sa.String(length=120), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("external_listing_id", sa.String(length=255), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_competitor_snapshots_price_nonnegative"),
            sa.CheckConstraint("rating IS NULL OR (rating >= 0 AND rating <= 5)", name="ck_competitor_snapshots_rating_range"),
            sa.CheckConstraint(
                "review_count IS NULL OR review_count >= 0",
                name="ck_competitor_snapshots_review_count_nonnegative",
            ),
            sa.CheckConstraint(
                "stock_status IN ('IN_STOCK', 'OUT_OF_STOCK', 'UNKNOWN')",
                name="ck_competitor_snapshots_stock_status",
            ),
            sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "scrape_run_id",
                "competitor_id",
                "product_id",
                name="uq_competitor_snapshots_run_competitor_product",
            ),
        )
        op.create_index("ix_competitor_snapshots_scrape_run_id", "competitor_snapshots", ["scrape_run_id"])
        op.create_index(
            "ix_competitor_snapshots_product_captured",
            "competitor_snapshots",
            ["product_id", "captured_at"],
        )
        op.create_index(
            "ix_competitor_snapshots_competitor_product_captured",
            "competitor_snapshots",
            ["competitor_id", "product_id", "captured_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "competitor_snapshots" in existing_tables:
        op.drop_index("ix_competitor_snapshots_competitor_product_captured", table_name="competitor_snapshots")
        op.drop_index("ix_competitor_snapshots_product_captured", table_name="competitor_snapshots")
        op.drop_index("ix_competitor_snapshots_scrape_run_id", table_name="competitor_snapshots")
        op.drop_table("competitor_snapshots")

    existing_check_constraints = {constraint["name"] for constraint in inspector.get_check_constraints("scrape_runs")}
    if "ck_scrape_runs_status" in existing_check_constraints:
        op.drop_constraint("ck_scrape_runs_status", "scrape_runs", type_="check")

    existing_unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("scrape_runs")}
    if "uq_scrape_runs_scope_run_key" in existing_unique_constraints:
        op.drop_constraint("uq_scrape_runs_scope_run_key", "scrape_runs", type_="unique")

    existing_indexes = {index["name"] for index in inspector.get_indexes("scrape_runs")}
    if "ix_scrape_runs_product_marketplace_created" in existing_indexes:
        op.drop_index("ix_scrape_runs_product_marketplace_created", table_name="scrape_runs")
    if "ix_scrape_runs_product_status_finished" in existing_indexes:
        op.drop_index("ix_scrape_runs_product_status_finished", table_name="scrape_runs")

    op.execute(
        """
        UPDATE scrape_runs
        SET status = CASE status
            WHEN 'PENDING' THEN 'pending'
            WHEN 'RUNNING' THEN 'running'
            WHEN 'COMPLETED' THEN 'completed'
            WHEN 'FAILED' THEN 'failed'
            WHEN 'PARTIAL' THEN 'partial'
            ELSE status
        END
        """
    )
    op.alter_column("scrape_runs", "status", server_default="pending", existing_type=sa.String(length=30))

    scrape_run_columns = {column["name"] for column in inspector.get_columns("scrape_runs")}
    for column_name in (
        "updated_at",
        "failure_code",
        "snapshot_count",
        "discovered_competitor_count",
        "failed_at",
        "completed_at",
        "run_key",
        "marketplace",
    ):
        if column_name in scrape_run_columns:
            op.drop_column("scrape_runs", column_name)
