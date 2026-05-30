from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import register_routers
from app.api.v1.telegram import router as telegram_router

from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers

from app.db.bootstrap import (
    ensure_products_table,
    ensure_snapshot_logs_table,
    ensure_sellers_profile_columns,
)

from app.db.session import engine

from app.scraper.browser import BrowserManager

from app.websocket.socket_manager import init_socketio
import os

print("DEBUG DATABASE_URL:", os.environ.get("DATABASE_URL"))
print("ALL ENV KEYS:", list(os.environ.keys()))


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

        # Shutdown shared Playwright browser
        await BrowserManager.shutdown_shared()


def create_app() -> FastAPI:

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://bazar-sync-ai.vercel.app/",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

    # Global exception handlers
    register_exception_handlers(app)

    # Main API routers
    register_routers(app)

    # Telegram webhook router
    app.include_router(
        telegram_router,
        prefix="/api/v1/telegram",
        tags=["Telegram"],
    )

    # Initialize Socket.IO manager
    app.state.socket_manager = init_socketio(app)

    return app


app = create_app()
