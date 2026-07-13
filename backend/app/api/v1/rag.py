from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.product import Product
from app.models.rag_index_outbox import RagIndexOutbox, RagIndexOutboxStatus
from app.models.rag_memory import RagMemoryChunk, RagMemoryDocument, RagMemoryEmbeddingStatus
from app.models.seller import Seller
from app.schemas.rag_memory import RagAskRequest, RagAskResponse, RagErrorResponse
from app.services.rag_answer_service import RagAnswerService
from app.services.rag_memory_source_registry import RAG_SOURCE_REGISTRY
from app.services.copilot.observability import rag_quality_snapshot

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post(
    "/ask",
    response_model=RagAskResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": RagErrorResponse},
        403: {"model": RagErrorResponse},
        500: {"model": RagErrorResponse},
    },
)
async def ask_rag_memory(
    payload: RagAskRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> RagAskResponse | JSONResponse:
    if not settings.rag_enabled:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=RagErrorResponse(
                detail="RAG memory is not enabled.",
                error_code="rag_disabled",
            ).model_dump(),
        )
    if payload.product_id is not None and not _seller_owns_product(
        db,
        seller_id=current_seller.id,
        product_id=payload.product_id,
    ):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=RagErrorResponse(
                detail="Product is not available for this seller.",
                error_code="product_not_owned",
            ).model_dump(),
        )
    try:
        result = await RagAnswerService(db).answer_question(
            seller_id=current_seller.id,
            user_id=current_seller.id,
            question=payload.question,
            product_id=payload.product_id,
            source_types=payload.source_types,
            from_event_time=payload.from_event_time,
            to_event_time=payload.to_event_time,
            top_k=payload.top_k,
            min_similarity=payload.min_similarity,
            include_stale=payload.include_stale,
        )
        return RagAskResponse.model_validate(result.to_dict())
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=RagErrorResponse(
                detail="Could not answer from RAG memory right now.",
                error_code="rag_answer_failed",
            ).model_dump(),
        )


