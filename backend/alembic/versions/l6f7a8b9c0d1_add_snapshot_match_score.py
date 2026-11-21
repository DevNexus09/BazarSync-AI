"""Store match quality on the snapshot from the matching run."""

import sqlalchemy as sa
from alembic import op

revision = "l6f7a8b9c0d1"
down_revision = "k5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("competitor_snapshots", sa.Column("match_score", sa.Float()))


def downgrade() -> None:
    op.drop_column("competitor_snapshots", "match_score")
