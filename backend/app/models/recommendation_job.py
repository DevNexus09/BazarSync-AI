from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ACTIVE_JOBS = ("PENDING", "RUNNING")
JobStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]


class RecommendationJob(Base):
    __tablename__ = "recommendation_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="ck_rec_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_rec_jobs_attempts"),
        CheckConstraint(
            "(status = 'RUNNING') = (lease_until IS NOT NULL)", name="ck_rec_jobs_lease"
        ),
        CheckConstraint(
            "(status IN ('COMPLETED', 'FAILED')) = (completed_at IS NOT NULL)",
            name="ck_rec_jobs_terminal",
        ),
        Index(
            "uq_rec_jobs_active_scope",
            "seller_id",
            "product_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING')"),
        ),
        Index("ix_rec_jobs_scope_created", "seller_id", "product_id", "created_at"),
        Index(
            "ix_rec_jobs_dispatch",
            "dispatch_after",
            postgresql_where=text("status IN ('PENDING', 'RUNNING')"),
        ),
    )

    # The job UUID is also the stable Celery task ID across dispatch attempts.
    id: Mapped[UUID] = mapped_column(primary_key=True)
    seller_id: Mapped[UUID] = mapped_column(
        ForeignKey("sellers.id", ondelete="CASCADE")
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE")
    )
    scrape_run_id: Mapped[UUID | None] = mapped_column()
    status: Mapped[JobStatus] = mapped_column(String(12))
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    recommendation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        unique=True,
    )


class RecommendationJobRequest(Base):
    """Bind each explicit request key to its job, including coalesced requests."""

    __tablename__ = "recommendation_job_requests"

    seller_id: Mapped[UUID] = mapped_column(primary_key=True)
    product_id: Mapped[UUID] = mapped_column(primary_key=True)
    request_key: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("recommendation_jobs.id", ondelete="CASCADE"), index=True
    )
