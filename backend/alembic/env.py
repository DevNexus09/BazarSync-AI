from logging.config import fileConfig
import os

from sqlalchemy import engine_from_config, pool
from alembic import context

# Import your SQLAlchemy Base
from app.db.base import Base

# Import ALL models so Alembic can detect them
from app.models.seller import Seller
from app.models.product import Product
from app.models.scrape_run import ScrapeRun
from app.models.competitor import Competitor
from app.models.price_history import PriceHistory

# Alembic Config object
config = context.config

# Load DATABASE_URL from environment variable
database_url = os.getenv("DATABASE_URL")

if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Configure Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tell Alembic about your SQLAlchemy models
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with only a database URL
    and avoids creating an actual Engine connection.
    """

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this mode Alembic creates a real database Engine
    and associates a live connection with the migration context.
    """

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# Decide whether to run offline or online migrations
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

import os

config.set_main_option(
    "sqlalchemy.url",
    os.getenv("DATABASE_URL")
)