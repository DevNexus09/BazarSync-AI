from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.demand_elasticity_estimate import DemandEstimateDataStatus, DemandEstimationMethod
from app.services.recommendation_evidence_service import Freshness
from test_forecast_assisted_pricing import _priced_row

pytest_plugins = ("test_decision_orchestrator",)


def pooled(*, elasticity="-1.0", passed=True):
    return SimpleNamespace(
        id=uuid4(),
        elasticity=Decimal(elasticity),
        estimation_method=DemandEstimationMethod.POOLED_CATEGORY,
        quality_metrics={"out_of_time": {"passed": passed, "improvement_rate": 0.2}},
        confidence=Decimal("80.00"),
        sample_count=40,
        baseline_units=Decimal("10"),
        observation_start=date(2026, 8, 1),
        observation_end=date(2026, 11, 20),
        data_status=DemandEstimateDataStatus.SUFFICIENT,
        calculation_version="pooled-v1",
    )


@pytest.fixture
def selection(monkeypatch):
    calls = []

    def setup(*, enabled=True, record=None, baseline_units="300"):
        monkeypatch.setattr(settings, "forecast_assisted_pricing_selection_enabled", enabled)
        baseline = (
            {"status": "AVAILABLE", "forecast": {"expected_units": baseline_units}, "uncertainty": {"status": "uncalibrated"}}
            if baseline_units is not None
            else {"status": "UNAVAILABLE"}
        )
        monkeypatch.setattr(
            "app.services.dynamic_pricing_service.load_pricing_forecast_evidence",
            lambda *_, **__: {"baseline_demand_forecast": baseline, "price_response": {"status": "UNKNOWN"}},
        )

        def latest(*_, **kwargs):
            calls.append(kwargs)
            return record

        monkeypatch.setattr("app.services.pooled_elasticity_service.latest_pooled_estimate", latest)
        return calls

    return setup


def test_validated_response_selects_the_best_constraint_safe_price(selection):
    selection(record=pooled())
    row = _priced_row(db=Mock())

    # Cost 78 + 5% fee; elasticity -1 makes the highest allowed price (106, 6% cap) most profitable.
    assert row.action == "PRICE_RAISE"
    assert row.recommended_price == Decimal("106")
    assert row.recommendation_status == "OPEN"
    assert row.estimation_method == DemandEstimationMethod.POOLED_CATEGORY
    assert row.profit_impact > 0
    audit = row.evidence
    assert Decimal(audit["recommended_target_price"]) == Decimal("106")
    assert audit["price_response"]["status"] == "VALIDATED"
    assert Decimal(audit["selected"]["candidate_price"]) == Decimal("106")
    allowed = [item for item in audit["candidates"] if item["is_allowed"]]
    assert all(item["expected_units"] is not None for item in allowed)
    # Never ranks a price MarginGuard rejected.
    assert all(item["expected_units"] is None for item in audit["candidates"] if not item["is_allowed"])
    assert all("PRICE_RESPONSE_UNVALIDATED" not in item["rejection_reasons"] for item in allowed)


def test_failed_out_of_time_validation_keeps_hold(selection):
    selection(record=pooled(passed=False))
    row = _priced_row(db=Mock())

    assert row.action == "HOLD"
    assert row.recommended_price == row.current_price
    assert row.evidence["recommended_target_price"] is None
    assert row.evidence["price_response"]["reason"] == "OUT_OF_TIME_VALIDATION_NOT_PASSED"


def test_missing_baseline_forecast_keeps_hold(selection):
    selection(record=pooled(), baseline_units=None)
    row = _priced_row(db=Mock())

    assert row.action == "HOLD"
    assert row.evidence["price_response"]["reason"] == "BASELINE_FORECAST_UNAVAILABLE"


def test_missing_pooled_estimate_keeps_hold(selection):
    selection(record=None)
    row = _priced_row(db=Mock())

    assert row.action == "HOLD"
    assert row.evidence["price_response"]["reason"] == "NO_POOLED_ESTIMATE"


def test_stale_market_keeps_hold(selection, monkeypatch):
    selection(record=pooled())
    row = _priced_row(status=Freshness.STALE, db=Mock())

    assert row.action == "HOLD"
    assert row.evidence["price_response"]["reason"] == "INSUFFICIENT_FRESH_COMPETITOR_PRICES"


def test_small_gain_keeps_the_current_price(selection):
    # Elasticity -5: 102 is best, but only ~0.7% more profit, under the 2% minimum improvement.
    selection(record=pooled(elasticity="-5.0"))
    row = _priced_row(db=Mock())

    assert row.recommended_price == row.current_price
    assert row.action == "HOLD"


def test_flag_off_never_reads_pooled_estimates(selection):
    calls = selection(enabled=False, record=pooled())
    row = _priced_row(db=Mock())

    assert row.action == "HOLD"
    assert calls == []
    assert row.evidence["price_response"] == {"status": "UNKNOWN"}
