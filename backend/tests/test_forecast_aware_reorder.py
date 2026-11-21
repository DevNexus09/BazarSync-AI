from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.inventory_risk import InventoryRiskAssessment
from app.models.product import Product, ProductMarketplaceListing
from app.models.product_price_history import ProductPriceHistory
from app.models.reorder_recommendation import (
    FORECAST_REORDER_VERSION,
    ReorderRecommendation,
)
from app.models.sales_velocity import SalesVelocityDataStatus
from app.models.seller import Seller
from app.schemas.demand_regime import DemandRegime
from app.schemas.forecast_inference import (
    ForecastInferenceResult,
    ForecastModelManifest,
    LeadTimeDemandCalibration,
    NativeInferenceReply,
)
from app.schemas.forecast_uncertainty import CalibrationPeriod
from app.schemas.ml_forecast import MLForecastResult
from app.schemas.reorder_recommendation import ReorderRecommendationResponse
from app.schemas.statistical_forecast import BaselineConfig, ForecastResult
from app.repositories.inventory_intelligence_repository import (
    InventoryIntelligenceRepository,
)
from app.services.decision_orchestrator import DecisionOrchestrator
from app.services.forecast_inference_service import ForecastInferenceService
from app.services.forecast_interval_service import (
    IntervalSample,
    validate_reorder_bound,
)
from app.services.forecast_reorder_service import (
    ReorderInputs,
    load_reorder_forecast,
)
from app.services.historical_dataset_service import BUSINESS_TIMEZONE, DAY, _opening
from app.services.inventory_risk_service import InventoryRiskService
from app.services.reorder_recommendation_service import ReorderRecommendationService
from app.services.sales_velocity_service import (
    SalesVelocityCalculation,
    SalesVelocityService,
)
from app.tasks import recommendation_tasks, reorder_recommendation_tasks
from test_decision_orchestrator import _client, _seed
from test_forecast_inference import manifest, write_registry
from test_recommendation_evidence import _collect, _product
from test_reorder_recommendation_service import FakeReorderRepository
from test_statistical_forecast import DATE, PRODUCT, SELLER, origin_case

pytest_plugins = ("test_decision_orchestrator",)
NOW = datetime(2026, 9, 10, 7, tzinfo=timezone.utc)
AS_OF = NOW.date()
DIGEST = "b" * 64


@pytest.fixture(autouse=True)
def enable_reorder(monkeypatch):
    monkeypatch.setattr(settings, "forecast_aware_reorder_enabled", True)
    monkeypatch.setattr(settings, "reorder_target_service_level", Decimal("0.90"))
    monkeypatch.setenv("FORECAST_ML_MODE", "disabled")


def _inputs(*, stock=0, reserved=0, incoming=0, lead=7, rate="2", specs=None):
    seller = Seller(id=uuid4())
    product = Product(
        id=uuid4(),
        seller_id=seller.id,
        stock_quantity=stock,
        supplier_lead_time=lead,
        cost_price=Decimal("10"),
        specifications=specs or {},
    )
    snapshot = InventoryHistory(
        id=uuid4(),
        seller_id=seller.id,
        product_id=product.id,
        snapshot_date=AS_OF,
        captured_at=NOW - timedelta(hours=1),
        quantity_on_hand=stock,
        quantity_reserved=reserved,
        quantity_available=stock - reserved,
        quantity_incoming=incoming,
        source=InventorySnapshotSource.DAILY_SNAPSHOT,
    )
    velocity = (
        None
        if rate is None
        else SalesVelocityCalculation(
            product_id=product.id,
            seller_id=seller.id,
            as_of_date=AS_OF - DAY,
            window_days=30,
            observed_days=30,
            gross_units_sold=60,
            returned_units=0,
            net_units_sold=60,
            daily_sales_rate=Decimal(rate),
            sales_days=10,
            confidence_score=Decimal("85"),
            data_status=SalesVelocityDataStatus.SUFFICIENT,
            calculation_version="observed-v1",
            metadata={},
        )
    )
    return dict(
        product=product,
        seller=seller,
        inventory_snapshot=snapshot,
        sales_velocity=velocity,
        stockout_prediction=None,
        as_of_date=AS_OF,
        generated_at=NOW,
        calculation_version="legacy-v1",
    )


