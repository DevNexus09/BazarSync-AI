from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, update

from app.api.v1.dynamic_pricing import router
from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.competitor_ranking import CompetitorRanking
from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation
from app.models.inventory_risk import InventoryRiskAssessment
from app.models.product import Product, ProductMarketplaceListing
from app.models.product_price_history import ProductPriceHistory
from app.models.promotion import PromotionPlan, PromotionResult
from app.models.rag_index_outbox import RagIndexOutbox
from app.models.rag_memory import RagMemorySourceType
from app.schemas.forecast_inference import NativeInferenceReply
from app.schemas.pricing_policy import (
    MarketplaceFeePolicyResponse,
    PricingPolicyResponse,
)
from app.schemas.recommendation_candidate import CandidateEngine
from app.schemas.statistical_forecast import BaselineConfig
from app.services.copilot.tool_registry import _pricing_payload
from app.services.decision_orchestrator import DecisionOrchestrator
from app.services.dynamic_pricing_service import DynamicPricingService
from app.services.forecast_inference_service import ForecastInferenceService
from app.services.historical_dataset_service import CompetitorPriceStatistics
from app.services.margin_guard import MarginGuard
from app.services.pricing_analytics_service import PricingAnalyticsService
from app.services.pricing_forecast_evidence import (
    PRICING_FORECAST_VERSION,
    _baseline_evidence,
    describe_price_history,
    load_pricing_forecast_evidence,
)
from app.services.rag_memory_document_builder import RagMemoryDocumentBuilder
from app.services.recommendation_evidence_service import (
    CompetitorEvidence,
    FieldEvidence,
    Freshness,
    RecommendationEvidence,
)
from test_decision_orchestrator import _seed
from test_forecast_inference import manifest, write_registry
from test_recommendation_evidence import MARKETPLACE, _collect, _product
from test_statistical_forecast import origin_case

pytest_plugins = ("test_decision_orchestrator",)


def _priced_row(*, status=Freshness.FRESH, fee=True, db=None):
    seller_id, product_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    product = Product(
        id=product_id,
        seller_id=seller_id,
        selling_price=Decimal("100"),
        cost_price=Decimal("78"),
        stock_quantity=50,
        category="Home",
    )
    policy = PricingPolicyResponse(
        id=uuid4(),
        seller_id=seller_id,
        product_id=product_id,
        marketplace=MARKETPLACE,
        currency="BDT",
        minimum_margin_rate=Decimal("0.15"),
        minimum_unit_profit=Decimal("0"),
        price_increment=Decimal("2"),
        recommendation_cooldown_hours=0,
        maximum_price_increase_rate=Decimal("0.06"),
        minimum_allowed_price=Decimal("91"),
        maximum_allowed_price=Decimal("108"),
        objective="MAXIMIZE_EXPECTED_PROFIT",
        is_active=True,
    )
    fees = MarketplaceFeePolicyResponse(
        id=uuid4() if fee else None,
        seller_id=seller_id,
        product_id=product_id,
        marketplace=MARKETPLACE,
        currency="BDT",
        version="test-fees",
        percentage_commission_rate=Decimal("0.05"),
        payment_fee_rate=Decimal("0"),
        fixed_per_order_fee=Decimal("0"),
        fixed_per_unit_fee=Decimal("0"),
        fulfilment_fee=Decimal("0"),
        shipping_subsidy=Decimal("0"),
        other_variable_cost=Decimal("0"),
        is_active=True,
        is_default=not fee,
    )
    field = FieldEvidence(status, now - timedelta(minutes=5))
    market = RecommendationEvidence(
        seller_id,
        product_id,
        uuid4(),
        now,
        timedelta(hours=1),
        timedelta(hours=1),
        observations=tuple(
            CompetitorEvidence(
                uuid4(), uuid4(), Decimal(price), "IN_STOCK", field, field, 0.97
            )
            for price in ("91", "103", "109")
        ),
    )
    service = DynamicPricingService(
        db, margin_guard=MarginGuard(None, resolved_policy=(policy, fees))
    )
    return service.build_forecast_assisted_recommendation(
        product=product, market=market, policy=policy
    )


def test_exact_rounded_prices_are_guarded_and_never_ranked_without_response():
    row = _priced_row()
    audit = row.evidence
    prices = {Decimal(item["candidate_price"]): item for item in audit["candidates"]}
    assert all(price % 2 == 0 and abs(price - 100) <= 15 for price in prices)
    assert prices[104]["is_allowed"] and 103 not in prices
    assert "BELOW_MINIMUM_SAFE_PRICE" in prices[90]["rejection_reasons"]
    assert "BELOW_ABSOLUTE_MINIMUM" in prices[90]["rejection_reasons"]
    assert "EXCEEDS_MAXIMUM_INCREASE" in prices[110]["rejection_reasons"]
    assert "ABOVE_ABSOLUTE_MAXIMUM" in prices[110]["rejection_reasons"]
    assert all(not quote["eligible_for_price_change"] for quote in prices.values())
    assert all(quote["expected_units"] is None for quote in prices.values())
    assert row.action == "HOLD"
    assert row.recommended_price == row.current_price
    assert row.revenue_impact is row.profit_impact is None
    assert audit["recommended_target_price"] is None
    assert audit["price_response"]["status"] == "UNKNOWN"
    assert audit["competitor_evidence"]["validated_fresh_price_count"] == 3
    assert audit["selected"]["margin_guard"]["policy_version"] == "test-fees"


