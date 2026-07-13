from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dead_stock_assessment import DeadStockVisibilityStatus
from app.models.product import Product
from app.models.product_visibility_metric import ProductVisibilityMetric
from app.models.rag_memory import RagMemorySourceType
from app.schemas.product_visibility_metric import ProductVisibilityMetricCreate, ProductVisibilityMetricResponse
from app.services.rag_index_outbox_service import RagIndexOutboxService


class ProductVisibilityService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, *, seller_id: UUID, product_id: UUID, payload: ProductVisibilityMetricCreate) -> ProductVisibilityMetricResponse:
        self._product_for_seller(seller_id=seller_id, product_id=product_id)
        record = ProductVisibilityMetric(
            seller_id=seller_id,
            product_id=product_id,
            marketplace=payload.marketplace,
            metric_date=payload.metric_date,
            impressions=payload.impressions,
            views=payload.views,
            clicks=payload.clicks,
            search_rank=payload.search_rank,
            listing_quality_score=payload.listing_quality_score,
            conversion_rate=payload.conversion_rate,
            source=payload.source,
            source_reference=payload.source_reference,
        )
        self._db.add(record)
        self._db.flush()
        RagIndexOutboxService(self._db).enqueue_upsert(
            seller_id=seller_id,
            source_type=RagMemorySourceType.SEO_VISIBILITY_HISTORY,
            source_id=str(record.id),
            product_id=product_id,
            source_updated_at=datetime.combine(payload.metric_date, time.min, tzinfo=timezone.utc),
        )
        self._db.commit()
        self._db.refresh(record)
        from app.tasks.dead_stock_workflow_tasks import enqueue_dead_stock_recalculation

        enqueue_dead_stock_recalculation(seller_id=seller_id, product_id=product_id, reason="visibility_metric_update")
        return self._response(record)

    def latest(self, *, seller_id: UUID, product_id: UUID) -> ProductVisibilityMetricResponse | None:
        self._product_for_seller(seller_id=seller_id, product_id=product_id)
        record = self._latest_record(seller_id=seller_id, product_id=product_id)
        return self._response(record) if record else None

    def history(self, *, seller_id: UUID, product_id: UUID, limit: int, offset: int) -> tuple[list[ProductVisibilityMetricResponse], int]:
        self._product_for_seller(seller_id=seller_id, product_id=product_id)
        statement = select(ProductVisibilityMetric).where(
            ProductVisibilityMetric.seller_id == seller_id,
            ProductVisibilityMetric.product_id == product_id,
        )
        total = len(self._db.execute(statement).scalars().all())
        items = self._db.execute(
            statement.order_by(ProductVisibilityMetric.metric_date.desc(), ProductVisibilityMetric.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return [self._response(item) for item in items], total

    def visibility_for_product(self, *, seller_id: UUID, product_id: UUID, as_of_date: date | None = None) -> dict | None:
        record = self._latest_record(seller_id=seller_id, product_id=product_id, as_of_date=as_of_date)
        return self.evidence(record) if record else None

    @classmethod
    def evidence(cls, record: ProductVisibilityMetric) -> dict:
        status, score = cls.evaluate(record)
        return {
            "status": status.value,
            "score": str(score) if score is not None else None,
            "impressions": record.impressions,
            "views": record.views,
            "clicks": record.clicks,
            "search_rank": record.search_rank,
            "listing_quality_score": str(record.listing_quality_score) if record.listing_quality_score is not None else None,
            "conversion_rate": str(record.conversion_rate) if record.conversion_rate is not None else None,
            "marketplace": record.marketplace,
            "metric_date": record.metric_date.isoformat(),
            "source": record.source,
        }

    @classmethod
    def evaluate(cls, record: ProductVisibilityMetric) -> tuple[DeadStockVisibilityStatus, Decimal | None]:
        score = _visibility_score(record)
        if score is None:
            return DeadStockVisibilityStatus.VISIBILITY_DATA_LIMITED, None
        if score <= Decimal(str(settings.dead_stock_low_visibility_threshold)):
            return DeadStockVisibilityStatus.LOW_VISIBILITY, score
        return DeadStockVisibilityStatus.NORMAL_VISIBILITY, score

    def _latest_record(self, *, seller_id: UUID, product_id: UUID, as_of_date: date | None = None) -> ProductVisibilityMetric | None:
        statement = select(ProductVisibilityMetric).where(
            ProductVisibilityMetric.seller_id == seller_id,
            ProductVisibilityMetric.product_id == product_id,
        )
        if as_of_date:
            statement = statement.where(ProductVisibilityMetric.metric_date <= as_of_date)
        return self._db.execute(
            statement.order_by(ProductVisibilityMetric.metric_date.desc(), ProductVisibilityMetric.created_at.desc(), ProductVisibilityMetric.id.desc()).limit(1)
        ).scalar_one_or_none()

    def _product_for_seller(self, *, seller_id: UUID, product_id: UUID) -> Product:
        product = self._db.execute(select(Product).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none()
        if product is None:
            raise ValueError("Product not found.")
        return product

    def _response(self, record: ProductVisibilityMetric) -> ProductVisibilityMetricResponse:
        status, score = self.evaluate(record)
        return ProductVisibilityMetricResponse(
            id=record.id,
            seller_id=record.seller_id,
            product_id=record.product_id,
            marketplace=record.marketplace,
            metric_date=record.metric_date,
            impressions=record.impressions,
            views=record.views,
            clicks=record.clicks,
            search_rank=record.search_rank,
            listing_quality_score=record.listing_quality_score,
            conversion_rate=record.conversion_rate,
            source=record.source,
            source_reference=record.source_reference,
            visibility_status=status.value,
            visibility_score=score,
            seo_recommendation_available=status == DeadStockVisibilityStatus.LOW_VISIBILITY,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


def _visibility_score(record: ProductVisibilityMetric) -> Decimal | None:
    if record.listing_quality_score is not None:
        return Decimal(str(record.listing_quality_score))
    if record.impressions > 0:
        ctr = Decimal(record.clicks) / Decimal(record.impressions)
        return min(Decimal("100"), ctr * Decimal("1000"))
    if record.views > 0:
        engagement = Decimal(record.clicks) / Decimal(record.views)
        return min(Decimal("100"), engagement * Decimal("500"))
    return None