def _run(**kwargs):
    return ReorderRecommendationService(
        repository=FakeReorderRepository()
    ).build_recommendation(**kwargs)


def _forecast(product, at, day, *, units="70", horizon=7, calibration=None):
    point = ForecastResult(
        seller_id=product.seller_id,
        product_id=product.id,
        forecast_origin=at + timedelta(microseconds=2),
        horizon_days=horizon,
        target_start_date=day + DAY,
        target_end_date=day + horizon * DAY,
        expected_units=Decimal(units),
        requested_model="auto",
        model_name="catboost",
        model_version="catboost@reorder-fixture",
        data_sufficiency_status="SUFFICIENT",
        evidence_status="ELIGIBLE_OBSERVED_SALES",
        generated_at=at,
        fallback_reason=None,
        contiguous_history_days=60,
        data_cutoff=at,
        feature_version="fixture-v1",
    )
    return ForecastInferenceResult(
        mode="enabled",
        source="active",
        forecast=point,
        selection_reason="APPROVED_MODEL",
        demand_regime="regular",
        lead_time_calibration=calibration,
    )


def _calibration(product_id, *, at_day=AS_OF, successes=30, radius=90):
    first = at_day - 400 * DAY
    last = first + 19 * 7 * DAY
    first_test = last + 10 * DAY
    last_test = first_test + 29 * 7 * DAY
    return LeadTimeDemandCalibration(
        product_id=product_id,
        model_sha256=DIGEST,
        radius_units=radius,
        nominal_level=Decimal("0.90"),
        calibration=CalibrationPeriod(
            first_origin=_opening(first),
            last_origin=_opening(last),
            last_target_date=last + 7 * DAY,
            available_at=_opening(last + 8 * DAY),
            scored_windows=20,
        ),
        validation_first_origin=first_test,
        validation_last_origin=last_test,
        validation_outcomes_available_at=_opening(last_test + 8 * DAY),
        validation_windows=30,
        within_upper_bound=successes,
        validation_lineage_sha256="c" * 64,
    )


def _patch_forecast(monkeypatch, result):
    monkeypatch.setattr(
        "app.services.reorder_recommendation_service.load_reorder_forecast",
        lambda *_, **__: (result, result.selection_reason),
    )


@pytest.mark.parametrize(("stock", "expected_action"), [(0, "REORDER"), (1000, "HOLD")])
def test_high_approved_demand_and_missing_legacy_sales(
    monkeypatch, stock, expected_action
):
    inputs = _inputs(stock=stock, rate=None)
    _patch_forecast(monkeypatch, _forecast(inputs["product"], NOW, AS_OF))
    row = _run(**inputs)
    assert row.action == expected_action
    assert row.reorder_point == 100 and row.target_stock == 170
    assert row.evidence["lead_time_demand"] == "70"
    assert row.evidence["uncertainty"]["status"] == "uncalibrated"
    if stock == 0:
        assert row.recommended_quantity == 170 and row.reorder_deadline == AS_OF
    else:
        assert row.recommended_quantity == 0


def test_zero_approved_or_covered_demand_holds(monkeypatch):
    inputs = _inputs(rate="0")
    fallback = _run(**inputs, verified_zero_sales=True)
    assert fallback.action == "HOLD" and fallback.recommendation_status == "OPEN"
    assert fallback.evidence["lead_time_demand"] == "0"
    assert _run(**inputs).recommendation_status == "INSUFFICIENT_DATA"
    _patch_forecast(monkeypatch, _forecast(inputs["product"], NOW, AS_OF, units="0"))
    approved = _run(**inputs)
    assert approved.action == "HOLD" and approved.recommended_quantity == 0
    assert (
        approved.reorder_deadline is None
        and approved.evidence["on_hand_coverage_days"] is None
    )


