from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import register_routers

from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers

from app.db.bootstrap import (
    ensure_products_table,
    ensure_snapshot_logs_table,
    ensure_sellers_profile_columns,
)

from app.db.session import engine

from app.services.telegram.telegram_client import TelegramClient
from app.services.telegram.telegram_connection_service import TelegramConnectionSettings
from app.websocket.socket_manager import init_socketio

logger = logging.getLogger(__name__)


async def _setup_telegram_webhook() -> None:
    telegram_settings = TelegramConnectionSettings()
    webhook_url = telegram_settings.webhook_url
    if not webhook_url:
        logger.warning("telegram_webhook_not_configured reason=missing TELEGRAM_WEBHOOK_URL")
        return
    client = TelegramClient()
    await client.set_webhook(
        url=webhook_url,
        secret_token=telegram_settings.webhook_secret,
    )
    logger.info("telegram_webhook_configured url=%s", webhook_url)


@asynccontextmanager
async def lifespan(app: FastAPI):

    # Database health check
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    # Bootstrap database tables/columns
    if settings.bootstrap_db_on_startup:
        ensure_sellers_profile_columns(engine)
        ensure_products_table(engine)
        ensure_snapshot_logs_table(engine)

    await _setup_telegram_webhook()

    # Start websocket/socket manager
    socket_manager = getattr(app.state, "socket_manager", None)

    if socket_manager:
        await socket_manager.start()

    try:
        yield

    finally:

        # Shutdown websocket manager
        if socket_manager:
            await socket_manager.shutdown()


def create_app() -> FastAPI:

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )

    # CORS configuration
    origins = settings.cors_origins
    if "*" in origins:
        raise RuntimeError(
            "CORS_ORIGINS cannot include '*' when allow_credentials=True. "
            "Use an explicit comma-separated list of origins."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
    )

    # Global exception handlers
    register_exception_handlers(app)

    # Main API routers
    register_routers(app)

    # Initialize Socket.IO manager
    app.state.socket_manager = init_socketio(app)

    return app


app = create_app()
