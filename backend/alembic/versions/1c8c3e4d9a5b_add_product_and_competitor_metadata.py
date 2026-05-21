"""add product and competitor metadata

Revision ID: 1c8c3e4d9a5b
Revises: 9ba821df6da5
Create Date: 2026-05-21 09:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1c8c3e4d9a5b"
down_revision: Union[str, Sequence[str], None] = "9ba821df6da5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("category", sa.String(length=120), nullable=True))
    op.add_column(
        "products",
        sa.Column("specifications", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("products", sa.Column("searchable_text", sa.Text(), nullable=True))
    op.create_index("ix_products_category", "products", ["category"], unique=False)
    op.create_index(
        "ix_products_searchable_text", "products", ["searchable_text"], unique=False
    )

    op.add_column("competitors", sa.Column("competitor_description", sa.Text(), nullable=True))
    op.add_column("competitors", sa.Column("competitor_category", sa.String(length=120), nullable=True))
    op.add_column("competitors", sa.Column("competitor_brand", sa.String(length=120), nullable=True))
    op.add_column(
        "competitors",
        sa.Column("competitor_attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("competitors", sa.Column("title_similarity", sa.Float(), nullable=True))
    op.add_column("competitors", sa.Column("description_similarity", sa.Float(), nullable=True))
    op.add_column("competitors", sa.Column("attribute_similarity", sa.Float(), nullable=True))
    op.add_column("competitors", sa.Column("keyword_score", sa.Float(), nullable=True))
    op.add_column("competitors", sa.Column("ranking_score", sa.Float(), nullable=True))
    op.add_column("competitors", sa.Column("match_confidence", sa.Float(), nullable=True))
    op.add_column("competitors", sa.Column("category_match", sa.Boolean(), nullable=True))
    op.add_column(
        "competitors",
        sa.Column("matched_attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_competitors_ranking_score", "competitors", ["ranking_score"], unique=False
    )
    op.create_index(
        "ix_competitors_match_confidence",
        "competitors",
        ["match_confidence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_competitors_match_confidence", table_name="competitors")
    op.drop_index("ix_competitors_ranking_score", table_name="competitors")
    op.drop_column("competitors", "matched_attributes")
    op.drop_column("competitors", "category_match")
    op.drop_column("competitors", "match_confidence")
    op.drop_column("competitors", "ranking_score")
    op.drop_column("competitors", "keyword_score")
    op.drop_column("competitors", "attribute_similarity")
    op.drop_column("competitors", "description_similarity")
    op.drop_column("competitors", "title_similarity")
    op.drop_column("competitors", "competitor_attributes")
    op.drop_column("competitors", "competitor_brand")
    op.drop_column("competitors", "competitor_category")
    op.drop_column("competitors", "competitor_description")

    op.drop_index("ix_products_searchable_text", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_column("products", "searchable_text")
    op.drop_column("products", "specifications")
    op.drop_column("products", "category")
    op.drop_column("products", "description")