def test_validated_high_uncertainty_requires_more_stock(monkeypatch):
    inputs = _inputs(stock=30)
    product = inputs["product"]
    calibration = _calibration(product.id)
    _patch_forecast(
        monkeypatch, _forecast(product, NOW, AS_OF, calibration=calibration)
    )
    validated = _run(**inputs)
    evidence = validated.evidence["uncertainty"]
    assert validated.reorder_point == 160 and validated.target_stock == 230
    assert validated.recommended_quantity == 200
    assert evidence["status"] == "validated_lead_time_upper_bound"
    assert evidence["stockout_risk"] == "ON_HAND_BELOW_VALIDATED_LEAD_TIME_BOUND"
    assert evidence["stockout_probability"] is None
    monkeypatch.setattr(settings, "reorder_target_service_level", Decimal("0.97"))
    unsupported = _run(**inputs)
    assert unsupported.reorder_point == 100
    assert unsupported.evidence["uncertainty"]["status"] == "service_level_unsupported"
    assert "stockout_risk" not in unsupported.evidence["uncertainty"]
    monkeypatch.setattr(settings, "reorder_target_service_level", Decimal("0.90"))
    weak_calibration = _calibration(product.id, successes=27)
    _patch_forecast(
        monkeypatch, _forecast(product, NOW, AS_OF, calibration=weak_calibration)
    )
    assert (
        _run(**inputs).evidence["uncertainty"]["status"] == "service_level_unsupported"
    )


def test_incoming_reserved_stock_and_eta_are_separate():
    inputs = _inputs(
        stock=20,
        reserved=15,
        incoming=80,
        specs={
            "confirmed_incoming_quantity": "20",
            "confirmed_incoming_date": (AS_OF + 2 * DAY).isoformat(),
        },
    )
    row = _run(**inputs)
    assert row.inventory_position == 25
    assert row.recommended_quantity == 9 and row.reorder_deadline == AS_OF
    assert row.evidence["available_stock"] == 5
    assert row.evidence["unconfirmed_snapshot_incoming"] == 80
    assert row.evidence["confirmed_incoming_before_supplier_receipt"] == 20
    override = _run(**inputs, confirmed_incoming_quantity=100)
    assert override.inventory_position == 105 and override.recommended_quantity == 0
    assert override.evidence["confirmed_incoming_before_supplier_receipt"] == 0
    assert (
        "CHECK_EXISTING_RECEIPTS_BEFORE_ORDERING" in override.evidence["reason_codes"]
    )
    inputs["product"].specifications["confirmed_incoming_date"] = (
        AS_OF + 40 * DAY
    ).isoformat()
    assert _run(**inputs).recommended_quantity == 29


def test_moq_pack_maximum_storage_and_budget():
    inputs = _inputs(
        specs={
            "moq": "35",
            "pack_size": "10",
            "maximum_stock": "60",
            "storage_capacity_units": "51",
            "reorder_budget_bdt": "450",
        },
    )
    assert _run(**inputs).recommended_quantity == 40
    inputs["product"].specifications["storage_capacity_units"] = "39"
    assert _run(**inputs).recommended_quantity == 0
    inputs["product"].specifications["storage_capacity_units"] = "51"
    inputs["product"].specifications["reorder_budget_bdt"] = "399"
    held = _run(**inputs)
    assert held.recommended_quantity == 0
    assert "REORDER_CONSTRAINED_BY_CAPACITY_OR_BUDGET" in held.evidence["reason_codes"]
    inputs["product"].specifications["pack_size"] = "-2"
    assert (
        _run(**inputs).evidence["insufficient_reason"] == "INVALID_SUPPLIER_ORDER_TERMS"
    )


@pytest.mark.parametrize(
    ("lead", "rate", "reason", "expected"),
    [
        (45, "2", "LEAD_TIME_HORIZON_UNSUPPORTED", "90"),
        (7, "2", "APPROVED_INFERENCE_UNAVAILABLE", "14"),
        (0, "2", "SUPPLIER_LEAD_TIME_UNAVAILABLE", None),
        (7, None, "INSUFFICIENT_DEMAND_EVIDENCE", None),
    ],
)
def test_available_fallback_and_unavailable_inputs(lead, rate, reason, expected):
    row = _run(**_inputs(lead=lead, rate=rate))
    assert row.evidence["lead_time_demand"] == expected
    assert reason in row.evidence["reason_codes"]
    assert row.action == ("HOLD" if expected is None else "REORDER")
    if expected is None:
        assert row.recommendation_status == "INSUFFICIENT_DATA"
        assert row.evidence["reorder_point"] is None


