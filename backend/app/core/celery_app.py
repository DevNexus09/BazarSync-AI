from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from celery import Celery


def build_celery_app() -> "Celery":
    # Celery is not installed yet; this stub defines the integration point.
    from celery import Celery  # type: ignore[import-not-found]

    if not settings.redis_broker_url:
        raise RuntimeError("REDIS_BROKER_URL is required to initialize Celery.")

    return Celery(
        settings.app_name,
        broker=settings.redis_broker_url,
        backend=settings.redis_broker_url,
        include=["app.services.tasks"],
    )
