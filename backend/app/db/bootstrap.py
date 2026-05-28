from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


_SELLERS_OPTIONAL_COLUMNS: dict[str, str] = {
    "phone": "VARCHAR(30)",
    "full_name": "VARCHAR(120)",
    "business_name": "VARCHAR(255)",
    "industry": "VARCHAR(120)",
    "website": "VARCHAR(255)",
    "address_line": "VARCHAR(255)",
    "city": "VARCHAR(120)",
    "country": "VARCHAR(120)",
}


_PRODUCT_COLUMNS: dict[str, str] = {
    "id": "UUID PRIMARY KEY",
    "seller_id": "UUID NOT NULL REFERENCES sellers(id) ON DELETE CASCADE",
    "title": "VARCHAR(255) NOT NULL",
    "cost_price": "NUMERIC(12, 2) NOT NULL",
    "selling_price": "NUMERIC(12, 2) NOT NULL",
    "stock_quantity": "INTEGER NOT NULL",
    "supplier_lead_time": "INTEGER NOT NULL",
    "minimum_margin": "NUMERIC(8, 2) NOT NULL",
    "created_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
}

_SNAPSHOT_LOG_COLUMNS: dict[str, str] = {
    "id": "UUID PRIMARY KEY",
    "seller_id": "UUID NOT NULL REFERENCES sellers(id) ON DELETE CASCADE",
    "product_id": "UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE",
    "telegram_chat_id": "VARCHAR(120) NOT NULL",
    "sent_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "status": "VARCHAR(50) NOT NULL",
    "error_message": "TEXT",
}

_SNAPSHOT_LOG_INDEXES: dict[str, str] = {
    "ix_snapshot_logs_seller_id": "seller_id",
    "ix_snapshot_logs_product_id": "product_id",
    "ix_snapshot_logs_status": "status",
    "ix_snapshot_logs_sent_at": "sent_at",
}


def ensure_sellers_profile_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if "sellers" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("sellers")}
    missing_columns = [
        (name, sql_type)
        for name, sql_type in _SELLERS_OPTIONAL_COLUMNS.items()
        if name not in columns
    ]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for name, sql_type in missing_columns:
            connection.execute(
                text(f"ALTER TABLE sellers ADD COLUMN {name} {sql_type}")
            )


def ensure_products_table(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "products" not in table_names:
        columns_sql = ", ".join(f"{name} {sql_type}" for name, sql_type in _PRODUCT_COLUMNS.items())
        with engine.begin() as connection:
            connection.execute(text(f"CREATE TABLE IF NOT EXISTS products ({columns_sql})"))
        return

    columns = {column["name"] for column in inspector.get_columns("products")}
    missing_columns = [
        (name, sql_type) for name, sql_type in _PRODUCT_COLUMNS.items() if name not in columns
    ]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for name, sql_type in missing_columns:
            safe_type = (
                sql_type.replace(" NOT NULL", "")
                .replace(" PRIMARY KEY", "")
            )
            connection.execute(text(f"ALTER TABLE products ADD COLUMN {name} {safe_type}"))


def ensure_snapshot_logs_table(engine: Engine) -> None:
    inspector = inspect(engine)
    if "snapshot_logs" not in inspector.get_table_names():
        columns_sql = ", ".join(
            f"{name} {sql_type}" for name, sql_type in _SNAPSHOT_LOG_COLUMNS.items()
        )
        with engine.begin() as connection:
            connection.execute(
                text(f"CREATE TABLE IF NOT EXISTS snapshot_logs ({columns_sql})")
            )
            for index_name, column_name in _SNAPSHOT_LOG_INDEXES.items():
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        f"{index_name} ON snapshot_logs ({column_name})"
                    )
                )
        return
