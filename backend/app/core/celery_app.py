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

# The project keeps tasks in multiple modules under ``app.tasks`` rather than
# in a single ``tasks.py`` module. Import the package explicitly so a worker
# started with this Celery application registers every task before it begins
# consuming messages.
import app.tasks  # noqa: E402,F401

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
if settings.dead_stock_workflow_schedule_enabled:
    beat_schedule["dead_stock_daily"] = {
        "task": "dead_stock.daily_workflow",
        "schedule": crontab(
            minute=settings.dead_stock_workflow_daily_minute_utc,
            hour=settings.dead_stock_workflow_daily_hour_utc,
        ),
    }
if settings.rag_memory_schedule_enabled:
    beat_schedule["rag_memory_daily_backfill"] = {
        "task": "rag_backfill_memory",
        "schedule": crontab(
            minute=settings.rag_memory_daily_minute_utc,
            hour=settings.rag_memory_daily_hour_utc,
        ),
    }
    beat_schedule["rag_memory_daily_embedding"] = {
        "task": "rag_embed_pending_chunks",
        "schedule": crontab(
            minute=(settings.rag_memory_daily_minute_utc + 15) % 60,
            hour=settings.rag_memory_daily_hour_utc,
        ),
    }
    beat_schedule["rag_memory_outbox_processing"] = {
        "task": "process_rag_index_outbox",
        "schedule": crontab(minute="*"),
    }
    beat_schedule["rag_memory_outbox_retry"] = {
        "task": "retry_failed_rag_index_events",
        "schedule": crontab(minute="*/5"),
    }
    beat_schedule["rag_memory_reconciliation"] = {
        "task": "reconcile_rag_memory_sources",
        "schedule": crontab(
            minute=(settings.rag_memory_daily_minute_utc + 30) % 60,
            hour=(settings.rag_memory_daily_hour_utc + 1) % 24,
        ),
    }

celery_app.conf.beat_schedule = beat_schedule
