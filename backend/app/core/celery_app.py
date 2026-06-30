from __future__ import annotations

import os
from typing import Final

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

DEFAULT_REDIS_URL: Final = "redis://localhost:6379/0"


def _resolve_redis_url() -> str:
    return os.getenv("REDIS_URL") or settings.redis_broker_url or DEFAULT_REDIS_URL


redis_url = _resolve_redis_url()

celery_app = Celery(
    settings.app_name,
    broker=redis_url,
    backend=redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_expires=60 * 60,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

celery_app.autodiscover_tasks(["app.tasks"])

beat_schedule = {}
if settings.scraper_schedule_enabled:
    beat_schedule.update(
        {
            "scraper_every_6_hours": {
                "task": "scraper.run_periodic_scrape",
                "schedule": crontab(minute=0, hour="*/6"),
            },
            "scraper_nightly_refresh": {
                "task": "scraper.run_nightly_refresh",
                "schedule": crontab(minute=0, hour=2),
            },
        }
    )
if settings.inventory_intelligence_schedule_enabled:
    beat_schedule["inventory_intelligence_daily"] = {
        "task": "inventory_intelligence.daily_workflow",
        "schedule": crontab(
            minute=settings.inventory_intelligence_daily_minute_utc,
            hour=settings.inventory_intelligence_daily_hour_utc,
        ),
    }

celery_app.conf.beat_schedule = beat_schedule
