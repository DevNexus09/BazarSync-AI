"""repair dead stock risk columns

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-04 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "dead_stock_assessments"
RISK_LEVEL_VALUES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "dead_stock_risk_level" not in enum_names:
        postgresql.ENUM(*RISK_LEVEL_VALUES, name="dead_stock_risk_level").create(bind, checkfirst=True)

    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "risk_score" not in columns:
        op.add_column(
            TABLE,
            sa.Column("risk_score", sa.Numeric(precision=5, scale=2), nullable=True),
        )
    if "risk_level" not in columns:
        op.add_column(
            TABLE,
            sa.Column(
                "risk_level",
                postgresql.ENUM(*RISK_LEVEL_VALUES, name="dead_stock_risk_level", create_type=False),
                nullable=True,
            ),
        )

    op.execute(
        sa.text(
            """
            UPDATE dead_stock_assessments
            SET risk_score = CASE
                    WHEN risk_score IS NOT NULL THEN risk_score
                    WHEN rule_results ? 'risk_score'
                         AND (rule_results->>'risk_score') ~ '^[0-9]+(\\.[0-9]+)?$'
                    THEN LEAST(GREATEST((rule_results->>'risk_score')::numeric, 0), 100)
                    ELSE 0
                END,
                risk_level = CASE
                    WHEN risk_level IS NOT NULL THEN risk_level
                    WHEN rule_results->>'risk_level' IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
                    THEN (rule_results->>'risk_level')::dead_stock_risk_level
                    WHEN classification = 'DEAD_STOCK' THEN 'HIGH'::dead_stock_risk_level
                    WHEN classification = 'AT_RISK' THEN 'HIGH'::dead_stock_risk_level
                    WHEN classification = 'SLOW_MOVING' THEN 'MEDIUM'::dead_stock_risk_level
                    ELSE 'LOW'::dead_stock_risk_level
                END
            WHERE risk_score IS NULL OR risk_level IS NULL
            """
        )
    )
    op.alter_column(TABLE, "risk_score", nullable=False)
    op.alter_column(TABLE, "risk_level", nullable=False)

    constraints = {constraint["name"] for constraint in inspector.get_check_constraints(TABLE)}
    if "ck_dead_stock_risk_score_range" not in constraints:
        op.create_check_constraint(
            "ck_dead_stock_risk_score_range",
            TABLE,
            "risk_score >= 0 AND risk_score <= 100",
        )

    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    if "ix_dead_stock_seller_risk_level" not in indexes:
        op.create_index(
            "ix_dead_stock_seller_risk_level",
            TABLE,
            ["seller_id", "risk_level"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    if "ix_dead_stock_seller_risk_level" in indexes:
        op.drop_index("ix_dead_stock_seller_risk_level", table_name=TABLE)
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints(TABLE)}
    if "ck_dead_stock_risk_score_range" in constraints:
        op.drop_constraint("ck_dead_stock_risk_score_range", TABLE, type_="check")
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "risk_level" in columns:
        op.drop_column(TABLE, "risk_level")
    if "risk_score" in columns:
        op.drop_column(TABLE, "risk_score")
