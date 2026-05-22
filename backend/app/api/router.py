from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.api.v1.auth import router as auth_router
from app.api.v1.competitors import router as competitors_router
from app.api.v1.health import router as health_router
from app.api.v1.products import router as products_router
from app.api.v1.recommendations import router as recommendations_router
from app.api.v1.scraper import router as scraper_router
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router)
api_router.include_router(competitors_router)
api_router.include_router(products_router)
api_router.include_router(recommendations_router)
api_router.include_router(scraper_router)


def register_routers(app: FastAPI) -> None:
    # Single registration point to keep route wiring predictable as modules grow.
    app.include_router(api_router, prefix=settings.api_v1_prefix)
