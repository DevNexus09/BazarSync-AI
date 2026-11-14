from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, exists, func, select, true
from sqlalchemy.orm import Session

from app.models.competitor_event import CompetitorEvent, CompetitorEventType
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.product import Product, ProductStatus
from app.models.scrape_run import ScrapeRun
from app.scraper.constants import MARKETPLACE_NAME


class RefreshPolicy(BaseModel):
    normal_hours: int = Field(6, ge=1, le=168)
    volatile_hours: int = Field(3, ge=1, le=168)
    stable_hours: int = Field(12, ge=1, le=168)
    failure_hours: int = Field(12, ge=1, le=168)
    repeated_failures: int = Field(2, ge=2, le=10)
    stable_observations: int = Field(4, ge=2, le=20)
    change_window_days: int = Field(7, ge=1, le=90)
    volatile_changes: int = Field(3, ge=1, le=100)
    max_in_flight: int = Field(50, ge=1, le=10000)
    max_per_tick: int = Field(25, ge=1, le=10000)

    @model_validator(mode="after")
    def validate_intervals(self) -> RefreshPolicy:
        if not self.volatile_hours <= self.normal_hours <= self.stable_hours:
            raise ValueError("Refresh intervals must be ordered volatile, normal, stable.")
        return self


def adaptive_refresh_enabled() -> bool:
    return os.getenv("SCRAPER_ADAPTIVE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def refresh_policy() -> RefreshPolicy | None:
    if not adaptive_refresh_enabled():
        return None
    return RefreshPolicy.model_validate_json(os.getenv("SCRAPER_REFRESH_POLICY", "{}"))


@dataclass(frozen=True)
class RefreshCandidate:
    product_id: UUID
    seller_id: UUID
    last_success: datetime | None
    last_attempt: datetime | None
    failures: int
    changed_runs: int
    priced_runs: int


def due_at(candidate: RefreshCandidate, policy: RefreshPolicy) -> datetime | None:
    interval = policy.normal_hours
    if candidate.changed_runs >= policy.volatile_changes:
        interval = policy.volatile_hours
    elif candidate.changed_runs == 0 and candidate.priced_runs >= policy.stable_observations:
        interval = policy.stable_hours
    due = candidate.last_success + timedelta(hours=interval) if candidate.last_success else None
    if candidate.failures and candidate.last_attempt:
        delay = policy.failure_hours if candidate.failures >= policy.repeated_failures else policy.normal_hours
        retry_at = candidate.last_attempt + timedelta(hours=delay)
        return max(due, retry_at) if due else retry_at
    return due


def plan_refreshes(session: Session, policy: RefreshPolicy, now: datetime) -> list[RefreshCandidate]:
    active_run = (
        ScrapeRun.marketplace == MARKETPLACE_NAME,
        ScrapeRun.status.in_(("PENDING", "RUNNING")),
        ScrapeRun.celery_task_id.is_not(None),
    )
    workload = session.scalar(select(func.count()).select_from(ScrapeRun).where(*active_run)) or 0
    capacity = min(policy.max_per_tick, policy.max_in_flight - workload)
    if capacity <= 0:
        return []

    scope = (
        ScrapeRun.product_id == Product.id, ScrapeRun.seller_id == Product.seller_id,
        ScrapeRun.marketplace == MARKETPLACE_NAME,
    )
    terminal_time = func.coalesce(ScrapeRun.finished_at, ScrapeRun.completed_at, ScrapeRun.started_at, ScrapeRun.created_at)
    success = (
        select(terminal_time.label("last_success")).where(*scope, ScrapeRun.status == "COMPLETED")
        .order_by(terminal_time.desc()).limit(1).correlate(Product).lateral()
    )
    recent = (
        select(
            ScrapeRun.status, terminal_time.label("attempt"),
        ).where(*scope, ScrapeRun.status.in_(("COMPLETED", "FAILED", "PARTIAL")))
        .order_by(terminal_time.desc(), ScrapeRun.id.desc()).limit(policy.repeated_failures)
        .correlate(Product).subquery()
    )
    attempts = select(
        func.max(recent.c.attempt).label("last_attempt"),
        func.count().filter(and_(
            recent.c.status.in_(("FAILED", "PARTIAL")),
            (success.c.last_success.is_(None) | (recent.c.attempt >= success.c.last_success)),
        )).label("failures"),
    ).select_from(recent).correlate(success).lateral()
    window = now - timedelta(days=policy.change_window_days)
    priced_runs = (
        select(func.count()).select_from(ScrapeRun)
        .where(*scope, ScrapeRun.status == "COMPLETED", terminal_time >= window, exists(
            select(1).where(
                CompetitorSnapshot.scrape_run_id == ScrapeRun.id,
                CompetitorSnapshot.product_id == Product.id, CompetitorSnapshot.price.is_not(None),
            ).correlate(ScrapeRun, Product)
        )).correlate(Product).scalar_subquery()
    )
    changed_runs = (
        select(func.count(func.distinct(CompetitorEvent.scrape_run_id)))
        .join(ScrapeRun, ScrapeRun.id == CompetitorEvent.scrape_run_id)
        .where(
            *scope, ScrapeRun.status == "COMPLETED", CompetitorEvent.seller_id == Product.seller_id, CompetitorEvent.product_id == Product.id,
            CompetitorEvent.detected_at >= window,
            CompetitorEvent.event_type.in_((CompetitorEventType.PRICE_DROP, CompetitorEventType.PRICE_RISE)),
        ).correlate(Product).scalar_subquery()
    )
    statement = (
        select(Product.id, Product.seller_id, success.c.last_success, attempts.c.last_attempt,
               attempts.c.failures, changed_runs, priced_runs)
        .select_from(Product).outerjoin(success, true()).join(attempts, true())
        .where(Product.status == ProductStatus.ACTIVE, ~exists(
            select(1).where(*scope, *active_run).correlate(Product)
        ))
    )
    # Choose longest-overdue first. Observed price-change activity breaks ties.
    due = []
    for row in session.execute(statement):
        candidate = RefreshCandidate(*row)
        deadline = due_at(candidate, policy)
        if deadline is None or deadline <= now:
            due.append((deadline, candidate))
    earliest = datetime.min.replace(tzinfo=now.tzinfo)
    due.sort(key=lambda item: (item[0] or earliest, -item[1].changed_runs, item[1].product_id))
    return [candidate for _, candidate in due[:capacity]]
