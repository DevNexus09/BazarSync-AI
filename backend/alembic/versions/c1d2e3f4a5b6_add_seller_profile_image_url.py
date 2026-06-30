"""add seller profile image url

Revision ID: c1d2e3f4a5b6
Revises: b4c5d6e7f8a9
Create Date: 2026-06-30 18:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE sellers ADD COLUMN IF NOT EXISTS profile_image_url TEXT")
    op.execute("ALTER TABLE sellers ALTER COLUMN profile_image_url TYPE TEXT")


def downgrade() -> None:
    op.drop_column("sellers", "profile_image_url")