@router.get("/coverage")
def get_rag_coverage(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> dict:
    return _coverage_payload(db, seller_id=current_seller.id)


@router.get("/health")
def get_rag_health(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> dict:
    payload = _coverage_payload(db, seller_id=current_seller.id)
    return {
        "status": "ok",
        "retrieval_quality": rag_quality_snapshot(),
        **payload,
    }


def _coverage_payload(db: Session, *, seller_id) -> dict:
    outbox_rows = db.execute(
        select(RagIndexOutbox.source_type, RagIndexOutbox.status, func.count())
        .where(RagIndexOutbox.seller_id == seller_id)
        .group_by(RagIndexOutbox.source_type, RagIndexOutbox.status)
    ).all()
    outbox_by_source: dict[object, dict[str, int]] = {}
    for source_type, outbox_status, count in outbox_rows:
        source_counts = outbox_by_source.setdefault(source_type, {})
        source_counts[getattr(outbox_status, "value", str(outbox_status))] = int(count)
    outbox_counts = {
        getattr(status, "value", str(status)).lower(): count
        for status, count in db.execute(
            select(RagIndexOutbox.status, func.count())
            .where(RagIndexOutbox.seller_id == seller_id)
            .group_by(RagIndexOutbox.status)
        ).all()
    }
    last_processing = db.execute(
        select(func.max(RagIndexOutbox.processed_at)).where(
            RagIndexOutbox.seller_id == seller_id,
            RagIndexOutbox.status == RagIndexOutboxStatus.COMPLETED,
        )
    ).scalar_one_or_none()
    sources = []
    stale_sources = []
    unimplemented_sources = []
    for source_type, definition in RAG_SOURCE_REGISTRY.items():
        source_records = _source_record_count(db, seller_id=seller_id, definition=definition)
        memory_documents = _count_documents(db, seller_id=seller_id, source_type=source_type)
        embedded_chunks = _count_chunks(db, seller_id=seller_id, source_type=source_type)
        failed = _count_documents(db, seller_id=seller_id, source_type=source_type, status=RagMemoryEmbeddingStatus.FAILED)
        stale = _count_documents(db, seller_id=seller_id, source_type=source_type, status=RagMemoryEmbeddingStatus.STALE)
        last_indexed = db.execute(
            select(func.max(RagMemoryDocument.updated_at)).where(
                RagMemoryDocument.seller_id == seller_id,
                RagMemoryDocument.source_type == source_type,
            )
        ).scalar_one_or_none()
        warnings = []
        if definition.implemented and not definition.adapter_function:
            warnings.append("missing_adapter")
        if definition.implemented and not definition.builder_function:
            warnings.append("missing_builder")
        if not definition.implemented:
            warnings.append(definition.coverage_status)
            unimplemented_sources.append(source_type.value)
        source_outbox = outbox_by_source.get(source_type, {})
        if stale > 0 or (source_records is not None and memory_documents < source_records):
            stale_sources.append(source_type.value)
        sources.append(
            {
                "source_type": source_type.value,
                "source_table": definition.source_table,
                "source_records": source_records,
                "memory_documents": memory_documents,
                "embedded_chunks": embedded_chunks,
                "failed": failed,
                "stale": stale,
                "coverage_percent": None if source_records is None else (100 if source_records == 0 else round((memory_documents / source_records) * 100, 2)),
                "last_indexed_time": _format_datetime(last_indexed),
                "implemented": definition.implemented,
                "warnings": warnings,
                "outbox": {
                    "pending": source_outbox.get(RagIndexOutboxStatus.PENDING.value, 0),
                    "processing": source_outbox.get(RagIndexOutboxStatus.PROCESSING.value, 0),
                    "failed": source_outbox.get(RagIndexOutboxStatus.FAILED.value, 0),
                    "dead_letter": source_outbox.get(RagIndexOutboxStatus.DEAD_LETTER.value, 0),
                },
            }
        )
    return {
        "sources": sources,
        "unimplemented_sources": unimplemented_sources,
        "stale_sources": stale_sources,
        "outbox": {
            "pending": outbox_counts.get("pending", 0),
            "processing": outbox_counts.get("processing", 0),
            "failed": outbox_counts.get("failed", 0),
            "dead_letter": outbox_counts.get("dead_letter", 0),
            "completed": outbox_counts.get("completed", 0),
            "last_successful_processing_time": _format_datetime(last_processing),
        },
    }


def _seller_owns_product(db: Session, *, seller_id, product_id) -> bool:
    return bool(
        db.execute(
            select(Product.id).where(
                Product.id == product_id,
                Product.seller_id == seller_id,
            )
        ).scalar_one_or_none()
    )


def _format_datetime(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _count_documents(db: Session, *, seller_id, source_type, status: RagMemoryEmbeddingStatus | None = None) -> int:
    statement = select(func.count()).select_from(RagMemoryDocument).where(
        RagMemoryDocument.seller_id == seller_id,
        RagMemoryDocument.source_type == source_type,
        RagMemoryDocument.deleted_at.is_(None),
    )
    if status is not None:
        statement = statement.where(RagMemoryDocument.embedding_status == status)
    return int(db.execute(statement).scalar_one() or 0)


def _count_chunks(db: Session, *, seller_id, source_type) -> int:
    return int(
        db.execute(
            select(func.count()).select_from(RagMemoryChunk).where(
                RagMemoryChunk.seller_id == seller_id,
                RagMemoryChunk.source_type == source_type,
                RagMemoryChunk.deleted_at.is_(None),
                RagMemoryChunk.embedding_status == RagMemoryEmbeddingStatus.EMBEDDED,
            )
        ).scalar_one() or 0
    )


def _source_record_count(db: Session, *, seller_id, definition) -> int | None:
    if not definition.implemented or not definition.model_name:
        return None
    model = _coverage_model(definition.model_name)
    if model is None:
        return None
    statement = select(func.count()).select_from(model)
    if definition.seller_field and hasattr(model, definition.seller_field):
        statement = statement.where(getattr(model, definition.seller_field) == seller_id)
    elif hasattr(model, "product_id"):
        statement = statement.join(Product, Product.id == model.product_id).where(Product.seller_id == seller_id)
    else:
        return None
    return int(db.execute(statement).scalar_one() or 0)


def _coverage_model(model_name: str):
    from app.models.alert import Alert
    from app.models.competitor_event import CompetitorEvent
    from app.models.copilot import CopilotMessage
    from app.models.dead_stock_assessment import DeadStockAssessment
    from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation
    from app.models.inventory_history import InventoryHistory
    from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
    from app.models.product_visibility_metric import ProductVisibilityMetric
    from app.models.recommendation import Recommendation
    from app.models.sales_record import SalesRecord

    return {
        "Alert": Alert,
        "CompetitorEvent": CompetitorEvent,
        "CopilotMessage": CopilotMessage,
        "DeadStockAssessment": DeadStockAssessment,
        "DynamicPricingRecommendation": DynamicPricingRecommendation,
        "InventoryHistory": InventoryHistory,
        "PricingAnalyticsSnapshot": PricingAnalyticsSnapshot,
        "Product": Product,
        "ProductVisibilityMetric": ProductVisibilityMetric,
        "Recommendation": Recommendation,
        "SalesRecord": SalesRecord,
    }.get(model_name)
