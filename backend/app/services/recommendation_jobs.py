from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.recommendation_job import (
    ACTIVE_JOBS,
    RecommendationJob,
    RecommendationJobRequest,
)

logger = logging.getLogger(__name__)

JOB_TASK = "analytics.run_recommendation_job"
JOB_LIFETIME = timedelta(minutes=15)
ATTEMPT_TIMEOUT = 120
LEASE = timedelta(seconds=180)
DISPATCH_DELAY = timedelta(seconds=30)
MAX_ATTEMPTS = 3
ERROR_MESSAGES = {
    "generation_expired": "Generation did not finish in time. Please try again.",
    "worker_interrupted": "Generation was interrupted. Please try again.",
    "product_not_found": "Product not found.",
    "competitor_data_missing": "Fresh competitor evidence is unavailable. Refresh competitor data and try again.",
    "analytics_failure": "The available product data could not support a recommendation.",
    "ai_generation_failed": "The recommendation provider could not complete the request. Please try again.",
    "storage_unavailable": "The recommendation could not be saved. Please try again.",
    "generation_failed": "Recommendation generation failed. Please try again.",
}


@dataclass(frozen=True)
class JobAttempt:
    job_id: UUID
    seller_id: UUID
    product_id: UUID
    scrape_run_id: UUID | None
    number: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RecommendationJobs:
    def __init__(self, db: Session) -> None:
        self.db = db

    def for_request(
        self, seller_id: UUID, product_id: UUID, key: UUID
    ) -> RecommendationJob | None:
        return self.db.scalar(
            select(RecommendationJob)
            .join(
                RecommendationJobRequest,
                RecommendationJobRequest.job_id == RecommendationJob.id,
            )
            .where(
                RecommendationJobRequest.seller_id == seller_id,
                RecommendationJobRequest.product_id == product_id,
                RecommendationJobRequest.request_key == key,
                RecommendationJob.seller_id == seller_id,
                RecommendationJob.product_id == product_id,
            )
        )

    def create(
        self,
        seller_id: UUID,
        product_id: UUID,
        scrape_run_id: UUID | None,
        request_key: UUID | None,
        *,
        existing_only: bool = False,
    ) -> RecommendationJob | None:
        # Serialize admission only. No broker or external calls hold this lock.
        owned_product = self.db.scalar(
            select(Product.id)
            .where(
                Product.id == product_id,
                Product.seller_id == seller_id,
            )
            .with_for_update()
        )
        if owned_product is None:
            return None
        if request_key is not None:
            existing = self.for_request(seller_id, product_id, request_key)
            if existing is not None:
                self.db.commit()
                return existing
        now = _now()
        job = self.db.scalar(
            select(RecommendationJob)
            .where(
                RecommendationJob.seller_id == seller_id,
                RecommendationJob.product_id == product_id,
                RecommendationJob.status.in_(ACTIVE_JOBS),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is not None:
            self._expire(job, now)
        if job is None or job.status not in ACTIVE_JOBS:
            if existing_only:
                self.db.commit()
                return None
            self.db.flush()
            job = RecommendationJob(
                id=uuid4(),
                seller_id=seller_id,
                product_id=product_id,
                scrape_run_id=scrape_run_id,
                status="PENDING",
                created_at=now,
                deadline=now + JOB_LIFETIME,
                dispatch_after=now,
            )
            self.db.add(job)
        if request_key is not None:
            self.db.add(
                RecommendationJobRequest(
                    seller_id=seller_id,
                    product_id=product_id,
                    request_key=request_key,
                    job_id=job.id,
                )
            )
        self.db.commit()
        if not existing_only:
            logger.info(
                "recommendation_job_admitted job_id=%s seller_id=%s product_id=%s",
                job.id,
                seller_id,
                product_id,
            )
        return job

    def status(self, seller_id: UUID, job_id: UUID) -> RecommendationJob | None:
        return self.db.scalar(
            select(RecommendationJob)
            .join(Product, Product.id == RecommendationJob.product_id)
            .where(
                RecommendationJob.id == job_id,
                RecommendationJob.seller_id == seller_id,
                Product.seller_id == seller_id,
            )
            .execution_options(populate_existing=True)
        )

    def latest(self, seller_id: UUID, product_id: UUID) -> RecommendationJob | None:
        return self.db.scalar(
            select(RecommendationJob)
            .join(Product, Product.id == RecommendationJob.product_id)
            .where(
                RecommendationJob.product_id == product_id,
                RecommendationJob.seller_id == seller_id,
                Product.seller_id == seller_id,
            )
            .order_by(RecommendationJob.created_at.desc(), RecommendationJob.id.desc())
            .limit(1)
        )

    def dispatch(self, job_id: UUID) -> None:
        from app.core.celery_app import celery_app
        from kombu.exceptions import OperationalError  # type: ignore[import-untyped]

        job = self._lock(job_id)
        now = _now()
        due = job is not None and self._due(job, now)
        self.db.commit()
        if not due:
            return
        try:
            celery_app.send_task(
                JOB_TASK, args=[str(job_id)], task_id=str(job_id), retry=False
            )
        except (OperationalError, OSError):
            # The DB reservation is recoverable even if publish succeeded
            # without an acknowledgement, or if the publisher died.
            logger.warning(
                "recommendation_job_publish_failed job_id=%s", job_id, exc_info=True
            )

    def recover(self, limit: int = 50) -> int:
        now = _now()
        ids = list(
            self.db.scalars(
                select(RecommendationJob.id)
                .where(
                    RecommendationJob.status.in_(ACTIVE_JOBS),
                    (RecommendationJob.dispatch_after <= now)
                    | (RecommendationJob.deadline <= now),
                )
                .order_by(RecommendationJob.dispatch_after)
                .limit(limit)
            )
        )
        self.db.commit()
        for job_id in ids:
            self.dispatch(job_id)
        return len(ids)

    def claim(self, job_id: UUID) -> JobAttempt | None:
        job = self._lock(job_id)
        now = _now()
        if job is None or job.status not in ACTIVE_JOBS:
            self.db.commit()
            return None
        self._expire(job, now)
        if (
            job.status == "FAILED"
            or (
                job.status == "RUNNING"
                and job.lease_until is not None
                and job.lease_until > now
            )
            or (job.retry_after is not None and job.retry_after > now)
        ):
            self.db.commit()
            return None
        owner = self.db.scalar(
            select(Product.seller_id).where(Product.id == job.product_id)
        )
        if owner != job.seller_id:
            self._fail(job, now, "product_not_found")
            self.db.commit()
            return None
        job.status = "RUNNING"
        job.retry_after = None
        job.attempts += 1
        job.started_at = job.started_at or now
        job.lease_until = min(now + LEASE, job.deadline)
        job.dispatch_after = job.lease_until
        attempt = JobAttempt(
            job.id, job.seller_id, job.product_id, job.scrape_run_id, job.attempts
        )
        self.db.commit()
        return attempt

    def can_complete(self, attempt: JobAttempt) -> bool:
        owner = self.db.scalar(
            select(Product.seller_id)
            .where(
                Product.id == attempt.product_id,
            )
            .with_for_update(read=True)
        )
        if owner != attempt.seller_id:
            return False
        job = self._current_attempt(attempt)
        return (
            job is not None and job.lease_until is not None and job.lease_until > _now()
        )

    def complete(self, attempt: JobAttempt, recommendation_id: UUID) -> bool:
        job = self._current_attempt(attempt)
        now = _now()
        if job is None or job.lease_until is None or job.lease_until <= now:
            return False
        job.status = "COMPLETED"
        job.recommendation_id = recommendation_id
        job.completed_at = now
        job.lease_until = None
        job.error_code = None
        return True

    def record_failure(
        self, attempt: JobAttempt, code: str, *, transient: bool
    ) -> None:
        self.db.rollback()
        job = self._current_attempt(attempt)
        now = _now()
        if job is not None:
            if job.deadline <= now:
                self._fail(job, now, "generation_expired")
            elif (
                transient
                and job.attempts < MAX_ATTEMPTS
                and now + DISPATCH_DELAY < job.deadline
            ):
                job.status = "PENDING"
                job.lease_until = None
                job.retry_after = now + DISPATCH_DELAY
                job.dispatch_after = job.retry_after
                job.error_code = code
            else:
                self._fail(job, now, code)
        self.db.commit()
        logger.info(
            "recommendation_job_attempt_failed job_id=%s attempt=%s code=%s transient=%s",
            attempt.job_id,
            attempt.number,
            code,
            transient,
        )

    def _lock(self, job_id: UUID) -> RecommendationJob | None:
        return self.db.scalar(
            select(RecommendationJob)
            .where(
                RecommendationJob.id == job_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _current_attempt(self, attempt: JobAttempt) -> RecommendationJob | None:
        job = self._lock(attempt.job_id)
        if job is not None and (
            job.status,
            job.attempts,
            job.seller_id,
            job.product_id,
        ) == ("RUNNING", attempt.number, attempt.seller_id, attempt.product_id):
            return job
        return None

    def _due(self, job: RecommendationJob, now: datetime) -> bool:
        self._expire(job, now)
        if job.status not in ACTIVE_JOBS or job.dispatch_after > now:
            return False
        if job.status == "RUNNING":
            job.status = "PENDING"
            job.lease_until = None
        job.dispatch_after = now + DISPATCH_DELAY
        return True

    @staticmethod
    def _expire(job: RecommendationJob, now: datetime) -> None:
        if job.status not in ACTIVE_JOBS:
            return
        if job.deadline <= now:
            RecommendationJobs._fail(job, now, "generation_expired")
        elif (
            job.attempts >= MAX_ATTEMPTS
            and job.lease_until is not None
            and job.lease_until <= now
        ):
            RecommendationJobs._fail(job, now, "worker_interrupted")

    @staticmethod
    def _fail(job: RecommendationJob, now: datetime, code: str) -> None:
        job.status = "FAILED"
        job.completed_at = now
        job.lease_until = None
        job.retry_after = None
        job.error_code = code