def test_intermittent_or_foreign_forecast_uses_only_scoped_velocity(monkeypatch):
    inputs = _inputs(rate="0.4")
    source = _forecast(inputs["product"], NOW, AS_OF)
    intermittent = source.model_copy(
        update={
            "source": "baseline",
            "demand_regime": DemandRegime.INTERMITTENT,
            "selection_reason": "ML_REQUIRES_REGULAR_VERIFIED_HISTORY",
        }
    )
    _patch_forecast(monkeypatch, intermittent)
    row = _run(**inputs)
    assert row.evidence["demand_regime"] == "intermittent"
    assert row.evidence["lead_time_demand"] == "2.8"
    assert row.evidence["uncertainty"]["status"] == "unavailable"
    foreign = source.model_copy(
        update={"forecast": source.forecast.model_copy(update={"seller_id": uuid4()})}
    )
    _patch_forecast(monkeypatch, foreign)
    assert _run(**inputs).evidence["forecast"] is None
    inputs["inventory_snapshot"].seller_id = uuid4()
    with pytest.raises(ValueError, match="authorized seller"):
        _run(**inputs)


def test_inference_accepts_only_exact_product_and_artifact_validation(
    tmp_path, monkeypatch
):
    case = origin_case((5,) * 60)
    calibration = _calibration(PRODUCT, at_day=DATE)
    draft = manifest(
        "reorder-validation",
        DIGEST,
        training_data_cutoff=_opening(DATE - 600 * DAY),
        trained_at=_opening(DATE - 599 * DAY),
    )
    artifact = draft.artifacts[0]
    payload = draft.model_dump()
    payload["artifacts"] = [
        {**artifact.model_dump(), "reorder_calibrations": (calibration,)}
    ]
    approved = ForecastModelManifest.model_validate(payload)
    payload["artifacts"] = [
        {
            **artifact.model_dump(),
            "reorder_calibrations": (
                calibration.model_copy(update={"model_sha256": "d" * 64}),
            ),
        }
    ]
    with pytest.raises(ValidationError, match="lead-time calibration"):
        ForecastModelManifest.model_validate(payload)
    monkeypatch.setenv("FORECAST_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "FORECAST_REGISTRY_SHA256", write_registry(tmp_path, active=approved)
    )
    monkeypatch.setattr(
        ForecastInferenceService,
        "_native",
        lambda *_, **__: NativeInferenceReply(units=35),
    )
    service = ForecastInferenceService.enabled_runtime(SELLER, BaselineConfig())
    result = service.forecast(
        case.snapshot, forecast_origin=case.forecast_origin, horizon_days=7
    )
    assert result.lead_time_calibration == calibration
    other = origin_case((5,) * 60, product=uuid4())
    other_outcome = service.forecast(
        other.snapshot, forecast_origin=other.forecast_origin, horizon_days=7
    )
    assert (
        other_outcome.source == "active" and other_outcome.lead_time_calibration is None
    )


def test_offline_bound_independent_holdouts_and_repeatable_lineage():
    split = DATE + 21 * 8 * DAY
    rows = []
    for index in range(53):
        day = DATE + index * 8 * DAY
        point = MLForecastResult(
            seller_id=SELLER,
            product_id=PRODUCT,
            forecast_origin=_opening(day),
            horizon_days=7,
            target_start_date=day + DAY,
            target_end_date=day + 7 * DAY,
            expected_units=100,
            status="AVAILABLE",
            model_version="fixture-v1",
            model_sha256=DIGEST,
            feature_version="v1",
            feature_schema_sha256="d" * 64,
        )
        rows.append(
            IntervalSample(
                forecast=point,
                regime="regular",
                actual_units=110 if index < 21 else 109,
                outcome_extract_cutoff=_opening(day + 8 * DAY),
            )
        )
    options = dict(
        seller_id=SELLER,
        product_id=PRODUCT,
        horizon_days=7,
        model_sha256=DIGEST,
        test_start_date=split,
    )
    report = validate_reorder_bound(rows, **options)
    assert report is not None
    assert (
        report.radius_units == 10
        and report.validation_windows == report.within_upper_bound == 32
    )
    assert report.coverage_lower_bound >= Decimal("0.90")
    assert report == validate_reorder_bound(reversed(rows), **options)
    assert validate_reorder_bound(rows[:30], **options) is None


