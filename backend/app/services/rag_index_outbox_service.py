from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.rag_index_outbox import (
    RagIndexOutbox,
    RagIndexOutboxAction,
    RagIndexOutboxStatus,
)
from app.models.rag_memory import RagMemorySourceType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RagIndexOutboxCounts:
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    dead_letter: int = 0
    last_completed_at: datetime | None = None


class RagIndexOutboxService:
    """Manages durable RAG indexing work without owning source transactions."""

    def __init__(self, db: Session, *, log: logging.Logger | None = None) -> None:
        self._db = db
        self._log = log or logger

    def enqueue_upsert(
        self,
        *,
        seller_id: UUID,
        source_type: RagMemorySourceType | str,
        source_id: str,
        product_id: UUID | None = None,
        source_updated_at: datetime | None = None,
    ) -> RagIndexOutbox:
        return self._enqueue(
            seller_id=seller_id,
            source_type=source_type,
            source_id=source_id,
            product_id=product_id,
            action=RagIndexOutboxAction.UPSERT,
            source_updated_at=source_updated_at,
        )

    def enqueue_delete(
        self,
        *,
        seller_id: UUID,
        source_type: RagMemorySourceType | str,
        source_id: str,
        product_id: UUID | None = None,
        source_updated_at: datetime | None = None,
    ) -> RagIndexOutbox:
        return self._enqueue(
            seller_id=seller_id,
            source_type=source_type,
            source_id=source_id,
            product_id=product_id,
            action=RagIndexOutboxAction.DELETE,
            source_updated_at=source_updated_at,
        )

    def claim_batch(
        self,
        *,
        batch_size: int,
        seller_id: UUID | None = None,
        now: datetime | None = None,
        lease_seconds: int = 900,
        include_failed: bool = True,
    ) -> list[RagIndexOutbox]:
        if batch_size < 1:
            return []
        now = _utc(now or datetime.now(timezone.utc))
        retryable_statuses: tuple[RagIndexOutboxStatus, ...] = (RagIndexOutboxStatus.PENDING,)
        if include_failed:
            retryable_statuses = (*retryable_statuses, RagIndexOutboxStatus.FAILED)
        available = or_(
            RagIndexOutbox.status.in_(retryable_statuses),
            (RagIndexOutbox.status == RagIndexOutboxStatus.PROCESSING)
            & (RagIndexOutbox.next_attempt_at <= now),
        )
        statement = (
            select(RagIndexOutbox)
            .where(
                available,
                or_(RagIndexOutbox.next_attempt_at.is_(None), RagIndexOutbox.next_attempt_at <= now),
            )
            .order_by(RagIndexOutbox.created_at.asc(), RagIndexOutbox.id.asc())
            .limit(min(batch_size, 1000))
            .with_for_update(skip_locked=True)
        )
        if seller_id is not None:
            statement = statement.where(RagIndexOutbox.seller_id == seller_id)

        events = list(self._db.execute(statement).scalars().all())
        lease_until = now + timedelta(seconds=max(30, lease_seconds))
        for event in events:
            event.status = RagIndexOutboxStatus.PROCESSING
            event.attempts = int(event.attempts or 0) + 1
            event.next_attempt_at = lease_until
            event.last_error_code = None
            event.last_error_summary = None
        if events:
            self._db.commit()
        return events

    def mark_completed(self, event_id: UUID, *, processed_at: datetime | None = None) -> bool:
        event = self._db.get(RagIndexOutbox, event_id)
        if event is None:
            return False
        event.status = RagIndexOutboxStatus.COMPLETED
        event.processed_at = _utc(processed_at or datetime.now(timezone.utc))
        event.next_attempt_at = None
        event.last_error_code = None
        event.last_error_summary = None
        self._db.commit()
        return True

    def mark_failed(
        self,
        event_id: UUID,
        *,
        error_code: str,
        error_summary: str,
        max_attempts: int = 5,
        initial_backoff_seconds: int = 60,
        max_backoff_seconds: int = 3600,
    ) -> RagIndexOutboxStatus | None:
        event = self._db.get(RagIndexOutbox, event_id)
        if event is None:
            return None
        attempts = int(event.attempts or 0)
        event.last_error_code = _safe_error_code(error_code)
        event.last_error_summary = _safe_error_summary(error_summary)
        if attempts >= max(1, max_attempts):
            event.status = RagIndexOutboxStatus.DEAD_LETTER
            event.next_attempt_at = None
            event.processed_at = _utc(datetime.now(timezone.utc))
        else:
            event.status = RagIndexOutboxStatus.FAILED
            delay = min(
                max(1, max_backoff_seconds),
                max(1, initial_backoff_seconds) * (2 ** max(0, attempts - 1)),
            )
            event.next_attempt_at = _utc(datetime.now(timezone.utc)) + timedelta(seconds=delay)
        self._db.commit()
        return event.status

    def mark_dead_letter(
        self,
        event_id: UUID,
        *,
        error_code: str = "MAX_ATTEMPTS_EXCEEDED",
        error_summary: str = "RAG indexing event exceeded the retry limit.",
    ) -> bool:
        event = self._db.get(RagIndexOutbox, event_id)
        if event is None:
            return False
        event.status = RagIndexOutboxStatus.DEAD_LETTER
        event.next_attempt_at = None
        event.processed_at = _utc(datetime.now(timezone.utc))
        event.last_error_code = _safe_error_code(error_code)
        event.last_error_summary = _safe_error_summary(error_summary)
        self._db.commit()
        return True

    def counts(self, *, seller_id: UUID) -> RagIndexOutboxCounts:
        rows = self._db.execute(
            select(RagIndexOutbox.status, func.count())
            .where(RagIndexOutbox.seller_id == seller_id)
            .group_by(RagIndexOutbox.status)
        ).all()
        values = {status: int(count) for status, count in rows}
        last_completed = self._db.execute(
            select(func.max(RagIndexOutbox.processed_at)).where(
                RagIndexOutbox.seller_id == seller_id,
                RagIndexOutbox.status == RagIndexOutboxStatus.COMPLETED,
            )
        ).scalar_one_or_none()
        return RagIndexOutboxCounts(
            pending=values.get(RagIndexOutboxStatus.PENDING, 0),
            processing=values.get(RagIndexOutboxStatus.PROCESSING, 0),
            completed=values.get(RagIndexOutboxStatus.COMPLETED, 0),
            failed=values.get(RagIndexOutboxStatus.FAILED, 0),
            dead_letter=values.get(RagIndexOutboxStatus.DEAD_LETTER, 0),
            last_completed_at=last_completed,
        )

    def _enqueue(
        self,
        *,
        seller_id: UUID,
        source_type: RagMemorySourceType | str,
        source_id: str,
        product_id: UUID | None,
        action: RagIndexOutboxAction,
        source_updated_at: datetime | None,
    ) -> RagIndexOutbox:
        source_enum = _source_type(source_type)
        normalized_source_id = str(source_id).strip()
        if not normalized_source_id:
            raise ValueError("source_id is required for RAG indexing.")
        dedupe_key = _dedupe_key(
            seller_id=seller_id,
            source_type=source_enum,
            source_id=normalized_source_id,
            action=action,
            source_updated_at=source_updated_at,
        )
        try:
            existing = self._db.execute(
                select(RagIndexOutbox).where(RagIndexOutbox.dedupe_key == dedupe_key)
            ).scalar_one_or_none()
        except OperationalError as exc:
            if not _is_missing_outbox_table(exc) or self._db.bind is None or self._db.bind.dialect.name != "sqlite":
                raise
            # This compatibility path keeps older test/bootstrap schemas
            # usable while the migration is being rolled out. Production
            # deployments should always run the migration; reconciliation
            # repairs the missing event after the table becomes available.
            self._log.warning(
                "rag_index_outbox_table_missing seller_id=%s source_type=%s source_id=%s",
                seller_id,
                source_enum.value,
                normalized_source_id,
            )
            return RagIndexOutbox(
                seller_id=seller_id,
                source_type=source_enum,
                source_id=normalized_source_id,
                product_id=product_id,
                action=action,
                source_updated_at=_utc(source_updated_at) if source_updated_at else None,
                status=RagIndexOutboxStatus.PENDING,
                attempts=0,
                dedupe_key=dedupe_key,
            )
        if existing is not None:
            self._log.info(
                "rag_index_outbox_duplicate_skipped seller_id=%s source_type=%s source_id=%s action=%s",
                seller_id,
                source_enum.value,
                normalized_source_id,
                action.value,
            )
            return existing

        event = RagIndexOutbox(
            seller_id=seller_id,
            source_type=source_enum,
            source_id=normalized_source_id,
            product_id=product_id,
            action=action,
            source_updated_at=_utc(source_updated_at) if source_updated_at else None,
            status=RagIndexOutboxStatus.PENDING,
            attempts=0,
            dedupe_key=dedupe_key,
        )
        # No commit here: callers can include this row in the same transaction
        # as the business write that it describes.
        self._db.add(event)
        return event


