"""relax capital recovery loss constraints

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-07-03 00:00:04.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "dead_stock_capital_recovery_estimates"


def upgrade() -> None:
    op.drop_constraint("ck_capital_recovery_net", TABLE, type_="check")
    op.drop_constraint("ck_capital_recovery_cost_basis", TABLE, type_="check")
    op.drop_constraint("ck_capital_recovery_ratio", TABLE, type_="check")
    op.create_check_constraint(
        "ck_capital_recovery_ratio",
        TABLE,
        "capital_recovery_ratio IS NULL OR capital_recovery_ratio <= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_capital_recovery_ratio", TABLE, type_="check")
    op.create_check_constraint(
        "ck_capital_recovery_net",
        TABLE,
        "net_cash_recovered IS NULL OR net_cash_recovered >= 0",
    )
    op.create_check_constraint(
        "ck_capital_recovery_cost_basis",
        TABLE,
        "cost_basis_recovered IS NULL OR cost_basis_recovered >= 0",
    )
    op.create_check_constraint(
        "ck_capital_recovery_ratio",
        TABLE,
        "capital_recovery_ratio IS NULL OR (capital_recovery_ratio >= 0 AND capital_recovery_ratio <= 1)",
    )
