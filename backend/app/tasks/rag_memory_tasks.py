from __future__ import annotations

import logging
import hashlib
from datetime import datetime
from uuid import UUID

from celery.exceptions import Ignore
from celery import chain
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.rag_index_outbox import RagIndexOutboxAction
from app.models.rag_memory import RagMemorySourceType
from app.repositories.rag_memory_repository import RagMemoryRepository
from app.services.rag_embedding_service import RagEmbeddingService
from app.services.rag_memory_backfill_service import RagMemoryBackfillService
from app.services.rag_memory_source_registry import get_rag_source_definition
from app.services.rag_index_outbox_service import RagIndexOutboxService

logger = logging.getLogger(__name__)
_embedding_service: RagEmbeddingService | None = None


@celery_app.task(
    bind=True,
    name="rag_backfill_memory",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def rag_backfill_memory(
    self,
    *,
    seller_id: str | None = None,
    product_id: str | None = None,
    source_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    batch_size: int = 500,
    dry_run: bool = False,
) -> dict[str, int | str | bool | None]:
    del self
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
        source_enum = RagMemorySourceType(source_type) if source_type else None
        from_dt = datetime.fromisoformat(from_date) if from_date else None
        to_dt = datetime.fromisoformat(to_date) if to_date else None
    except ValueError as exc:
        logger.warning(
            "invalid_rag_memory_backfill_scope seller_id=%s product_id=%s source_type=%s from_date=%s to_date=%s",
            seller_id,
            product_id,
            source_type,
            from_date,
            to_date,
        )
        raise Ignore() from exc

    session = SessionLocal()
    lock_id = _lock_id(
        f"rag-backfill:{seller_id or 'all'}:{product_id or 'all'}:{source_type or 'all'}:{from_date or ''}:{to_date or ''}"
    )
    try:
        if not _try_advisory_lock(session, lock_id):
            logger.info("rag_backfill_memory_locked seller_id=%s product_id=%s source_type=%s", seller_id, product_id, source_type)
            return _locked_payload("rag_backfill_memory", seller_id=seller_id, product_id=product_id, source_type=source_type)
        result = RagMemoryBackfillService(session, log=logger).backfill(
            seller_id=seller_uuid,
            product_id=product_uuid,
            source_type=source_enum,
            from_date=from_dt,
            to_date=to_dt,
            batch_size=batch_size,
            dry_run=dry_run,
        )
        return {
            "created_count": result.created_count,
            "skipped_count": result.skipped_count,
            "updated_count": result.updated_count,
            "failed_count": result.failed_count,
            "dry_run_count": result.dry_run_count,
            "soft_deleted_count": result.soft_deleted_count,
            "unsupported_count": result.unsupported_count,
            "seller_id": seller_id,
            "product_id": product_id,
            "source_type": source_type,
            "from_date": from_date,
            "to_date": to_date,
            "dry_run": dry_run,
        }
    finally:
        _release_advisory_lock(session, lock_id)
        session.close()


backfill_rag_memory = rag_backfill_memory


@celery_app.task(
    bind=True,
    name="rag_embed_pending_chunks",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def rag_embed_pending_chunks(
    self,
    *,
    seller_id: str | None = None,
    source_type: str | None = None,
    limit: int | None = None,
    batch_size: int | None = None,
) -> dict[str, int | str | None]:
    del self
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        source_enum = RagMemorySourceType(source_type) if source_type else None
    except ValueError as exc:
        logger.warning("invalid_rag_embedding_scope seller_id=%s source_type=%s", seller_id, source_type)
        raise Ignore() from exc

    session = SessionLocal()
    lock_id = _lock_id(f"rag-embed:{seller_id or 'all'}:{source_type or 'all'}")
    try:
        if not _try_advisory_lock(session, lock_id):
            logger.info("rag_embed_pending_chunks_locked seller_id=%s source_type=%s", seller_id, source_type)
            return _locked_payload("rag_embed_pending_chunks", seller_id=seller_id, source_type=source_type)
        service = _get_embedding_service()
        result = service.embed_pending_chunks(
            repository=RagMemoryRepository(session),
            seller_id=seller_uuid,
            source_type=source_enum,
            limit=limit or batch_size,
        )
        searchable_count = RagMemoryRepository(session).count_searchable_chunks(
            seller_id=seller_uuid,
            source_type=source_enum,
        ) if seller_uuid else None
        logger.info(
            "rag_embedding_completed embedded=%s failed=%s dimension=%s model=%s seller_id=%s source_type=%s",
            result.embedded_count,
            result.failed_count,
            result.dimension,
            result.model,
            seller_id,
            source_type,
        )
        return {
            "embedded_count": result.embedded_count,
            "failed_count": result.failed_count,
            "dimension": result.dimension,
            "model": result.model,
            "seller_id": seller_id,
            "source_type": source_type,
            "searchable_count": searchable_count,
        }
    finally:
        _release_advisory_lock(session, lock_id)
        session.close()


embed_pending_rag_memory_chunks = rag_embed_pending_chunks


@celery_app.task(
    bind=True,
    name="process_rag_index_outbox",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def process_rag_index_outbox(
    self,
    *,
    seller_id: str | None = None,
    batch_size: int | None = None,
) -> dict[str, int | str | None]:
    del self
    return _process_rag_index_outbox_batch(
        seller_id=seller_id,
        batch_size=batch_size,
        include_failed=False,
    )


@celery_app.task(
    bind=True,
    name="retry_failed_rag_index_events",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def retry_failed_rag_index_events(
    self,
    *,
    seller_id: str | None = None,
    batch_size: int | None = None,
) -> dict[str, int | str | None]:
    del self
    return _process_rag_index_outbox_batch(
        seller_id=seller_id,
        batch_size=batch_size,
        include_failed=True,
    )


@celery_app.task(
    bind=True,
    name="reconcile_rag_memory_sources",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def reconcile_rag_memory_sources(
    self,
    *,
    seller_id: str | None = None,
    product_id: str | None = None,
    source_type: str | None = None,
    batch_size: int | None = None,
) -> dict[str, int | str | None]:
    del self
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
        source_enum = RagMemorySourceType(source_type) if source_type else None
    except ValueError as exc:
        logger.warning(
            "invalid_rag_memory_reconciliation_scope seller_id=%s product_id=%s source_type=%s",
            seller_id,
            product_id,
            source_type,
        )
        raise Ignore() from exc

    session = SessionLocal()
    lock_id = _lock_id(f"rag-reconcile:{seller_id or 'all'}:{product_id or 'all'}:{source_type or 'all'}")
    try:
        if not _try_advisory_lock(session, lock_id):
            logger.info(
                "rag_memory_reconciliation_locked seller_id=%s product_id=%s source_type=%s",
                seller_id,
                product_id,
                source_type,
            )
            return _locked_payload(
                "reconcile_rag_memory_sources",
                seller_id=seller_id,
                product_id=product_id,
                source_type=source_type,
            )
        result = RagMemoryBackfillService(session, log=logger).reconcile(
            seller_id=seller_uuid,
            product_id=product_uuid,
            source_type=source_enum,
            batch_size=batch_size or settings.rag_outbox_batch_size,
        )
        logger.info(
            "rag_memory_reconciliation_completed seller_id=%s product_id=%s source_type=%s created=%s updated=%s soft_deleted=%s failed=%s",
            seller_id,
            product_id,
            source_type,
            result.created_count,
            result.updated_count,
            result.soft_deleted_count,
            result.failed_count,
        )
        return {
            "created_count": result.created_count,
            "skipped_count": result.skipped_count,
            "updated_count": result.updated_count,
            "failed_count": result.failed_count,
            "soft_deleted_count": result.soft_deleted_count,
            "unsupported_count": result.unsupported_count,
            "seller_id": seller_id,
            "product_id": product_id,
            "source_type": source_type,
        }
    finally:
        _release_advisory_lock(session, lock_id)
        session.close()


def _process_rag_index_outbox_batch(
    *,
    seller_id: str | None,
    batch_size: int | None,
    include_failed: bool,
) -> dict[str, int | str | None]:
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
    except ValueError as exc:
        logger.warning("invalid_rag_index_outbox_scope seller_id=%s", seller_id)
        raise Ignore() from exc

    session = SessionLocal()
    lock_id = _lock_id(f"rag-outbox:{seller_id or 'all'}:{'retry' if include_failed else 'pending'}")
    processed = completed = failed = dead_letter = skipped = 0
    try:
        if not _try_advisory_lock(session, lock_id):
            logger.info("rag_index_outbox_locked seller_id=%s include_failed=%s", seller_id, include_failed)
            return _locked_payload("process_rag_index_outbox", seller_id=seller_id)
        service = RagIndexOutboxService(session, log=logger)
        events = service.claim_batch(
            batch_size=batch_size or settings.rag_outbox_batch_size,
            seller_id=seller_uuid,
            lease_seconds=settings.rag_outbox_processing_lease_seconds,
            include_failed=include_failed,
        )
        for event in events:
            processed += 1
            try:
                source_type = event.source_type
                if event.action == RagIndexOutboxAction.DELETE:
                    definition = get_rag_source_definition(source_type)
                    if definition.source_table:
                        RagMemoryBackfillService(session, log=logger).soft_delete_source(
                            seller_id=event.seller_id,
                            source_table=definition.source_table,
                            source_id=event.source_id,
                        )
                    else:
                        skipped += 1
                else:
                    result = RagMemoryBackfillService(session, log=logger).reindex_source_record(
                        seller_id=event.seller_id,
                        source_type=source_type,
                        source_id=event.source_id,
                    )
                    if result.failed_count:
                        raise RuntimeError("source_reindex_failed")
                    skipped += result.skipped_count
                    if result.soft_deleted_count:
                        logger.info(
                            "rag_index_outbox_missing_source_soft_deleted seller_id=%s source_type=%s source_id=%s count=%s",
                            event.seller_id,
                            source_type.value,
                            event.source_id,
                            result.soft_deleted_count,
                        )
                service.mark_completed(event.id)
                completed += 1
                logger.info(
                    "rag_index_outbox_event_completed seller_id=%s source_type=%s source_id=%s action=%s",
                    event.seller_id,
                    source_type.value,
                    event.source_id,
                    event.action.value,
                )
            except Exception as exc:
                session.rollback()
                status = RagIndexOutboxService(session, log=logger).mark_failed(
                    event.id,
                    error_code=type(exc).__name__,
                    error_summary="RAG source indexing failed.",
                    max_attempts=settings.rag_outbox_max_attempts,
                    initial_backoff_seconds=settings.rag_outbox_initial_backoff_seconds,
                    max_backoff_seconds=settings.rag_outbox_max_backoff_seconds,
                )
                failed += 1
                if status is not None and status.value == "DEAD_LETTER":
                    dead_letter += 1
                logger.exception(
                    "rag_index_outbox_event_failed seller_id=%s source_type=%s source_id=%s action=%s status=%s",
                    event.seller_id,
                    getattr(event.source_type, "value", event.source_type),
                    event.source_id,
                    getattr(event.action, "value", event.action),
                    getattr(status, "value", status),
                )
        return {
            "processed_count": processed,
            "completed_count": completed,
            "failed_count": failed,
            "dead_letter_count": dead_letter,
            "skipped_count": skipped,
            "seller_id": seller_id,
        }
    finally:
        _release_advisory_lock(session, lock_id)
        session.close()


@celery_app.task(
    bind=True,
    name="rag_reindex_source_record",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def rag_reindex_source_record(
    self,
    *,
    source_type: str,
    source_id: str,
    seller_id: str,
) -> dict[str, int | str | None]:
    del self
    try:
        seller_uuid = UUID(seller_id)
        source_enum = RagMemorySourceType(source_type)
    except ValueError as exc:
        logger.warning("invalid_rag_reindex_source_scope seller_id=%s source_type=%s source_id=%s", seller_id, source_type, source_id)
        raise Ignore() from exc

    session = SessionLocal()
    lock_id = _lock_id(f"rag-source:{seller_id}:{source_type}:{source_id}")
    try:
        if not _try_advisory_lock(session, lock_id):
            return _locked_payload("rag_reindex_source_record", seller_id=seller_id, source_type=source_type, source_id=source_id)
        result = RagMemoryBackfillService(session, log=logger).reindex_source_record(
            seller_id=seller_uuid,
            source_type=source_enum,
            source_id=source_id,
        )
        logger.info(
            "rag_reindex_completed seller_id=%s source_type=%s source_id=%s created=%s skipped=%s updated=%s failed=%s soft_deleted=%s",
            seller_id,
            source_type,
            source_id,
            result.created_count,
            result.skipped_count,
            result.updated_count,
            result.failed_count,
            result.soft_deleted_count,
        )
        return {
            "created_count": result.created_count,
            "skipped_count": result.skipped_count,
            "updated_count": result.updated_count,
            "failed_count": result.failed_count,
            "soft_deleted_count": result.soft_deleted_count,
            "seller_id": seller_id,
            "source_type": source_type,
            "source_id": source_id,
        }
    finally:
        _release_advisory_lock(session, lock_id)
        session.close()


@celery_app.task(
    bind=True,
    name="rag_full_reindex_for_seller",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def rag_full_reindex_for_seller(
    self,
    *,
    seller_id: str,
    product_id: str | None = None,
    source_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    batch_size: int = 500,
) -> dict[str, int | str | None]:
    del self
    try:
        seller_uuid = UUID(seller_id)
        product_uuid = UUID(product_id) if product_id else None
        source_enum = RagMemorySourceType(source_type) if source_type else None
        from_dt = datetime.fromisoformat(from_date) if from_date else None
        to_dt = datetime.fromisoformat(to_date) if to_date else None
    except ValueError as exc:
        logger.warning("invalid_rag_full_reindex_scope seller_id=%s product_id=%s source_type=%s", seller_id, product_id, source_type)
        raise Ignore() from exc

    session = SessionLocal()
    lock_id = _lock_id(f"rag-full:{seller_id}:{product_id or 'all'}:{source_type or 'all'}")
    try:
        if not _try_advisory_lock(session, lock_id):
            return _locked_payload("rag_full_reindex_for_seller", seller_id=seller_id, product_id=product_id, source_type=source_type)
        backfill_result = RagMemoryBackfillService(session, log=logger).backfill(
            seller_id=seller_uuid,
            product_id=product_uuid,
            source_type=source_enum,
            from_date=from_dt,
            to_date=to_dt,
            batch_size=batch_size,
        )
        embed_result = _get_embedding_service().embed_pending_chunks(
            repository=RagMemoryRepository(session),
            seller_id=seller_uuid,
            source_type=source_enum,
            limit=batch_size,
        )
        searchable_count = RagMemoryRepository(session).count_searchable_chunks(
            seller_id=seller_uuid,
            source_type=source_enum,
        )
        logger.info(
            "rag_full_reindex_completed seller_id=%s product_id=%s source_type=%s created=%s skipped=%s embedded=%s failed=%s searchable=%s",
            seller_id,
            product_id,
            source_type,
            backfill_result.created_count,
            backfill_result.skipped_count,
            embed_result.embedded_count,
            backfill_result.failed_count + embed_result.failed_count,
            searchable_count,
        )
        return {
            "created_count": backfill_result.created_count,
            "skipped_count": backfill_result.skipped_count,
            "updated_count": backfill_result.updated_count,
            "soft_deleted_count": backfill_result.soft_deleted_count,
            "embedded_count": embed_result.embedded_count,
            "failed_count": backfill_result.failed_count + embed_result.failed_count,
            "searchable_count": searchable_count,
            "seller_id": seller_id,
            "product_id": product_id,
            "source_type": source_type,
        }
    finally:
        _release_advisory_lock(session, lock_id)
        session.close()


def enqueue_rag_full_reindex_for_seller(
    *,
    seller_id: str,
    product_id: str | None = None,
    source_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    batch_size: int = 500,
):
    return chain(
        rag_backfill_memory.s(
            seller_id=seller_id,
            product_id=product_id,
            source_type=source_type,
            from_date=from_date,
            to_date=to_date,
            batch_size=batch_size,
        ),
        rag_embed_pending_chunks.si(
            seller_id=seller_id,
            source_type=source_type,
            batch_size=batch_size,
        ),
    ).apply_async()


def _get_embedding_service() -> RagEmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = RagEmbeddingService(log=logger)
    return _embedding_service


def _lock_id(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:15], 16)


def _try_advisory_lock(session, lock_id: int) -> bool:
    if session.bind is not None and session.bind.dialect.name != "postgresql":
        return True
    try:
        return bool(session.execute(select(func.pg_try_advisory_lock(lock_id))).scalar_one())
    except Exception:
        session.rollback()
        raise


def _release_advisory_lock(session, lock_id: int) -> None:
    if session.bind is not None and session.bind.dialect.name != "postgresql":
        return
    try:
        session.execute(select(func.pg_advisory_unlock(lock_id))).scalar_one_or_none()
    except Exception:
        session.rollback()


def _locked_payload(task_name: str, **extra) -> dict[str, int | str | None]:
    return {
        "task": task_name,
        "skipped_reason": "locked",
        "created_count": 0,
        "skipped_count": 0,
        "updated_count": 0,
        "embedded_count": 0,
        "failed_count": 0,
        **extra,
    }
