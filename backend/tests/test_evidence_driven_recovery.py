from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.dead_stock_assessment import (
    DeadStockAssessment,
    DeadStockClassification,
    DeadStockNoSalesState,
)
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.dead_stock_recovery_recommendation import (
    EVIDENCE_RECOVERY_VERSION,
    DeadStockRecoveryRecommendation,
)
from app.models.inventory_history import InventoryHistory
from app.models.product import Product
from app.models.product_visibility_metric import ProductVisibilityMetric
from app.models.promotion import PromotionPlan, PromotionResult
from app.models.rag_index_outbox import RagIndexOutbox
from app.models.recommendation import Recommendation
from app.schemas.dead_stock_recovery import DeadStockRecoveryRecommendationResponse
from app.services.dead_stock_capital_recovery_service import (
    DeadStockCapitalRecoveryService,
)
from app.services.dead_stock_dashboard_service import DeadStockDashboardService
from app.services.dead_stock_recovery_evidence import promotion_observations
from app.services.dead_stock_recovery_service import DeadStockRecoveryService
from app.services.sales_velocity_service import SalesVelocityService
from app.tasks import recommendation_tasks
from test_decision_orchestrator import _client, _evaluations, _seed
from test_recommendation_evidence import MARKETPLACE, _product

pytest_plugins = ("test_decision_orchestrator",)


@pytest.fixture
def enabled_db(decision_db, monkeypatch):
    monkeypatch.setattr(settings, "evidence_driven_recovery_enabled", True)
    monkeypatch.setenv("FORECAST_ML_MODE", "disabled")
    with decision_db() as session:
        Product.metadata.create_all(
            session.get_bind(),
            tables=[
                PromotionPlan.__table__,
                PromotionResult.__table__,
                DeadStockCapitalRecoveryEstimate.__table__,
            ],
        )
    return decision_db


def _seed_recovery(
    db,
    *,
    stock=150,
    reserved=50,
    demand=True,
    cost="200",
    classification="DEAD_STOCK",
    new=False,
    visibility=False,
):
    product, _ = _seed(db, stock=stock, assessment=True, demand=demand)
    with db.begin() as session:
        item = session.get(Product, product.id)
        item.cost_price = Decimal(cost)
        assessment = session.scalar(
            select(DeadStockAssessment).where(DeadStockAssessment.product_id == item.id)
        )
        assessment.classification = DeadStockClassification(classification)
        assessment.risk_level = "HIGH" if classification == "DEAD_STOCK" else "MEDIUM"
        assessment.eligible_quantity = stock
        assessment.inventory_age_days = 5 if new else 90
        assessment.no_sales_state = (
            DeadStockNoSalesState.PRODUCT_TOO_NEW
            if new
            else DeadStockNoSalesState.RECENT_SALE
            if demand
            else DeadStockNoSalesState.SALES_DATA_INSUFFICIENT
        )
        assessment.triggered_rules = ["LOW_VISIBILITY"] if visibility else []
        if not visibility:
            metric = session.scalar(
                select(ProductVisibilityMetric).where(
                    ProductVisibilityMetric.product_id == item.id
                )
            )
            session.delete(metric)
        inventory = session.get(InventoryHistory, assessment.inventory_snapshot_id)
        inventory.quantity_reserved = reserved
        inventory.quantity_available = stock - reserved
    if demand:
        with db() as session:
            item = session.get(Product, product.id)
            now = datetime.now(timezone.utc)
            through = SalesVelocityService.business_date_for_seller(
                item.seller, now
            ) - timedelta(days=1)
            SalesVelocityService(session).calculate_for_product(
                product=item, as_of_date=through
            )
    return product


def _generate(db, product):
    with db() as session:
        return DeadStockRecoveryService(session).generate_for_product(
            seller_id=product.seller_id,
            product_id=product.id,
        )


def _promotion(product, at, *, offset=0, **overrides):
    end = at - timedelta(days=4 + offset)
    fields = {
        "id": uuid4(),
        "seller_id": product.seller_id,
        "product_id": product.id,
        "marketplace": MARKETPLACE,
        "started_at": end - timedelta(days=1),
        "ended_at": end,
        "units_sold": 12,
        "gross_revenue": Decimal("1000"),
        "estimated_profit": Decimal("400"),
        "spend": Decimal("40"),
        "result_status": "CALCULATED",
        "created_at": end + timedelta(hours=1),
        "updated_at": end + timedelta(hours=1),
        "evidence_json": {"currency": "BDT", "offered_quantity": 24},
        "missing_data_json": {},
    } | overrides
    return PromotionResult(**fields)