def _source_type(value: RagMemorySourceType | str) -> RagMemorySourceType:
    return value if isinstance(value, RagMemorySourceType) else RagMemorySourceType(value)


def _dedupe_key(
    *,
    seller_id: UUID,
    source_type: RagMemorySourceType,
    source_id: str,
    action: RagIndexOutboxAction,
    source_updated_at: datetime | None,
) -> str:
    version = _utc(source_updated_at).isoformat() if source_updated_at else "none"
    return f"{seller_id}:{source_type.value}:{source_id}:{action.value}:{version}"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_error_code(value: str) -> str:
    cleaned = "".join(char for char in str(value).upper() if char.isalnum() or char in {"_", "-"})
    return cleaned[:80] or "RAG_INDEX_FAILED"


def _safe_error_summary(value: str) -> str:
    summary = " ".join(str(value).split())
    for secret_marker in ("token=", "api_key=", "password=", "authorization:"):
        if secret_marker in summary.lower():
            summary = summary[: summary.lower().index(secret_marker)].strip()
    return summary[:255] or "RAG indexing failed."


def _is_missing_outbox_table(error: OperationalError) -> bool:
    message = str(getattr(error, "orig", error)).lower()
    return "rag_index_outbox" in message and ("no such table" in message or "does not exist" in message)