def test_worker_replay_and_same_day_supplier_change(decision_db, monkeypatch):
    product, _ = _seed(decision_db, stock=0, assessment=False)
    foreign = _product(decision_db)
    with decision_db() as session:
        row = session.get(Product, product.id)
        Product.metadata.create_all(
            session.get_bind(), tables=[InventoryRiskAssessment.__table__]
        )
        now = datetime.now(timezone.utc)
        as_of = SalesVelocityService.business_date_for_seller(row.seller, now)
        SalesVelocityService(session).calculate_for_product(
            product=row, as_of_date=as_of - DAY
        )
    monkeypatch.setattr(reorder_recommendation_tasks, "SessionLocal", decision_db)
    run = reorder_recommendation_tasks.calculate_reorder_recommendations_task.run
    args = dict(seller_id=str(product.seller_id), product_id=str(product.id))
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda _: run(**args), range(2)))
    assert sorted(result["created_count"] for result in outcomes) == [0, 1]
    assert run(**args)["skipped_count"] == 1
    with decision_db() as session:
        risk = InventoryRiskService(session)
        assert (
            risk.assess_for_batch(
                seller_id=product.seller_id, as_of_date=as_of
            ).created_count
            == 1
        )
    assert (
        run(seller_id=str(foreign.seller_id), product_id=str(product.id))[
            "created_count"
        ]
        == 0
    )
    with decision_db.begin() as session:
        session.get(Product, product.id).supplier_lead_time = 14
    assert run(**args)["created_count"] == 1
    with decision_db() as session:
        rows = session.scalars(
            select(ReorderRecommendation).order_by(ReorderRecommendation.generated_at)
        ).all()
        assert [item.supplier_lead_time_days for item in rows] == [7, 14]
        assert [item.recommendation_status for item in rows] == ["EXPIRED", "OPEN"]
        assert 0 < rows[0].recommended_quantity < rows[1].recommended_quantity
        assert (
            ReorderRecommendationResponse.model_validate(rows[1]).evidence[
                "planning_method"
            ]
            == FORECAST_REORDER_VERSION
        )
        assert session.get(Product, product.id).stock_quantity == 0
        risk = InventoryRiskService(session)
        assert (
            risk.assess_for_batch(
                seller_id=product.seller_id, as_of_date=as_of
            ).created_count
            == 1
        )
        assert (
            risk.assess_for_batch(
                seller_id=product.seller_id, as_of_date=as_of
            ).skipped_count
            == 1
        )
        listed, total = InventoryIntelligenceRepository(session).reorder_list(
            seller_id=product.seller_id,
            risk_level=None,
            deadline_from=None,
            deadline_to=None,
            product_id=product.id,
            category=None,
            sort="deadline",
            limit=10,
            offset=0,
        )
        assert total == 1 and listed[0]["reorder"].id == rows[1].id
    monkeypatch.setattr(settings, "forecast_aware_reorder_enabled", False)
    assert run(**args)["created_count"] == 1


def test_generic_worker_accepts_forecast_with_no_sales_rate_and_rechecks_lead(
    decision_db, monkeypatch
):
    product, run_id = _seed(decision_db, stock=0, assessment=False, demand=False)
    monkeypatch.setattr(settings, "recommendation_action_evaluation_enabled", True)
    monkeypatch.setattr(
        "app.services.reorder_recommendation_service.load_reorder_forecast",
        lambda _, seller_id, product_id, inputs: (
            _forecast(product, inputs.evaluated_at, inputs.business_date),
            "APPROVED_MODEL",
        ),
    )
    with _client(decision_db, product.seller_id) as client:
        response = client.post(f"/api/v1/recommendations/generate/{product.id}")
        assert response.status_code == 202, response.text
        job = response.json()["job_id"]
        recommendation_tasks.run_recommendation_job.run(job)
        response = client.get(f"/api/v1/recommendations/jobs/{job}").json()
        assert response["status"] == "COMPLETED"
        assert response["result"]["recommendation"]["action"] == "REORDER"
    with decision_db() as session:
        row = session.get(Product, product.id)
        orchestrator = DecisionOrchestrator(session)
        decision = orchestrator.evaluate(
            row, _collect(session, row, scrape_run_id=run_id)
        )
        row.supplier_lead_time = 14
        assert orchestrator.finalize(row, decision).action == "HOLD"


