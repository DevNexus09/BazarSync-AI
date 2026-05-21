from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import register_routers
from app.core.config import settings
from app.db.bootstrap import ensure_products_table, ensure_sellers_profile_columns
from app.db.session import engine
from app.scraper.browser import BrowserManager


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fail fast on startup if the database is unreachable or misconfigured.
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    if settings.bootstrap_db_on_startup:
        ensure_sellers_profile_columns(engine)
        ensure_products_table(engine)
    try:
        yield
    finally:
        await BrowserManager.shutdown_shared()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # Centralized CORS policy for React frontends and future domains.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_routers(app)
    return app


app = create_app()
