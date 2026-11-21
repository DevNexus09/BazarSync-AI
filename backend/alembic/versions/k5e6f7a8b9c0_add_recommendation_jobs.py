"""Track durable recommendation generation and request keys."""

import sqlalchemy as sa
from alembic import op

revision = "k5e6f7a8b9c0"
down_revision = "j4d5e6f7a8b9"
branch_labels = None
depends_on = None

ACTIVE = sa.text("status IN ('PENDING', 'RUNNING')")


def upgrade() -> None:
    op.create_table(
        "recommendation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "seller_id",
            sa.Uuid(),
            sa.ForeignKey("sellers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scrape_run_id", sa.Uuid()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("dispatch_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column(
            "recommendation_id",
            sa.Uuid(),
            sa.ForeignKey("recommendations.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="ck_rec_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_rec_jobs_attempts"),
        sa.CheckConstraint(
            "(status = 'RUNNING') = (lease_until IS NOT NULL)", name="ck_rec_jobs_lease"
        ),
        sa.CheckConstraint(
            "(status IN ('COMPLETED', 'FAILED')) = (completed_at IS NOT NULL)",
            name="ck_rec_jobs_terminal",
        ),
    )
    op.create_index(
        "uq_rec_jobs_active_scope",
        "recommendation_jobs",
        ["seller_id", "product_id"],
        unique=True,
        postgresql_where=ACTIVE,
    )
    op.create_index(
        "ix_rec_jobs_scope_created",
        "recommendation_jobs",
        ["seller_id", "product_id", "created_at"],
    )
    op.create_index(
        "ix_rec_jobs_dispatch",
        "recommendation_jobs",
        ["dispatch_after"],
        postgresql_where=ACTIVE,
    )
    op.create_table(
        "recommendation_job_requests",
        sa.Column("seller_id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Uuid(), primary_key=True),
        sa.Column("request_key", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("recommendation_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_recommendation_job_requests_job_id",
        "recommendation_job_requests",
        ["job_id"],
    )


def downgrade() -> None:
    op.drop_table("recommendation_job_requests")
    op.drop_table("recommendation_jobs")
