from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.promotion import PromotionPlan, PromotionPlanStatus, PromotionResult, PromotionResultStatus
from app.models.rag_memory import RagMemorySourceType
from app.services.rag_index_outbox_service import RagIndexOutboxService


class PromotionService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_plan(
        self,
        *,
        seller_id: UUID,
        promotion_type: str,
        title: str,
        description: str | None = None,
        product_id: UUID | None = None,
        category: str | None = None,
        marketplace: str | None = None,
        proposed_discount_rate: Decimal | None = None,
        proposed_price: Decimal | None = None,
        planned_start_at: datetime | None = None,
        planned_end_at: datetime | None = None,
        source: str = "UNKNOWN",
        created_from_recommendation_id: UUID | None = None,
        created_from_copilot_proposal_id: UUID | None = None,
        safety_checks_json: dict | None = None,
        expected_impact_json: dict | None = None,
        status: PromotionPlanStatus = PromotionPlanStatus.PROPOSED,
    ) -> PromotionPlan:
        if product_id is not None:
            self._verify_product(seller_id=seller_id, product_id=product_id)
        plan = PromotionPlan(
            seller_id=seller_id,
            product_id=product_id,
            category=category,
            marketplace=marketplace,
            promotion_type=promotion_type,
            title=title,
            description=description,
            proposed_discount_rate=proposed_discount_rate,
            proposed_price=proposed_price,
            planned_start_at=planned_start_at,
            planned_end_at=planned_end_at,
            status=status,
            source=source,
            created_from_recommendation_id=created_from_recommendation_id,
            created_from_copilot_proposal_id=created_from_copilot_proposal_id,
            safety_checks_json=safety_checks_json or {},
            expected_impact_json=expected_impact_json or {},
        )
        self._db.add(plan)
        self._db.flush()
        RagIndexOutboxService(self._db).enqueue_upsert(
            seller_id=seller_id,
            source_type=RagMemorySourceType.PROMOTION_PLAN,
            source_id=str(plan.id),
            product_id=product_id,
            source_updated_at=datetime.now(timezone.utc),
        )
        self._db.commit()
        self._db.refresh(plan)
        return plan

    def approve_plan(self, *, seller_id: UUID, promotion_plan_id: UUID) -> dict:
        plan = self._db.execute(select(PromotionPlan).where(PromotionPlan.seller_id == seller_id, PromotionPlan.id == promotion_plan_id)).scalar_one_or_none()
        if plan is None:
            raise PermissionError("Promotion plan does not belong to the authenticated seller.")
        plan.status = PromotionPlanStatus.APPROVED
        RagIndexOutboxService(self._db).enqueue_upsert(
            seller_id=seller_id,
            source_type=RagMemorySourceType.PROMOTION_PLAN,
            source_id=str(plan.id),
            product_id=plan.product_id,
            source_updated_at=datetime.now(timezone.utc),
        )
        self._db.commit()
        self._db.refresh(plan)
        return {
            "promotion_plan": plan,
            "marketplace_execution_created": False,
            "execution_note": "Approval records an internal plan only; live marketplace campaign execution is not implemented.",
        }

    def record_result(
        self,
        *,
        seller_id: UUID,
        started_at: datetime,
        promotion_plan_id: UUID | None = None,
        product_id: UUID | None = None,
        marketplace: str | None = None,
        ended_at: datetime | None = None,
        units_sold: int | None = None,
        gross_revenue: Decimal | None = None,
        estimated_profit: Decimal | None = None,
        spend: Decimal | None = None,
        discount_cost: Decimal | None = None,
        evidence_json: dict | None = None,
        missing_data_json: dict | None = None,
    ) -> PromotionResult:
        if promotion_plan_id is not None:
            plan = self._db.execute(select(PromotionPlan).where(PromotionPlan.seller_id == seller_id, PromotionPlan.id == promotion_plan_id)).scalar_one_or_none()
            if plan is None:
                raise PermissionError("Promotion plan does not belong to the authenticated seller.")
            product_id = product_id or plan.product_id
            marketplace = marketplace or plan.marketplace
        if product_id is not None:
            self._verify_product(seller_id=seller_id, product_id=product_id)
        missing = dict(missing_data_json or {})
        roi = None
        total_cost = _sum_money(spend, discount_cost)
        if gross_revenue is None:
            missing.setdefault("MISSING_REVENUE", True)
        if estimated_profit is None:
            missing.setdefault("MISSING_COST_OR_FEE_DATA", True)
        if total_cost is None or total_cost == 0:
            missing.setdefault("MISSING_SPEND_OR_DISCOUNT_COST", True)
        elif estimated_profit is not None:
            roi = estimated_profit / total_cost
        result_status = PromotionResultStatus.CALCULATED if not missing else PromotionResultStatus.PARTIAL
        if gross_revenue is None and estimated_profit is None:
            result_status = PromotionResultStatus.MISSING_DATA
        row = PromotionResult(
            seller_id=seller_id,
            promotion_plan_id=promotion_plan_id,
            product_id=product_id,
            marketplace=marketplace,
            started_at=started_at,
            ended_at=ended_at,
            units_sold=units_sold,
            gross_revenue=gross_revenue,
            estimated_profit=estimated_profit,
            spend=spend,
            discount_cost=discount_cost,
            roi=roi,
            result_status=result_status,
            evidence_json=evidence_json or {},
            missing_data_json=missing,
        )
        self._db.add(row)
        self._db.flush()
        RagIndexOutboxService(self._db).enqueue_upsert(
            seller_id=seller_id,
            source_type=RagMemorySourceType.PROMOTION_RESULT,
            source_id=str(row.id),
            product_id=product_id,
            source_updated_at=started_at,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def _verify_product(self, *, seller_id: UUID, product_id: UUID) -> None:
        exists = self._db.execute(select(Product.id).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none()
        if exists is None:
            raise PermissionError("Product does not belong to the authenticated seller.")


def _sum_money(*values: Decimal | None) -> Decimal | None:
    present = [Decimal(value) for value in values if value is not None]
    if not present:
        return None
    return sum(present, Decimal("0"))