def test_live_postgres_capture_rejects_sparse_and_foreign_forecasts(
    decision_db, monkeypatch
):
    product, _ = _seed(decision_db, demand=False, assessment=False)
    foreign = _product(decision_db)
    monkeypatch.setenv("FORECAST_ML_MODE", "enabled")
    with decision_db() as session:
        Product.metadata.create_all(
            session.get_bind(),
            tables=[
                ProductMarketplaceListing.__table__,
                ProductPriceHistory.__table__,
            ],
        )
        now = datetime.now(timezone.utc)
        inputs = ReorderInputs(
            lead_days=7,
            review_days=7,
            buffer_days=3,
            minimum_order=None,
            pack_size=None,
            business_date=now.astimezone(BUSINESS_TIMEZONE).date(),
            evaluated_at=now,
            confirmed_incoming=None,
            verified_zero_sales=False,
        )
        result, reason = load_reorder_forecast(
            session,
            seller_id=product.seller_id,
            product_id=product.id,
            inputs=inputs,
        )
        assert result is not None and result.forecast.product_id == product.id
        assert reason == "ML_REQUIRES_REGULAR_VERIFIED_HISTORY"
        assert result.source == "insufficient_data"
        blocked, reason = load_reorder_forecast(
            session,
            seller_id=foreign.seller_id,
            product_id=product.id,
            inputs=inputs,
        )
        assert blocked is None and reason == "FORECAST_EVIDENCE_UNAVAILABLE"
        assert session.get(Product, product.id) is not None


def test_model_revision_changes_the_plan_key_but_recapture_is_idempotent(monkeypatch):
    inputs = _inputs(stock=0, rate=None)
    first_forecast = _forecast(inputs["product"], NOW, AS_OF, units="70")
    _patch_forecast(monkeypatch, first_forecast)
    first = _run(**inputs)
    recaptured = first_forecast.model_copy(
        update={
            "forecast": first_forecast.forecast.model_copy(
                update={
                    "forecast_origin": NOW + timedelta(seconds=1),
                    "generated_at": NOW + timedelta(seconds=1),
                }
            ),
        }
    )
    _patch_forecast(monkeypatch, recaptured)
    assert _run(**inputs).calculation_version == first.calculation_version

    replacement = first_forecast.model_copy(
        update={
            "forecast": first_forecast.forecast.model_copy(
                update={
                    "model_version": "catboost@replacement",
                    "expected_units": Decimal("140"),
                }
            ),
        }
    )
    _patch_forecast(monkeypatch, replacement)
    changed = _run(**inputs)
    assert changed.recommended_quantity > first.recommended_quantity
    assert changed.calculation_version != first.calculation_version


def test_replacement_model_publishes_a_new_saved_plan(decision_db, monkeypatch):
    product, _ = _seed(decision_db, stock=0, assessment=False)
    units = ["70"]

    def approved(_, seller_id, product_id, inputs):
        result = _forecast(
            product, inputs.evaluated_at, inputs.business_date, units=units[0]
        )
        return result, "APPROVED_MODEL"

    monkeypatch.setattr(
        "app.services.reorder_recommendation_service.load_reorder_forecast",
        approved,
    )
    monkeypatch.setattr(reorder_recommendation_tasks, "SessionLocal", decision_db)
    run = reorder_recommendation_tasks.calculate_reorder_recommendations_task.run
    scope = {"seller_id": str(product.seller_id), "product_id": str(product.id)}
    assert run(**scope)["created_count"] == 1
    assert run(**scope)["skipped_count"] == 1
    units[0] = "140"
    assert run(**scope)["created_count"] == 1
    assert run(**scope)["skipped_count"] == 1
    with decision_db() as session:
        rows = session.scalars(
            select(ReorderRecommendation).order_by(ReorderRecommendation.generated_at)
        ).all()
        assert [row.recommended_quantity for row in rows] == [170, 340]
        assert [row.recommendation_status for row in rows] == ["EXPIRED", "OPEN"]
        assert session.get(Product, product.id).stock_quantity == 0