def test_stale_market_prices_cannot_seed_candidates():
    row = _priced_row(status=Freshness.STALE)
    assert row.evidence["competitor_evidence"]["validated_fresh_price_count"] == 0
    assert "INSUFFICIENT_FRESH_COMPETITOR_PRICES" in row.evidence["rejection_reasons"]
    assert Decimal("92") not in {
        Decimal(item["candidate_price"]) for item in row.evidence["candidates"]
    }


def test_missing_fee_policy_rejects_all_quotes():
    row = _priced_row(fee=False)
    assert row.evidence["selected"] is None
    assert row.evidence["constraint_safe_candidate_prices"] == []
    for quote in row.evidence["candidates"]:
        assert "MISSING_FEE_DATA" in quote["rejection_reasons"]
    assert row.action == "HOLD"


@pytest.mark.parametrize(("units", "exposure"), [("0", False), ("250", True)])
def test_approved_baseline_affects_stock_exposure_only(
    monkeypatch, tmp_path, units, exposure
):
    case = origin_case((5,) * 60)
    model = manifest("pricing-fixture", "c" * 64, horizon=30)
    digest = write_registry(tmp_path, active=model)
    monkeypatch.setenv("FORECAST_ML_MODE", "enabled")
    monkeypatch.setenv("FORECAST_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("FORECAST_REGISTRY_SHA256", digest)
    monkeypatch.setattr(
        ForecastInferenceService,
        "_native",
        lambda *_: NativeInferenceReply(units=Decimal(units)),
    )
    baseline = _baseline_evidence(case.snapshot, case.forecast_origin, BaselineConfig())
    assert baseline["forecast"]["expected_units"] == units
    assert baseline["uncertainty"]["status"] == "uncalibrated"
    monkeypatch.setattr(
        "app.services.dynamic_pricing_service.load_pricing_forecast_evidence",
        lambda *_, **__: {
            "baseline_demand_forecast": baseline,
            "price_response": {"status": "UNKNOWN"},
        },
    )
    row = _priced_row(db=Mock())
    assert row.evidence["risk"]["baseline_point_exceeds_catalog_stock"] is exposure
    assert row.action == "HOLD"
    assert (
        row.expected_profit
        is row.baseline_expected_revenue
        is row.profit_impact
        is None
    )
    assert all(item["expected_units"] is None for item in row.evidence["candidates"])


def test_model_unavailable_and_shadow_baseline_are_not_used(monkeypatch, tmp_path):
    case = origin_case((5,) * 60)
    monkeypatch.setenv("FORECAST_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("FORECAST_REGISTRY_SHA256", "c" * 64)
    monkeypatch.setenv("FORECAST_ML_MODE", "enabled")
    assert _baseline_evidence(
        case.snapshot, case.forecast_origin, BaselineConfig()
    ) == {
        "status": "UNAVAILABLE",
        "reason": "REGISTRY_UNAVAILABLE",
        "attempts": [],
    }
    monkeypatch.setenv("FORECAST_ML_MODE", "shadow")
    assert (
        _baseline_evidence(case.snapshot, case.forecast_origin, BaselineConfig())[
            "reason"
        ]
        == "APPROVED_INFERENCE_DISABLED"
    )


def test_single_price_edit_and_confounders_do_not_qualify_response():
    snapshot = origin_case((5,) * 60).snapshot
    rows = list(snapshot.history.rows)
    edit_day = rows[-4].business_date
    for index, row in enumerate(rows):
        stockout = index == 1
        rows[index] = row.model_copy(
            update={
                "marketplace": MARKETPLACE,
                "effective_selling_price": Decimal("100" if index < 30 else "110"),
                "currency": "BDT",
                "stockout_indicator": stockout,
                "sales_coverage_complete": index != 0,
                "forecast_label_eligible": index not in (0, 1),
                "promotion_indicator": True if index == 2 else None,
                "observed_units_sold": 6 + index % 7 + (8 if index > 31 else 0),
                "competitor_prices": (
                    CompetitorPriceStatistics(
                        marketplace=MARKETPLACE,
                        currency="BDT",
                        count=2,
                        minimum=90,
                        maximum=150,
                        mean=Decimal(100 + index),
                    ),
                ),
            }
        )
    history = snapshot.history.model_copy(update={"rows": tuple(rows)})
    evidence = describe_price_history(
        snapshot.model_copy(update={"history": history}),
        edit_days={edit_day},
        promotion_results=False,
    )
    assert evidence["status"] == "OBSERVATIONAL_ONLY"
    assert evidence["variation_screen"] == "INSUFFICIENT_PRICE_VARIATION"
    assert evidence["recorded_base_price_edit_days"] == 1
    confounders = evidence["confounders"]
    assert confounders["promotion_observed"] is True
    assert confounders["weekly_seasonality_signal"] is True
    assert confounders["demand_trend"]["material_shift"] is True
    assert (
        confounders["sales_coverage_incomplete_days"]
        == confounders["stockout_days"]
        == 1
    )
    assert confounders["concurrent_competitor_aggregate_movements"] == 1


def test_specialized_api_replay_rollback_and_orchestrated_hold(
    decision_db, monkeypatch
):
    product, run_id = _seed(decision_db, stock=1000, assessment=False)
    foreign = _product(decision_db)
    with decision_db() as session:
        Product.metadata.create_all(
            session.get_bind(),
            tables=[
                ProductMarketplaceListing.__table__,
                ProductPriceHistory.__table__,
                PromotionPlan.__table__,
                PromotionResult.__table__,
                CompetitorRanking.__table__,
                InventoryRiskAssessment.__table__,
            ],
        )
        PricingAnalyticsService(session).generate_for_product(
            seller_id=product.seller_id, product_id=product.id
        )
    with decision_db.begin() as session:
        session.execute(
            update(Product)
            .where(Product.id == product.id)
            .values(updated_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )

    def get_session():
        with decision_db() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_current_seller] = lambda: SimpleNamespace(
        id=product.seller_id
    )
    monkeypatch.setenv("FORECAST_ML_MODE", "disabled")
    monkeypatch.setattr(settings, "forecast_assisted_pricing_enabled", True)
    path = f"/products/{product.id}/pricing/recommendations"
    with TestClient(app) as client:
        initial = client.post(path)
        assert initial.status_code == 200, initial.text
        data = initial.json()
        assert data["formula_version"] == PRICING_FORECAST_VERSION
        assert (
            data["evidence"]["baseline_demand_forecast"]["reason"]
            == "APPROVED_INFERENCE_DISABLED"
        )
        assert client.post(path).json()["id"] == data["id"]
        with decision_db() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RagIndexOutbox)
                    .where(RagIndexOutbox.source_id == data["id"])
                )
                == 1
            )
        assert (
            client.post(f"/products/{foreign.id}/pricing/recommendations").status_code
            == 422
        )
        assert (
            client.post(
                f"/pricing/recommendations/{data['id']}/acknowledge"
            ).status_code
            == 200
        )
        with decision_db() as session:
            item = session.get(Product, product.id)
            orchestrator = DecisionOrchestrator(
                session,
                forecast_provider=Mock(
                    side_effect=AssertionError("Legacy elasticity used")
                ),
            )
            decision = orchestrator.evaluate(
                item, _collect(session, product, scrape_run_id=run_id)
            )
            assert orchestrator.finalize(item, decision).target_price is None
            pricing = next(
                result
                for result in decision.evaluations
                if result.engine == CandidateEngine.DYNAMIC_PRICING
            )
            assert "PRICE_RESPONSE_UNVALIDATED" in pricing.reason_codes
            assert pricing.candidate.evidence.snapshot[
                "constraint_safe_candidate_prices"
            ]
        monkeypatch.setattr(settings, "forecast_assisted_pricing_enabled", False)
        legacy = client.post(path).json()
        assert (
            legacy["id"] != data["id"]
            and legacy["formula_version"] != PRICING_FORECAST_VERSION
        )
        assert client.get(path).json()["total"] == 2
    with decision_db() as session:
        saved = session.get(DynamicPricingRecommendation, UUID(data["id"]))
        assert _pricing_payload(saved)["recommended_price"] is None
        document = RagMemoryDocumentBuilder().build_from_pricing_recommendation(saved)
        assert "Recommended price: unknown" in document.content_text
        assert (
            session.scalar(
                select(func.count()).select_from(DynamicPricingRecommendation)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(RagIndexOutbox)
                .where(RagIndexOutbox.source_type == RagMemorySourceType.PRICE_HISTORY)
            )
            == 3
        )
        assert session.get(Product, product.id).selling_price == product.selling_price
        assert session.get(Product, product.id).stock_quantity == 1000
        unavailable = load_pricing_forecast_evidence(
            session,
            seller_id=foreign.seller_id,
            product_id=product.id,
            current_price=product.selling_price,
            evaluated_at=datetime.now(timezone.utc),
        )
        assert (
            unavailable["historical_price_demand_association"]["status"]
            == "UNAVAILABLE"
        )
