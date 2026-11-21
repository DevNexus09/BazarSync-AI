"""Persist field observation timestamps on competitor snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "j4d5e6f7a8b9"
down_revision = "i3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "competitor_snapshots",
        sa.Column("price_observed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "competitor_snapshots",
        sa.Column("stock_observed_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("competitor_snapshots", "stock_observed_at")
    op.drop_column("competitor_snapshots", "price_observed_at")