def test_high_stock_discount_and_cash_are_conditional(enabled_db):
    product = _seed_recovery(enabled_db)
    row, created = _generate(enabled_db, product)
    assert created and row.calculation_version == EVIDENCE_RECOVERY_VERSION
    assert row.primary_action == "DISCOUNT" and row.recommended_quantity == 100
    evidence = row.evidence
    assert evidence["expected_promotion_uplift"] is None
    assert evidence["inputs"]["baseline_demand"]["status"] == "UNAVAILABLE"
    assert evidence["inputs"]["recorded_sales"]["net_units"] == 100
    assert evidence["inputs"]["reserved_units"] == 50
    proof = evidence["candidate_actions"][0]["evidence"]
    assert proof["margin_guard"]["is_allowed"]
    assert Decimal(proof["margin_guard"]["candidate_price"]) == row.recommended_price
    zero, one, all_stock = proof["cash_scenarios"]
    assert [case["assumed_units_sold"] for case in (zero, one, all_stock)] == [
        0,
        1,
        100,
    ]
    assert Decimal(all_stock["gross_revenue_bdt"]) == row.recommended_price * 100
    assert Decimal(one["contribution_bdt"]) == Decimal(
        proof["margin_guard"]["unit_profit"]
    )
    assert zero["remaining_holding_cost_bdt"] is None
    assert row.rejected_actions[0]["action"] == "BUNDLE"
    assert any(
        "FLASH_HISTORY_INSUFFICIENT" in item["reasons"] for item in row.rejected_actions
    )
    assert (
        DeadStockRecoveryRecommendationResponse.model_validate(row).recommended_quantity
        == 100
    )


@pytest.mark.parametrize(
    ("params", "expected", "reason"),
    [
        ({"new": True}, "HOLD", "CLASSIFICATION_DOES_NOT_REQUIRE_RECOVERY"),
        ({"demand": False}, "MANUAL_REVIEW", "RECENT_SALES_EVIDENCE_UNAVAILABLE"),
        ({"cost": "480"}, "MANUAL_REVIEW", "NEGATIVE_UNIT_PROFIT"),
        (
            {"classification": "SLOW_MOVING", "visibility": True},
            "SEO_FIX",
            "RISK_BELOW_PROMOTION_THRESHOLD",
        ),
        ({"reserved": 150}, "MANUAL_REVIEW", "ELIGIBLE_STOCK_UNVERIFIED_OR_EMPTY"),
    ],
)
def test_recovery_keeps_safe_options_only(enabled_db, params, expected, reason):
    product = _seed_recovery(enabled_db, **params)
    row, _ = _generate(enabled_db, product)
    assert row.primary_action == expected
    assert row.recommended_price is None and row.recommended_quantity is None
    assert any(reason in item["reasons"] for item in row.rejected_actions)


def test_promotion_observations_are_scoped_noncausal_and_holding_cost_is_conditional(
    enabled_db, monkeypatch
):
    product = _seed_recovery(enabled_db)
    now = datetime.now(timezone.utc)
    foreign = _product(enabled_db)
    with enabled_db.begin() as session:
        session.get(Product, product.id).specifications = {
            "holding_cost_bdt_per_unit_per_day": "0.20"
        }
        plan = PromotionPlan(
            id=uuid4(),
            seller_id=product.seller_id,
            product_id=product.id,
            marketplace=MARKETPLACE,
            status="COMPLETED",
            promotion_type="DISCOUNT",
            title="Earlier seller-recorded discount",
            proposed_discount_rate=Decimal("0.1"),
            updated_at=now - timedelta(days=2),
        )
        session.add(plan)
        session.add_all(
            [
                _promotion(product, now, promotion_plan_id=plan.id),
                _promotion(product, now, offset=8),
                _promotion(product, now, offset=12, units_sold=-20),
                _promotion(foreign, now),
            ]
        )
    monkeypatch.setattr(
        "app.services.dead_stock_recovery_service.load_recovery_forecast",
        lambda *_: {
            "status": "APPROVED_BASELINE_ONLY",
            "forecast": {"expected_units": "105", "model_version": "fixture"},
            "uncertainty": {"status": "uncalibrated"},
        },
    )
    row, _ = _generate(enabled_db, product)
    evidence = row.evidence["inputs"]
    history = evidence["promotion_history"]
    assert history["response_status"] == "UNKNOWN"
    assert Decimal(history["observed_outcomes"][0]["planned_discount_rate"]) == Decimal(
        "0.1"
    )
    assert [item["observed_sell_through"] for item in history["observed_outcomes"]] == [
        "0.5",
        "0.5",
    ]
    assert len(history["rejected_outcomes"]) == 1
    assert "seasonality" in history["uncontrolled_factors"]
    assert evidence["baseline_demand"]["baseline_point_covers_eligible_units"] is True
    assert row.evidence["expected_promotion_uplift"] is None
    assert "FLASH_SALE" in row.secondary_actions
    proof = row.evidence["candidate_actions"][0]["evidence"]
    assert proof["ranking_components"]["baseline_coverage_penalty"] == "-12"
    assert proof["cash_scenarios"][0]["remaining_holding_cost_bdt"] == "600.00"


