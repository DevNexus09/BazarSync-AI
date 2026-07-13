from logging.config import fileConfig
import os

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# Import your SQLAlchemy Base
from app.db.base import Base

# Import ALL models so Alembic can detect them
from app.models.alert import Alert
from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.competitor import Competitor
from app.models.competitor_event import CompetitorEvent
from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.copilot import CopilotActionProposal, CopilotConversation, CopilotMessage, CopilotToolCall
from app.models.copilot_telemetry import CopilotRunTelemetry
from app.models.demand_elasticity_estimate import DemandElasticityEstimate
from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation
from app.models.inventory_history import InventoryHistory
from app.models.inventory_risk import InventoryRiskAssessment
from app.models.market_opportunity import MarketOpportunity
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.password_reset import PasswordResetAuthorization, PasswordResetChallenge
from app.models.price_history import PriceHistory
from app.models.pricing_policy import PricingPolicy
from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
from app.models.product import Product, ProductMarketplaceListing
from app.models.rag_memory import RagMemoryChunk, RagMemoryDocument, RagQueryLog
from app.models.rag_index_outbox import RagIndexOutbox
from app.models.recommendation import Recommendation
from app.models.reorder_recommendation import ReorderRecommendation
from app.models.sales_data_coverage import SalesDataCoverage
from app.models.sales_record import SalesRecord
from app.models.sales_velocity import SalesVelocity
from app.models.security_audit_event import SecurityAuditEvent
from app.models.scrape_run import ScrapeRun
from app.models.seller import Seller
from app.models.stockout_prediction import StockoutPrediction
from app.models.telegram_connection import SellerTelegramConnection
from app.models.telegram_inventory_alert import TelegramInventoryAlert
from app.models.telegram_snapshot_log import TelegramProductSnapshotLog

# Alembic Config object
config = context.config

load_dotenv()

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
