"""placeholder revision to repair migration chain.

Revision ID: d4f5a8c9b2e1
Revises: 9ba821df6da5
Create Date: 2026-05-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f5a8c9b2e1"
down_revision: Union[str, Sequence[str], None] = "9ba821df6da5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SELECT 1")


def downgrade() -> None:
    op.execute("SELECT 1")
