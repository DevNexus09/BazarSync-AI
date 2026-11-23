from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.core.config import settings
from app.models.demand_elasticity_estimate import DemandEstimateDataStatus, DemandEstimationMethod
from app.services.demand_response_service import DemandResponseService
from app.services.pooled_elasticity_service import out_of_time_passed


def _db_with_product():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(id=uuid4())
    return db


def _record():
    return SimpleNamespace(
        id=uuid4(), estimation_method=DemandEstimationMethod.POOLED_CATEGORY, elasticity=Decimal("-1.6"), sample_count=40,
        baseline_units=Decimal("9"), observation_start=date(2026, 8, 1), observation_end=date(2026, 11, 20),
        quality_metrics={"out_of_time": {"passed": True}}, confidence=Decimal("78.00"),
        data_status=DemandEstimateDataStatus.SUFFICIENT, calculation_version="pooled-v1",
    )


def test_request_path_uses_stored_pooled_estimate_when_enabled():
    seller_id, product_id = uuid4(), uuid4()
    record = _record()
    with patch.object(settings, "demand_response_pooling_enabled", True), patch(
        "app.services.pooled_elasticity_service.latest_pooled_estimate", return_value=record
    ) as lookup:
        result = DemandResponseService(_db_with_product()).estimate_for_product(seller_id=seller_id, product_id=product_id, as_of_date=date(2026, 11, 23))

    assert result.method == DemandEstimationMethod.POOLED_CATEGORY
    assert result.elasticity == Decimal("-1.6")
    assert result.evidence["estimate_id"] == str(record.id)
    assert lookup.call_args.kwargs == {"seller_id": seller_id, "product_id": product_id, "as_of_date": date(2026, 11, 23)}


def test_request_path_ignores_pooling_when_disabled():
    with patch.object(settings, "demand_response_pooling_enabled", False), patch(
        "app.services.pooled_elasticity_service.latest_pooled_estimate"
    ) as lookup, patch.object(DemandResponseService, "_load_observations_from_sales_records", return_value=[]):
        result = DemandResponseService(_db_with_product()).estimate_for_product(seller_id=uuid4(), product_id=uuid4(), as_of_date=date(2026, 11, 23))

    lookup.assert_not_called()
    assert result.method != DemandEstimationMethod.POOLED_CATEGORY


def test_pooled_estimate_feeds_learned_uncertainty_band():
    service = DemandResponseService(None)
    record = _record()
    estimate = service.forecast_candidate_units(
        current_price=Decimal("100"), candidate_price=Decimal("110"), baseline_units=Decimal("100"), forecast_horizon_days=30,
        baseline_period={}, estimate=SimpleNamespace(
            method=record.estimation_method, elasticity=record.elasticity, evidence={}, confidence=record.confidence,
            data_status=record.data_status, calculation_version=record.calculation_version,
        ),
    )
    assert estimate.assumptions["uncertainty_band"] == "0.35"


def test_out_of_time_passed_requires_an_explicit_pass():
    assert out_of_time_passed(SimpleNamespace(quality_metrics={"out_of_time": {"passed": True}}))
    assert not out_of_time_passed(SimpleNamespace(quality_metrics={"out_of_time": {"passed": "yes"}}))
    assert not out_of_time_passed(SimpleNamespace(quality_metrics={}))
    assert not out_of_time_passed(None)
