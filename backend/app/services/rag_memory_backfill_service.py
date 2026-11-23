from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.alert import Alert
from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.competitor_event import CompetitorEvent
from app.models.copilot import CopilotConversation, CopilotMessage
from app.models.dead_stock_assessment import DeadStockAssessment
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryRecommendation
from app.models.demand_elasticity_estimate import DemandElasticityEstimate
from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.inventory_risk import InventoryRiskAssessment
from app.models.inventory_stock_in import InventoryStockIn
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
from app.models.pricing_policy import PricingPolicy
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory
from app.models.product_visibility_metric import ProductVisibilityMetric
from app.models.promotion import PromotionPlan, PromotionResult
from app.models.rag_memory import RagMemoryDocument, RagMemorySourceType
from app.models.recommendation import Recommendation
from app.models.reorder_recommendation import ReorderRecommendation
from app.models.sales_record import SalesRecord
from app.models.sales_velocity import SalesVelocity
from app.models.stockout_prediction import StockoutPrediction
from app.models.telegram_connection import SellerTelegramConnection
from app.models.telegram_inventory_alert import TelegramInventoryAlert
from app.models.telegram_snapshot_log import TelegramProductSnapshotLog
from app.repositories.rag_memory_repository import RagMemoryRepository
from app.schemas.rag_memory import RagMemoryDocumentCreate
from app.services.rag_chunking_service import RagChunkingService
from app.services.rag_memory_document_builder import RagMemoryBuildError, RagMemoryDocumentBuilder
from app.services.rag_memory_source_registry import get_rag_source_definition, implemented_source_types
from app.services.rag_observability import increment_metric, log_event

# Conversations created by scripts/copilot_eval.py carry this metadata_json.source.
EVAL_CONVERSATION_SOURCE = "copilot_eval"

logger = logging.getLogger(__name__)


_RECONCILIATION_MODELS: dict[RagMemorySourceType, Any] = {
    RagMemorySourceType.PRODUCT_PROFILE: Product,
    RagMemorySourceType.SALES_HISTORY: SalesRecord,
    RagMemorySourceType.COMPETITOR_HISTORY: CompetitorEvent,
    RagMemorySourceType.PRICE_HISTORY: DynamicPricingRecommendation,
    RagMemorySourceType.PRICING_HISTORY: PricingAnalyticsSnapshot,
    RagMemorySourceType.SELLER_PRICE_HISTORY: ProductPriceHistory,
    RagMemorySourceType.INVENTORY_HISTORY: InventoryHistory,
    RagMemorySourceType.INVENTORY_LIFECYCLE: InventoryHistory,
    RagMemorySourceType.ALERT: Alert,
    RagMemorySourceType.ALERT_HISTORY: AlertDeliveryLog,
    RagMemorySourceType.PROMOTION_PLAN: PromotionPlan,
    RagMemorySourceType.PROMOTION_RESULT: PromotionResult,
    RagMemorySourceType.DEAD_STOCK: DeadStockAssessment,
    RagMemorySourceType.DEAD_STOCK_HISTORY: DeadStockAssessment,
    RagMemorySourceType.SEO: ProductVisibilityMetric,
    RagMemorySourceType.SEO_VISIBILITY_HISTORY: ProductVisibilityMetric,
    RagMemorySourceType.COPILOT_HISTORY: CopilotMessage,
}


@dataclass(slots=True)
class RagMemoryBackfillResult:
    created_count: int = 0
    skipped_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    dry_run_count: int = 0
    soft_deleted_count: int = 0
    unsupported_count: int = 0


