"""merge heads

Revision ID: 91e0e754a8e6
Revises: 9b2d6a4d2a19, 7d2c3f6a9b0e
Create Date: 2026-05-29 00:52:16.179202

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '91e0e754a8e6'
down_revision: Union[str, Sequence[str], None] = ('9b2d6a4d2a19', '7d2c3f6a9b0e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