def test_overlapping_open_or_wrong_market_promotions_do_not_qualify():
    now = datetime.now(timezone.utc)
    product = Product(id=uuid4(), seller_id=uuid4())
    history = promotion_observations(
        [
            (_promotion(product, now), None),
            (_promotion(product, now), None),
            (
                _promotion(
                    product, now, offset=5, marketplace="Unverified", ended_at=None
                ),
                None,
            ),
        ],
        product=product,
        at=now,
    )
    assert history["observed_outcomes"] == []
    assert "OVERLAPPING_PROMOTION_WINDOWS" in history["rejected_outcomes"][0]["reasons"]
    assert "PROMOTION_TIMELINE_INVALID" in history["rejected_outcomes"][2]["reasons"]


def test_replay_preserves_one_recovery_and_outbox_and_capital_estimate_declines_uplift(
    enabled_db, monkeypatch
):
    product = _seed_recovery(enabled_db)
    row, _ = _generate(enabled_db, product)
    replay, created = _generate(enabled_db, product)
    assert replay.id == row.id and not created
    with enabled_db() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RagIndexOutbox)
                .where(RagIndexOutbox.source_id == str(row.id))
            )
            == 1
        )
        capital = DeadStockCapitalRecoveryService(session)
        monkeypatch.setattr(
            capital,
            "_estimate_units",
            Mock(side_effect=AssertionError("Legacy demand path used")),
        )
        estimate = capital.build_for_product(
            seller_id=product.seller_id,
            product_id=product.id,
            calculated_at=datetime.now(timezone.utc),
            simulation=None,
        )
        assert estimate.expected_units is estimate.gross_recovered_cash is None
        assert estimate.evidence["cash_scenarios"][-1]["assumed_units_sold"] == 100
        count = session.scalar(select(func.count()).select_from(PromotionPlan))
        assert count == 0 and session.get(Product, product.id).stock_quantity == 150
    monkeypatch.setattr(settings, "evidence_driven_recovery_enabled", False)
    legacy, created = _generate(enabled_db, product)
    assert created and legacy.id != row.id


def test_old_capital_estimate_is_not_attached_to_new_recommendation(
    enabled_db, monkeypatch
):
    product = _seed_recovery(enabled_db)
    scope = {"seller_id": product.seller_id, "product_id": product.id}
    monkeypatch.setattr(settings, "evidence_driven_recovery_enabled", False)
    old, _ = _generate(enabled_db, product)
    with enabled_db() as session:
        capital = DeadStockCapitalRecoveryService(session)
        prior = capital.estimate_for_product(**scope)
        assert prior.recovery_recommendation_id == old.id
    monkeypatch.setattr(settings, "evidence_driven_recovery_enabled", True)
    current, _ = _generate(enabled_db, product)
    with enabled_db() as session:
        capital = DeadStockCapitalRecoveryService(session)
        dashboard = DeadStockDashboardService(session)
        assert capital.latest_estimate(**scope) is None
        assert dashboard.product_intelligence(**scope).capital_recovery is None
        fresh = capital.estimate_for_product(**scope)
        assert fresh.recovery_recommendation_id == current.id
        data = dashboard.product_intelligence(**scope)
        assert (
            data.potential_recovered_cash is None and data.capital_recovery is not None
        )


def test_recovery_and_outbox_are_atomic_if_enqueue_fails(enabled_db, monkeypatch):
    product = _seed_recovery(enabled_db)
    with monkeypatch.context() as failed:
        failed.setattr(
            "app.services.dead_stock_recovery_service.RagIndexOutboxService.enqueue_upsert",
            Mock(side_effect=RuntimeError("unavailable outbox")),
        )
        with enabled_db() as session:
            service = DeadStockRecoveryService(session)
            with pytest.raises(RuntimeError, match="unavailable outbox"):
                service.generate_for_product(
                    seller_id=product.seller_id, product_id=product.id
                )
            assert (
                session.scalar(
                    select(func.count()).select_from(DeadStockRecoveryRecommendation)
                )
                == 0
            )
    assert _generate(enabled_db, product)[1]


def test_orchestration_keeps_listing_as_compatible_reorder_support(enabled_db):
    product = _seed_recovery(enabled_db, stock=30, reserved=0, visibility=True)
    with _client(enabled_db, product.seller_id) as client:
        request = client.post(f"/api/v1/recommendations/generate/{product.id}")
        assert request.status_code == 202, request.text
        recommendation_tasks.run_recommendation_job.run(request.json()["job_id"])
    with enabled_db() as session:
        record = session.scalars(select(Recommendation)).one()
        decision = record.recommendation_context["decision_orchestration"]
        recovery = _evaluations(decision)["dead_stock_recovery"]["candidate"]
        assert decision["primary_action"] == "REORDER"
        assert recovery["candidate_id"] in decision["supporting_candidate_ids"]
        assert recovery["proposed_parameters"]["action"] == "SEO_FIX"
        assert recovery["evidence"]["snapshot"]["expected_promotion_uplift"] is None
        assert (
            session.scalar(
                select(func.count()).select_from(DeadStockRecoveryRecommendation)
            )
            == 0
        )