class RagMemoryBackfillService:
    def __init__(
        self,
        db: Session,
        *,
        repository: RagMemoryRepository | None = None,
        builder: RagMemoryDocumentBuilder | None = None,
        chunker: RagChunkingService | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._repository = repository or RagMemoryRepository(db)
        self._builder = builder or RagMemoryDocumentBuilder()
        self._chunker = chunker or RagChunkingService()
        self._log = log or logger

    def backfill(
        self,
        *,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        source_type: RagMemorySourceType | str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        batch_size: int = 500,
        dry_run: bool = False,
    ) -> RagMemoryBackfillResult:
        source_types = self._source_types(source_type)
        result = RagMemoryBackfillResult()
        if source_type is not None and not source_types:
            result.unsupported_count = 1
            return result
        for current_type in source_types:
            try:
                handler = self._handler_for(current_type)
            except RagMemoryBuildError:
                self._log.warning("rag_memory_source_unsupported source_type=%s", current_type.value)
                result.unsupported_count += 1
                continue
            partial = handler(
                seller_id=seller_id,
                product_id=product_id,
                from_date=from_date,
                to_date=to_date,
                batch_size=batch_size,
                dry_run=dry_run,
            )
            _merge(result, partial)
        self._log.info(
            "rag_memory_backfill_completed created=%s skipped=%s updated=%s failed=%s dry_run=%s soft_deleted=%s unsupported=%s seller_id=%s product_id=%s source_type=%s",
            result.created_count,
            result.skipped_count,
            result.updated_count,
            result.failed_count,
            result.dry_run_count,
            result.soft_deleted_count,
            result.unsupported_count,
            seller_id,
            product_id,
            getattr(source_type, "value", source_type),
        )
        return result

    def soft_delete_source(
        self,
        *,
        seller_id: UUID,
        source_table: str,
        source_id: str,
    ) -> int:
        count = self._repository.soft_delete_by_source(
            seller_id=seller_id,
            source_table=source_table,
            source_id=source_id,
        )
        self._log.info(
            "rag_memory_source_soft_deleted seller_id=%s source_table=%s source_id=%s count=%s",
            seller_id,
            source_table,
            source_id,
            count,
        )
        return count

    def reconcile(
        self,
        *,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        source_type: RagMemorySourceType | str | None = None,
        batch_size: int = 500,
    ) -> RagMemoryBackfillResult:
        """Rebuild current hashes and tombstone documents for missing source rows.

        Normal backfill already compares content hashes and source timestamps
        while it processes current rows. This method adds the complementary
        missing-row check for sources whose model has a stable one-row adapter.
        Composite sources are intentionally left to their dedicated backfill
        handlers rather than guessing which source table row was deleted.
        """
        result = self.backfill(
            seller_id=seller_id,
            product_id=product_id,
            source_type=source_type,
            batch_size=batch_size,
        )
        requested_types = self._source_types(source_type)
        for current_type in requested_types:
            model = _RECONCILIATION_MODELS.get(current_type)
            definition = get_rag_source_definition(current_type)
            if model is None or not definition.source_table:
                continue
            try:
                source_statement = select(model.id)
                if hasattr(model, "seller_id"):
                    source_statement = source_statement.where(model.seller_id == seller_id) if seller_id is not None else source_statement
                elif hasattr(model, "product_id"):
                    source_statement = source_statement.join(Product, Product.id == model.product_id)
                    if seller_id is not None:
                        source_statement = source_statement.where(Product.seller_id == seller_id)
                if product_id is not None and hasattr(model, "product_id"):
                    source_statement = source_statement.where(model.product_id == product_id)
                source_ids = {str(value) for value in self._db.execute(source_statement).scalars().all()}

                document_statement = select(RagMemoryDocument.source_id).where(
                    RagMemoryDocument.source_type == current_type,
                    RagMemoryDocument.source_table == definition.source_table,
                    RagMemoryDocument.deleted_at.is_(None),
                )
                if seller_id is not None:
                    document_statement = document_statement.where(RagMemoryDocument.seller_id == seller_id)
                if product_id is not None:
                    document_statement = document_statement.where(RagMemoryDocument.product_id == product_id)
                document_ids = set(self._db.execute(document_statement).scalars().all())
                missing_ids = document_ids - source_ids
                if not missing_ids:
                    continue
                missing_statement = (
                    update(RagMemoryDocument)
                    .where(
                        RagMemoryDocument.source_type == current_type,
                        RagMemoryDocument.source_table == definition.source_table,
                        RagMemoryDocument.source_id.in_(missing_ids),
                        RagMemoryDocument.deleted_at.is_(None),
                    )
                    .values(deleted_at=func.now(), updated_at=func.now())
                )
                if seller_id is not None:
                    missing_statement = missing_statement.where(RagMemoryDocument.seller_id == seller_id)
                if product_id is not None:
                    missing_statement = missing_statement.where(RagMemoryDocument.product_id == product_id)
                result.soft_deleted_count += int(getattr(self._db.execute(missing_statement), "rowcount", 0) or 0)
                self._db.commit()
            except Exception:
                self._db.rollback()
                result.failed_count += 1
                self._log.exception(
                    "rag_memory_reconciliation_source_failed seller_id=%s source_type=%s",
                    seller_id,
                    current_type.value,
                )
        return result

    def reindex_source_record(
        self,
        *,
        seller_id: UUID,
        source_type: RagMemorySourceType | str,
        source_id: str,
        dry_run: bool = False,
    ) -> RagMemoryBackfillResult:
        source_enum = source_type if isinstance(source_type, RagMemorySourceType) else RagMemorySourceType(source_type)
        result = RagMemoryBackfillResult()
        try:
            document = self._build_single_source_document(
                seller_id=seller_id,
                source_type=source_enum,
                source_id=source_id,
            )
            if document is None:
                definition = get_rag_source_definition(source_enum)
                if definition.source_table:
                    result.soft_deleted_count += self.soft_delete_source(
                        seller_id=seller_id,
                        source_table=definition.source_table,
                        source_id=source_id,
                    )
                result.skipped_count += 1
                return result
            self._persist_document(document, result=result, dry_run=dry_run)
        except Exception:
            result.failed_count += 1
            self._log.exception(
                "rag_memory_reindex_source_failed seller_id=%s source_type=%s source_id=%s",
                seller_id,
                source_enum.value,
                source_id,
            )
        return result

    def _backfill_competitor_history(self, **kwargs) -> RagMemoryBackfillResult:
        seller_id = kwargs["seller_id"]
        product_id = kwargs["product_id"]
        statement = (
            select(CompetitorEvent)
            .options(
                selectinload(CompetitorEvent.product),
                selectinload(CompetitorEvent.competitor),
                selectinload(CompetitorEvent.market_opportunity),
            )
            .order_by(CompetitorEvent.detected_at.asc(), CompetitorEvent.id.asc())
        )
        statement = _scope(statement, CompetitorEvent, seller_id=seller_id, product_id=product_id)
        statement = _date_range(statement, CompetitorEvent.detected_at, kwargs["from_date"], kwargs["to_date"])
        return self._process_statement(
            statement=statement,
            build=self._builder.build_from_competitor_event,
            batch_size=kwargs["batch_size"],
            dry_run=kwargs["dry_run"],
        )

    def _backfill_price_history(self, **kwargs) -> RagMemoryBackfillResult:
        seller_id = kwargs["seller_id"]
        product_id = kwargs["product_id"]
        statement = (
            select(DynamicPricingRecommendation)
            .options(selectinload(DynamicPricingRecommendation.product))
            .order_by(DynamicPricingRecommendation.generated_at.asc(), DynamicPricingRecommendation.id.asc())
        )
        statement = _scope(statement, DynamicPricingRecommendation, seller_id=seller_id, product_id=product_id)
        statement = _date_range(
            statement,
            DynamicPricingRecommendation.generated_at,
            kwargs["from_date"],
            kwargs["to_date"],
        )
        return self._process_statement(
            statement=statement,
            build=self._builder.build_from_pricing_recommendation,
            batch_size=kwargs["batch_size"],
            dry_run=kwargs["dry_run"],
        )

    def _backfill_inventory_history(self, **kwargs) -> RagMemoryBackfillResult:
        seller_id = kwargs["seller_id"]
        product_id = kwargs["product_id"]
        result = RagMemoryBackfillResult()
        statement = (
            select(InventoryHistory)
            .options(selectinload(InventoryHistory.product))
            .order_by(InventoryHistory.captured_at.asc(), InventoryHistory.id.asc())
        )
        statement = _scope(statement, InventoryHistory, seller_id=seller_id, product_id=product_id)
        statement = _date_range(statement, InventoryHistory.captured_at, kwargs["from_date"], kwargs["to_date"])

        for batch in self._iter_batches(statement, kwargs["batch_size"]):
            product_ids = sorted({row.product_id for row in batch})
            velocities = _latest_by_product(self._db, SalesVelocity, product_ids, seller_id=seller_id)
            stockouts = _latest_by_product(self._db, StockoutPrediction, product_ids, seller_id=seller_id)
            reorders = _latest_by_product(self._db, ReorderRecommendation, product_ids, seller_id=seller_id)
            risks = _latest_by_product(self._db, InventoryRiskAssessment, product_ids, seller_id=seller_id)
            for row in batch:
                try:
                    document = self._builder.build_from_inventory_snapshot_or_risk(
                        row,
                        risk_assessment=risks.get(row.product_id),
                        sales_velocity=velocities.get(row.product_id),
                        stockout_prediction=stockouts.get(row.product_id),
                        reorder_recommendation=reorders.get(row.product_id),
                    )
                    self._persist_document(document, result=result, dry_run=kwargs["dry_run"])
                except Exception:
                    result.failed_count += 1
                    self._log.exception("rag_memory_inventory_document_failed source_id=%s", row.id)
        return result

    def _backfill_recommendations(self, **kwargs) -> RagMemoryBackfillResult:
        result = RagMemoryBackfillResult()
        seller_id = kwargs["seller_id"]
        product_id = kwargs["product_id"]
        statement = (
            select(Recommendation)
            .options(selectinload(Recommendation.product))
            .order_by(Recommendation.created_at.asc(), Recommendation.id.asc())
        )
        if seller_id is not None:
            statement = statement.join(Product, Recommendation.product_id == Product.id).where(Product.seller_id == seller_id)
        if product_id is not None:
            statement = statement.where(Recommendation.product_id == product_id)
        statement = _date_range(statement, Recommendation.created_at, kwargs["from_date"], kwargs["to_date"])
        _merge(
            result,
            self._process_statement(
                statement=statement,
                build=self._builder.build_from_recommendation,
                batch_size=kwargs["batch_size"],
                dry_run=kwargs["dry_run"],
            ),
        )

        reorder_statement = (
            select(ReorderRecommendation)
            .options(selectinload(ReorderRecommendation.product))
            .order_by(ReorderRecommendation.generated_at.asc(), ReorderRecommendation.id.asc())
        )
        reorder_statement = _scope(reorder_statement, ReorderRecommendation, seller_id=seller_id, product_id=product_id)
        reorder_statement = _date_range(
            reorder_statement,
            ReorderRecommendation.generated_at,
            kwargs["from_date"],
            kwargs["to_date"],
        )
        _merge(
            result,
            self._process_statement(
                statement=reorder_statement,
                build=self._builder.build_from_reorder_recommendation,
                batch_size=kwargs["batch_size"],
                dry_run=kwargs["dry_run"],
            ),
        )

        dead_stock_statement = (
            select(DeadStockRecoveryRecommendation)
            .options(selectinload(DeadStockRecoveryRecommendation.product))
            .order_by(DeadStockRecoveryRecommendation.generated_at.asc(), DeadStockRecoveryRecommendation.id.asc())
        )
        dead_stock_statement = _scope(
            dead_stock_statement,
            DeadStockRecoveryRecommendation,
            seller_id=seller_id,
            product_id=product_id,
        )
        dead_stock_statement = _date_range(
            dead_stock_statement,
            DeadStockRecoveryRecommendation.generated_at,
            kwargs["from_date"],
            kwargs["to_date"],
        )
        _merge(
            result,
            self._process_statement(
                statement=dead_stock_statement,
                build=self._builder.build_from_dead_stock_recovery_recommendation,
                batch_size=kwargs["batch_size"],
                dry_run=kwargs["dry_run"],
            ),
        )
        return result

    def _backfill_alerts(self, **kwargs) -> RagMemoryBackfillResult:
        result = RagMemoryBackfillResult()
        seller_id = kwargs["seller_id"]
        product_id = kwargs["product_id"]
        alert_statement = (
            select(Alert)
            .options(selectinload(Alert.product))
            .order_by(Alert.created_at.asc(), Alert.id.asc())
        )
        alert_statement = _scope(alert_statement, Alert, seller_id=seller_id, product_id=product_id)
        alert_statement = _date_range(alert_statement, Alert.created_at, kwargs["from_date"], kwargs["to_date"])
        _merge(
            result,
            self._process_statement(
                statement=alert_statement,
                build=self._builder.build_from_alert,
                batch_size=kwargs["batch_size"],
                dry_run=kwargs["dry_run"],
            ),
        )

        telegram_statement = (
            select(TelegramInventoryAlert)
            .options(selectinload(TelegramInventoryAlert.product))
            .order_by(TelegramInventoryAlert.created_at.asc(), TelegramInventoryAlert.id.asc())
        )
        telegram_statement = _scope(telegram_statement, TelegramInventoryAlert, seller_id=seller_id, product_id=product_id)
        telegram_statement = _date_range(
            telegram_statement,
            TelegramInventoryAlert.created_at,
            kwargs["from_date"],
            kwargs["to_date"],
        )
        _merge(
            result,
            self._process_statement(
                statement=telegram_statement,
                build=self._builder.build_from_telegram_inventory_alert,
                batch_size=kwargs["batch_size"],
                dry_run=kwargs["dry_run"],
            ),
        )
        return result

    def _backfill_seller_price_history(self, **kwargs) -> RagMemoryBackfillResult:
        statement = (
            select(ProductPriceHistory)
            .options(selectinload(ProductPriceHistory.product))
            .order_by(ProductPriceHistory.changed_at.asc(), ProductPriceHistory.id.asc())
        )
        statement = _scope(statement, ProductPriceHistory, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"])
        statement = _date_range(statement, ProductPriceHistory.changed_at, kwargs["from_date"], kwargs["to_date"])
        return self._process_statement(
            statement=statement,
            build=self._builder.build_from_seller_price_history,
            batch_size=kwargs["batch_size"],
            dry_run=kwargs["dry_run"],
        )

    def _backfill_promotion_plans(self, **kwargs) -> RagMemoryBackfillResult:
        statement = (
            select(PromotionPlan)
            .options(selectinload(PromotionPlan.product))
            .order_by(PromotionPlan.updated_at.asc(), PromotionPlan.id.asc())
        )
        statement = _scope(statement, PromotionPlan, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"])
        statement = _date_range(statement, PromotionPlan.updated_at, kwargs["from_date"], kwargs["to_date"])
        return self._process_statement(
            statement=statement,
            build=self._builder.build_from_promotion_plan,
            batch_size=kwargs["batch_size"],
            dry_run=kwargs["dry_run"],
        )

    def _backfill_promotion_results(self, **kwargs) -> RagMemoryBackfillResult:
        statement = (
            select(PromotionResult)
            .options(selectinload(PromotionResult.product), selectinload(PromotionResult.promotion_plan))
            .order_by(PromotionResult.started_at.asc(), PromotionResult.id.asc())
        )
        statement = _scope(statement, PromotionResult, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"])
        statement = _date_range(statement, PromotionResult.started_at, kwargs["from_date"], kwargs["to_date"])
        return self._process_statement(
            statement=statement,
            build=self._builder.build_from_promotion_result,
            batch_size=kwargs["batch_size"],
            dry_run=kwargs["dry_run"],
        )

    def _backfill_product_profiles(self, **kwargs) -> RagMemoryBackfillResult:
        statement = select(Product).order_by(Product.created_at.asc(), Product.id.asc())
        statement = _scope(statement, Product, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"])
        statement = _date_range(statement, Product.created_at, kwargs["from_date"], kwargs["to_date"])
        return self._process_statement(statement=statement, build=self._builder.build_from_product_profile, batch_size=kwargs["batch_size"], dry_run=kwargs["dry_run"])

    def _backfill_sales_history(self, **kwargs) -> RagMemoryBackfillResult:
        statement = select(SalesRecord).options(selectinload(SalesRecord.product)).order_by(SalesRecord.sold_at.asc(), SalesRecord.id.asc())
        statement = _scope(statement, SalesRecord, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"])
        statement = _date_range(statement, SalesRecord.sold_at, kwargs["from_date"], kwargs["to_date"])
        return self._process_statement(statement=statement, build=self._builder.build_from_sales_record, batch_size=kwargs["batch_size"], dry_run=kwargs["dry_run"])

    def _backfill_sales_revenue_summary(self, **kwargs) -> RagMemoryBackfillResult:
        seller_id = kwargs["seller_id"]
        if seller_id is None:
            result = RagMemoryBackfillResult()
            result.unsupported_count = 1
            return result
        statement = select(SalesRecord).options(selectinload(SalesRecord.product)).where(SalesRecord.seller_id == seller_id)
        if kwargs["product_id"] is not None:
            statement = statement.where(SalesRecord.product_id == kwargs["product_id"])
        statement = _date_range(statement, SalesRecord.sold_at, kwargs["from_date"], kwargs["to_date"])
        rows = self._db.execute(statement.order_by(SalesRecord.sold_at.asc(), SalesRecord.id.asc())).scalars().all()
        valid = [row for row in rows if getattr(row, "status", None) in {"COMPLETED", "FULFILLED"} or getattr(getattr(row, "status", None), "value", None) in {"COMPLETED", "FULFILLED"}]
        units = sum(max(0, int(getattr(row, "quantity_sold", 0) or 0) - int(getattr(row, "returned_units", 0) or 0) - int(getattr(row, "refunded_restocked_units", 0) or 0)) for row in valid if not getattr(row, "is_test_order", False))
        revenue = Decimal("0")
        missing_transaction_price = False
        for row in valid:
            if getattr(row, "is_test_order", False):
                continue
            unit_price = getattr(row, "unit_price", None)
            line_total = getattr(row, "line_total", None)
            if line_total is not None:
                revenue += Decimal(str(line_total))
                continue
            if unit_price is None:
                missing_transaction_price = True
                continue
            net_units = max(0, int(getattr(row, "quantity_sold", 0) or 0) - int(getattr(row, "returned_units", 0) or 0) - int(getattr(row, "refunded_restocked_units", 0) or 0))
            revenue += Decimal(str(unit_price)) * Decimal(net_units)
        summary = {
            "id": f"{seller_id}:{kwargs['from_date'] or 'all'}:{kwargs['to_date'] or 'all'}:{kwargs['product_id'] or 'all'}",
            "seller_id": seller_id,
            "from_date": kwargs["from_date"],
            "to_date": kwargs["to_date"],
            "units_sold": units,
            "order_count": len(valid),
            "revenue": revenue if not missing_transaction_price else None,
            "trend": "not_calculated",
            "top_products": "not_calculated",
            "missing_data": "MISSING_TRANSACTION_PRICE" if missing_transaction_price else "none",
            "completeness_status": "UNKNOWN",
        }
        result = RagMemoryBackfillResult()
        self._persist_document(self._builder.build_from_sales_revenue_summary(summary), result=result, dry_run=kwargs["dry_run"])
        return result

    def _backfill_inventory_lifecycle(self, **kwargs) -> RagMemoryBackfillResult:
        result = self._backfill_inventory_history(**kwargs)
        for model, builder, date_column in (
            (InventoryStockIn, self._builder.build_from_inventory_lifecycle, InventoryStockIn.received_at),
            (InventoryAgingSnapshot, self._builder.build_from_inventory_lifecycle, InventoryAgingSnapshot.calculated_at),
            (SalesVelocity, self._builder.build_from_inventory_lifecycle, SalesVelocity.calculated_at),
            (StockoutPrediction, self._builder.build_from_inventory_lifecycle, StockoutPrediction.calculated_at),
            (InventoryRiskAssessment, self._builder.build_from_inventory_lifecycle, InventoryRiskAssessment.assessed_at),
            (ReorderRecommendation, self._builder.build_from_reorder_recommendation, ReorderRecommendation.generated_at),
        ):
            statement = select(model).options(selectinload(model.product)).order_by(date_column.asc(), model.id.asc())
            statement = _scope(statement, model, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"])
            statement = _date_range(statement, date_column, kwargs["from_date"], kwargs["to_date"])
            _merge(result, self._process_statement(statement=statement, build=builder, batch_size=kwargs["batch_size"], dry_run=kwargs["dry_run"]))
        return result

    def _backfill_pricing_history(self, **kwargs) -> RagMemoryBackfillResult:
        result = RagMemoryBackfillResult()
        for model, builder, date_column in (
            (PricingAnalyticsSnapshot, self._builder.build_from_pricing_history, PricingAnalyticsSnapshot.calculated_at),
            (DynamicPricingRecommendation, self._builder.build_from_pricing_recommendation, DynamicPricingRecommendation.generated_at),
            (PricingPolicy, self._builder.build_from_pricing_history, PricingPolicy.effective_from),
            (MarketplaceFeePolicy, self._builder.build_from_pricing_history, MarketplaceFeePolicy.effective_from),
            (DemandElasticityEstimate, self._builder.build_from_pricing_history, DemandElasticityEstimate.calculated_at),
        ):
            statement = select(model)
            if hasattr(model, "product"):
                statement = statement.options(selectinload(model.product))
            statement = statement.order_by(date_column.asc(), model.id.asc())
            statement = _scope(statement, model, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"])
            statement = _date_range(statement, date_column, kwargs["from_date"], kwargs["to_date"])
            _merge(result, self._process_statement(statement=statement, build=builder, batch_size=kwargs["batch_size"], dry_run=kwargs["dry_run"]))
        return result

    def _backfill_dead_stock_history(self, **kwargs) -> RagMemoryBackfillResult:
        result = RagMemoryBackfillResult()
        for model, date_column in (
            (InventoryAgingSnapshot, InventoryAgingSnapshot.calculated_at),
            (DeadStockAssessment, DeadStockAssessment.assessed_at),
            (DeadStockRecoveryRecommendation, DeadStockRecoveryRecommendation.generated_at),
            (DeadStockCapitalRecoveryEstimate, DeadStockCapitalRecoveryEstimate.calculated_at),
        ):
            statement = select(model).options(selectinload(model.product)).order_by(date_column.asc(), model.id.asc())
            statement = _scope(statement, model, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"])
            statement = _date_range(statement, date_column, kwargs["from_date"], kwargs["to_date"])
            _merge(result, self._process_statement(statement=statement, build=self._builder.build_from_dead_stock_history, batch_size=kwargs["batch_size"], dry_run=kwargs["dry_run"]))
        return result

    def _backfill_seo_visibility_history(self, **kwargs) -> RagMemoryBackfillResult:
        statement = select(ProductVisibilityMetric).options(selectinload(ProductVisibilityMetric.product)).order_by(ProductVisibilityMetric.metric_date.asc(), ProductVisibilityMetric.id.asc())
        statement = _scope(statement, ProductVisibilityMetric, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"])
        statement = _date_range(statement, ProductVisibilityMetric.metric_date, kwargs["from_date"], kwargs["to_date"])
        return self._process_statement(statement=statement, build=self._builder.build_from_visibility_metric, batch_size=kwargs["batch_size"], dry_run=kwargs["dry_run"])

    def _backfill_alert_history(self, **kwargs) -> RagMemoryBackfillResult:
        result = self._backfill_alerts(**kwargs)
        for model, builder, date_column in (
            (AlertDeliveryLog, self._builder.build_from_alert_history, AlertDeliveryLog.created_at),
            (SellerTelegramConnection, self._builder.build_from_alert_history, SellerTelegramConnection.updated_at),
            (TelegramProductSnapshotLog, self._builder.build_from_alert_history, TelegramProductSnapshotLog.sent_at),
        ):
            statement = select(model).order_by(date_column.asc(), model.id.asc())
            if hasattr(model, "product"):
                statement = statement.options(selectinload(model.product))
            statement = _scope(statement, model, seller_id=kwargs["seller_id"], product_id=kwargs["product_id"] if hasattr(model, "product_id") else None)
            statement = _date_range(statement, date_column, kwargs["from_date"], kwargs["to_date"])
            _merge(result, self._process_statement(statement=statement, build=builder, batch_size=kwargs["batch_size"], dry_run=kwargs["dry_run"]))
        return result

    def _backfill_recommendation_history(self, **kwargs) -> RagMemoryBackfillResult:
        result = self._backfill_recommendations(**kwargs)
        _merge(result, self._backfill_price_history(**kwargs))
        return result

    def _backfill_copilot_history(self, **kwargs) -> RagMemoryBackfillResult:
        statement = _copilot_history_statement(seller_id=kwargs["seller_id"], from_date=kwargs["from_date"], to_date=kwargs["to_date"])
        return self._process_statement(statement=statement, build=self._builder.build_from_copilot_history, batch_size=kwargs["batch_size"], dry_run=kwargs["dry_run"])

    def _build_single_source_document(
        self,
        *,
        seller_id: UUID,
        source_type: RagMemorySourceType,
        source_id: str,
    ) -> RagMemoryDocumentCreate | None:
        if source_type == RagMemorySourceType.COMPETITOR_HISTORY:
            row = self._db.get(CompetitorEvent, UUID(source_id))
            if row is None or row.seller_id != seller_id:
                return None
            return self._builder.build_from_competitor_event(row)
        if source_type == RagMemorySourceType.PRICE_HISTORY:
            row = self._db.get(DynamicPricingRecommendation, UUID(source_id))
            if row is None or row.seller_id != seller_id:
                return None
            return self._builder.build_from_pricing_recommendation(row)
        if source_type == RagMemorySourceType.INVENTORY_HISTORY:
            row = self._db.get(InventoryHistory, UUID(source_id))
            if row is None or row.seller_id != seller_id:
                return None
            velocity = _latest_by_product(self._db, SalesVelocity, [row.product_id], seller_id=seller_id).get(row.product_id)
            stockout = _latest_by_product(self._db, StockoutPrediction, [row.product_id], seller_id=seller_id).get(row.product_id)
            reorder = _latest_by_product(self._db, ReorderRecommendation, [row.product_id], seller_id=seller_id).get(row.product_id)
            risk = _latest_by_product(self._db, InventoryRiskAssessment, [row.product_id], seller_id=seller_id).get(row.product_id)
            return self._builder.build_from_inventory_snapshot_or_risk(
                row,
                risk_assessment=risk,
                sales_velocity=velocity,
                stockout_prediction=stockout,
                reorder_recommendation=reorder,
            )
        if source_type == RagMemorySourceType.RECOMMENDATION:
            for model, builder in (
                (Recommendation, self._builder.build_from_recommendation),
                (ReorderRecommendation, self._builder.build_from_reorder_recommendation),
                (DeadStockRecoveryRecommendation, self._builder.build_from_dead_stock_recovery_recommendation),
            ):
                row = self._db.get(model, UUID(source_id))
                if row is not None and _seller_id_for_row(row) == seller_id:
                    return builder(row)
            return None
        if source_type == RagMemorySourceType.ALERT:
            for model, builder in (
                (Alert, self._builder.build_from_alert),
                (TelegramInventoryAlert, self._builder.build_from_telegram_inventory_alert),
            ):
                row = self._db.get(model, UUID(source_id))
                if row is not None and row.seller_id == seller_id:
                    return builder(row)
            return None
        if source_type == RagMemorySourceType.PROMOTION_RESULT:
            self._log.warning("rag_memory_promotion_result_reindex_no_persisted_source source_id=%s", source_id)
            return None
        single_adapters = {
            RagMemorySourceType.PRODUCT_PROFILE: (Product, self._builder.build_from_product_profile),
            RagMemorySourceType.SALES_HISTORY: (SalesRecord, self._builder.build_from_sales_record),
            RagMemorySourceType.PRICING_HISTORY: (PricingAnalyticsSnapshot, self._builder.build_from_pricing_history),
            RagMemorySourceType.INVENTORY_LIFECYCLE: (InventoryHistory, self._builder.build_from_inventory_lifecycle),
            RagMemorySourceType.DEAD_STOCK: (DeadStockAssessment, self._builder.build_from_dead_stock_history),
            RagMemorySourceType.DEAD_STOCK_HISTORY: (DeadStockAssessment, self._builder.build_from_dead_stock_history),
            RagMemorySourceType.SEO: (ProductVisibilityMetric, self._builder.build_from_visibility_metric),
            RagMemorySourceType.SEO_VISIBILITY_HISTORY: (ProductVisibilityMetric, self._builder.build_from_visibility_metric),
            RagMemorySourceType.COPILOT_HISTORY: (CopilotMessage, self._builder.build_from_copilot_history),
        }
        if source_type in single_adapters:
            model, builder = single_adapters[source_type]
            row = self._db.get(model, UUID(source_id))
            if row is None or _seller_id_for_row(row) != seller_id:
                return None
            return builder(row)
        raise RagMemoryBuildError(f"No reindex adapter for {source_type.value}")

    def _process_statement(self, *, statement: Select, build, batch_size: int, dry_run: bool) -> RagMemoryBackfillResult:
        result = RagMemoryBackfillResult()
        for batch in self._iter_batches(statement, batch_size):
            for row in batch:
                try:
                    document = build(row)
                    self._persist_document(document, result=result, dry_run=dry_run)
                except Exception:
                    result.failed_count += 1
                    self._log.exception("rag_memory_document_failed row_type=%s", type(row).__name__)
        return result

    def _iter_batches(self, statement: Select, batch_size: int):
        offset = 0
        while True:
            rows = self._db.execute(statement.limit(batch_size).offset(offset)).scalars().all()
            if not rows:
                break
            yield rows
            offset += batch_size

    def _persist_document(
        self,
        document: RagMemoryDocumentCreate,
        *,
        result: RagMemoryBackfillResult,
        dry_run: bool,
    ) -> None:
        if dry_run:
            result.dry_run_count += 1
            return
        existing = self._repository.get_by_source(
            seller_id=document.seller_id,
            source_table=document.source_table,
            source_id=document.source_id,
            source_version=document.source_version,
        )
        if existing and existing.content_hash == document.content_hash:
            if self._repository.count_chunks_for_document(existing.id) == 0:
                self._repository.create_chunks(self._chunker.chunk_document(existing))
            result.skipped_count += 1
            return
        if existing:
            self._repository.mark_stale(
                seller_id=document.seller_id,
                source_table=document.source_table,
                source_id=document.source_id,
            )
            result.soft_deleted_count += self._repository.soft_delete_by_source(
                seller_id=document.seller_id,
                source_table=document.source_table,
                source_id=document.source_id,
            )
            result.updated_count += 1
        created_document, created = self._repository.create_memory_document(document)
        if created:
            chunks = self._repository.create_chunks(self._chunker.chunk_document(created_document))
            increment_metric("rag_documents_total")
            increment_metric("rag_chunks_total", len(chunks))
            log_event(
                self._log,
                logging.INFO,
                "rag_memory_document_created",
                seller_id=created_document.seller_id,
                document_id=created_document.id,
                source_type=created_document.source_type.value,
                source_table=created_document.source_table,
                source_id=created_document.source_id,
            )
            log_event(
                self._log,
                logging.INFO,
                "rag_memory_chunks_created",
                seller_id=created_document.seller_id,
                document_id=created_document.id,
                chunk_count=len(chunks),
            )
            if not existing:
                result.created_count += 1
        else:
            result.skipped_count += 1

    def _source_types(self, source_type: RagMemorySourceType | str | None) -> list[RagMemorySourceType]:
        if source_type is None:
            return implemented_source_types()
        if isinstance(source_type, RagMemorySourceType):
            return [source_type]
        try:
            return [RagMemorySourceType(source_type)]
        except ValueError:
            self._log.warning("rag_memory_source_unsupported source_type=%s", source_type)
            return []

    def _handler_for(self, source_type: RagMemorySourceType):
        definition = get_rag_source_definition(source_type)
        if not definition.implemented:
            raise RagMemoryBuildError(f"Source type is not implemented: {source_type.value}")
        handlers = {
            RagMemorySourceType.PRODUCT_PROFILE: self._backfill_product_profiles,
            RagMemorySourceType.SALES_HISTORY: self._backfill_sales_history,
            RagMemorySourceType.SALES_REVENUE_SUMMARY: self._backfill_sales_revenue_summary,
            RagMemorySourceType.COMPETITOR_HISTORY: self._backfill_competitor_history,
            RagMemorySourceType.PRICE_HISTORY: self._backfill_price_history,
            RagMemorySourceType.PRICING_HISTORY: self._backfill_pricing_history,
            RagMemorySourceType.SELLER_PRICE_HISTORY: self._backfill_seller_price_history,
            RagMemorySourceType.INVENTORY_HISTORY: self._backfill_inventory_history,
            RagMemorySourceType.INVENTORY_LIFECYCLE: self._backfill_inventory_lifecycle,
            RagMemorySourceType.RECOMMENDATION: self._backfill_recommendations,
            RagMemorySourceType.RECOMMENDATION_HISTORY: self._backfill_recommendation_history,
            RagMemorySourceType.ALERT: self._backfill_alerts,
            RagMemorySourceType.ALERT_HISTORY: self._backfill_alert_history,
            RagMemorySourceType.DEAD_STOCK: self._backfill_dead_stock_history,
            RagMemorySourceType.DEAD_STOCK_HISTORY: self._backfill_dead_stock_history,
            RagMemorySourceType.SEO: self._backfill_seo_visibility_history,
            RagMemorySourceType.SEO_VISIBILITY_HISTORY: self._backfill_seo_visibility_history,
            RagMemorySourceType.COPILOT_HISTORY: self._backfill_copilot_history,
            RagMemorySourceType.PROMOTION_PLAN: self._backfill_promotion_plans,
            RagMemorySourceType.PROMOTION_RESULT: self._backfill_promotion_results,
        }
        try:
            return handlers[source_type]
        except KeyError as exc:
            raise RagMemoryBuildError(f"No adapter implemented for {source_type.value}") from exc


def _copilot_history_statement(*, seller_id: UUID | None, from_date: datetime | None, to_date: datetime | None) -> Select:
    # Offline eval conversations (scripts/copilot_eval.py) are not the seller's history; indexing
    # them would feed past test answers back to the Copilot as memory.
    eval_conversations = select(CopilotConversation.id).where(CopilotConversation.metadata_json["source"].astext == EVAL_CONVERSATION_SOURCE)
    statement = (
        select(CopilotMessage)
        .where(CopilotMessage.conversation_id.not_in(eval_conversations))
        .order_by(CopilotMessage.created_at.asc(), CopilotMessage.id.asc())
    )
    statement = _scope(statement, CopilotMessage, seller_id=seller_id, product_id=None)
    return _date_range(statement, CopilotMessage.created_at, from_date, to_date)


def _scope(statement: Select, model, *, seller_id: UUID | None, product_id: UUID | None) -> Select:
    if seller_id is not None:
        statement = statement.where(model.seller_id == seller_id)
    if product_id is not None:
        statement = statement.where(model.product_id == product_id)
    return statement


def _date_range(statement: Select, column, from_date: datetime | None, to_date: datetime | None) -> Select:
    if from_date is not None:
        statement = statement.where(column >= from_date)
    if to_date is not None:
        statement = statement.where(column <= to_date)
    return statement


def _latest_by_product(db: Session, model, product_ids: list[UUID], *, seller_id: UUID | None) -> dict[UUID, object]:
    if not product_ids:
        return {}
    time_column = _model_time_column(model)
    max_dates = (
        select(model.product_id.label("product_id"), func.max(time_column).label("latest_time"))
        .where(model.product_id.in_(product_ids))
        .group_by(model.product_id)
        .subquery()
    )
    statement = select(model).join(
        max_dates,
        (model.product_id == max_dates.c.product_id) & (time_column == max_dates.c.latest_time),
    )
    if seller_id is not None and hasattr(model, "seller_id"):
        statement = statement.where(model.seller_id == seller_id)
    rows = db.execute(statement).scalars().all()
    return {row.product_id: row for row in rows}


def _model_time_column(model):
    for name in ("calculated_at", "generated_at", "assessed_at", "captured_at", "created_at"):
        if hasattr(model, name):
            return getattr(model, name)
    raise RagMemoryBuildError(f"No supported time column for {model.__name__}")


def _seller_id_for_row(row) -> UUID | None:
    seller_id = getattr(row, "seller_id", None)
    if seller_id is not None:
        return seller_id
    product = getattr(row, "product", None)
    return getattr(product, "seller_id", None)


def _merge(target: RagMemoryBackfillResult, source: RagMemoryBackfillResult) -> None:
    target.created_count += source.created_count
    target.skipped_count += source.skipped_count
    target.updated_count += source.updated_count
    target.failed_count += source.failed_count
    target.dry_run_count += source.dry_run_count
    target.soft_deleted_count += source.soft_deleted_count
    target.unsupported_count += source.unsupported_count
