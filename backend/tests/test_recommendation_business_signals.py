from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.models.sales_data_coverage import SalesDataCompletenessStatus
from app.models.sales_velocity import SalesVelocityDataStatus
from app.services import recommendation_business_signals as signals
from app.services.margin_guard import MarginGuard
from app.services.recommendation_service import RecommendationService
from app.services.sales_velocity_service import SalesVelocityCalculation

D = Decimal
NOW = datetime(2026, 11, 14, 8, tzinfo=timezone.utc)


@pytest.fixture
def inputs(monkeypatch):
    product = SimpleNamespace(
        id=uuid4(),
        seller_id=uuid4(),
        seller=SimpleNamespace(timezone="UTC"),
        selling_price=D("100.00"),
        cost_price=D("40"),
        supplier_lead_time=7,
        stock_quantity=1000,
        specifications={},
    )
    velocity = SalesVelocityCalculation(
        product.id,
        product.seller_id,
        NOW.date() - timedelta(days=1),
        30,
        30,
        300,
        0,
        300,
        D("10.0000"),
        10,
        D("100"),
        SalesVelocityDataStatus.SUFFICIENT,
        "test",
        {"valid_sales_records": 10},
    )
    measure = Mock(return_value=velocity)
    monkeypatch.setattr(signals.SalesVelocityService, "measure_for_product", measure)
    inventory = SimpleNamespace(
        id=uuid4(),
        quantity_available=1000,
        quantity_on_hand=1000,
        quantity_reserved=0,
        quantity_incoming=0,
        captured_at=NOW - timedelta(hours=1),
    )
    monkeypatch.setattr(
        signals.ReorderRecommendationRepository,
        "latest_inventory_for_products",
        lambda *_args, **_kwargs: {product.id: inventory},
    )
    policy = SimpleNamespace(
        currency="BDT",
        price_increment=D("0.05"),
        minimum_margin_rate=D("0.20"),
        minimum_unit_profit=D("0"),
        minimum_allowed_price=None,
        maximum_allowed_price=None,
        maximum_price_decrease_rate=None,
        maximum_price_increase_rate=None,
    )
    fee = SimpleNamespace(
        id=uuid4(),
        currency="BDT",
        version="actual",
        is_default=False,
        percentage_commission_rate=D("0.10"),
        payment_fee_rate=D("0.02"),
        fixed_per_order_fee=D("1"),
        fixed_per_unit_fee=D("0"),
        fulfilment_fee=D("0"),
        shipping_subsidy=D("0"),
        other_variable_cost=D("0"),
    )
    policies = SimpleNamespace(
        get_product_policy=lambda **_: policy, effective_fee_policy=lambda **_: fee
    )
    service = signals.RecommendationBusinessSignals(Mock())
    service._guard = MarginGuard(
        Mock(), pricing_policy_service_factory=lambda _db: policies
    )
    coverage = Mock(return_value=None)
    monkeypatch.setattr(service, "_sales_window_coverage", coverage)
    return SimpleNamespace(
        product=product,
        inventory=inventory,
        velocity=velocity,
        measure=measure,
        service=service,
        policy=policy,
        fee=fee,
        coverage=coverage,
    )


def _analyze(inputs, statuses=(None, None), prices=("89.10", "89.15")):
    return inputs.service.analyze(
        inputs.product,
        [
            {"price": D(price), "stock_status": status}
            for price, status in zip(prices, statuses, strict=True)
        ],
        now=NOW,
    )


def test_stock_status_does_not_change_measured_velocity(inputs):
    unknown = _analyze(inputs, ("UNKNOWN", None))
    mixed = _analyze(inputs, ("OUT_OF_STOCK", "IN_STOCK"))
    assert unknown["competitor_availability_ratio"] is None
    assert unknown["out_of_stock_competitor_count"] is None
    assert mixed["competitor_availability_ratio"] == 0.5
    assert mixed["out_of_stock_competitor_count"] == 1
    assert (
        unknown["estimated_days_of_stock_left"]
        == mixed["estimated_days_of_stock_left"]
        == 100
    )
    assert mixed["inventory_evidence"]["daily_net_sales_rate"] == "10.0000"
    assert (
        mixed["inventory_evidence"]["demand_status"] == "ESTIMATED_FROM_RECORDED_SALES"
    )


@pytest.mark.parametrize(
    ("records", "net", "days", "complete", "status", "rate"),
    [
        (0, 0, 0, False, "INSUFFICIENT", None),
        (1, 2, 1, False, "INSUFFICIENT", None),
        (0, 0, 0, True, "OBSERVED", "0.0000"),
        (10, 0, 10, True, "OBSERVED", "0.0000"),
        (10, 300, 10, True, "OBSERVED", "10.0000"),
    ],
)
def test_sales_evidence(inputs, records, net, days, complete, status, rate):
    from dataclasses import replace

    inputs.measure.return_value = replace(
        inputs.velocity,
        net_units_sold=net,
        returned_units=300 if records and not net else 0,
        metadata={"valid_sales_records": records},
        sales_days=days,
        daily_sales_rate=(D(net) / 30).quantize(D("0.0001")),
    )
    if complete:
        inputs.coverage.return_value = SimpleNamespace(
            id=uuid4(),
            completeness_status=SalesDataCompletenessStatus.COMPLETE,
        )
    results = _analyze(inputs)
    evidence = results["inventory_evidence"]
    assert evidence["demand_status"] == status
    assert evidence["daily_net_sales_rate"] == rate
    if not net or status == "INSUFFICIENT":
        assert results["action"] == "HOLD"
        assert results["estimated_days_of_stock_left"] is None
        assert results["stock_risk_score"] is None


def test_zero_inventory_reuses_reorder_and_missing_lead_time_holds(inputs):
    inputs.inventory.quantity_on_hand = inputs.inventory.quantity_available = 0
    inputs.product.stock_quantity = 0
    reorder = _analyze(inputs)
    assert reorder["action"] == "REORDER"
    assert reorder["inventory_evidence"]["reorder"]["reorder_point"] > 0
    assert reorder["estimated_days_of_stock_left"] == 0
    assert reorder["stock_risk_score"] == 1
    inputs.product.supplier_lead_time = 0
    hold = _analyze(inputs)
    assert hold["action"] == "HOLD"
    assert hold["stock_risk_score"] is None
    assert "MISSING_SUPPLIER_LEAD_TIME" in hold["reason_codes"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("id", None, "MISSING_FEE_DATA"),
        ("cost_price", None, "MISSING_COST_DATA"),
        ("percentage_commission_rate", D("0.79"), "INVALID_POLICY"),
        ("currency", "USD", "UNSUPPORTED_CURRENCY"),
        ("minimum_allowed_price", D("89.15"), "BELOW_ABSOLUTE_MINIMUM"),
        ("maximum_price_decrease_rate", D("0.10"), "EXCEEDS_MAXIMUM_DECREASE"),
    ],
)
def test_financial_constraints_hold(inputs, field, value, reason):
    for source in (inputs.fee, inputs.product, inputs.policy):
        if hasattr(source, field):
            setattr(source, field, value)
            break
    results = _analyze(inputs)
    assert results["action"] == "HOLD"
    assert reason in results["reason_codes"]
    assert results["candidate_price"] is None
    if reason in {
        "MISSING_FEE_DATA",
        "MISSING_COST_DATA",
        "INVALID_POLICY",
        "UNSUPPORTED_CURRENCY",
    }:
        assert (
            results["pricing_evidence"]["current_offer"]["contribution_margin_per_unit"]
            is None
        )


def test_decimal_candidate_and_final_policy_change(inputs, monkeypatch):
    results = _analyze(inputs)
    assert results["action"] == "LOWER"
    assert results["competitor_median_price"] == "89.125"
    assert results["candidate_price"] == "89.10"
    current = results["pricing_evidence"]["current_offer"]
    assert current["gross_revenue_per_unit"] == "100.00"
    assert current["gross_margin_per_unit"] == "60.00"
    assert current["contribution_margin_per_unit"] == "47.00"
    assert current["estimated_profit"] is None

    service = RecommendationService(Mock())
    monkeypatch.setattr(
        "app.services.recommendation_service.MarginGuard",
        lambda _db: inputs.service._guard,
    )
    assert service._guard_business_decision(inputs.product, results)[0] == "LOWER"
    inputs.policy.minimum_allowed_price = D("90")
    assert service._guard_business_decision(inputs.product, results)[:2] == (
        "HOLD",
        "LOW",
    )


def test_minimum_margin_exact_boundary(inputs):
    inputs.fee.percentage_commission_rate = D("0.10")
    inputs.fee.payment_fee_rate = inputs.fee.fixed_per_order_fee = D("0")
    inputs.product.cost_price = D("56")
    assert _analyze(inputs, prices=("80", "80"))["action"] == "LOWER"
    below = _analyze(inputs, prices=("79.99", "79.99"))
    assert below["action"] == "HOLD"
    assert "BELOW_MINIMUM_SAFE_PRICE" in below["reason_codes"]


def test_stale_inventory_cannot_supply_stock_coverage(inputs):
    inputs.inventory.captured_at = NOW - timedelta(days=10)
    results = _analyze(inputs)
    assert results["action"] == "HOLD"
    assert results["estimated_days_of_stock_left"] is None
    assert results["inventory_evidence"]["daily_net_sales_rate"] == "10.0000"
    assert "MISSING_OR_STALE_INVENTORY_SNAPSHOT" in results["reason_codes"]


def test_final_guard_rejects_raise_without_a_valid_exact_price(inputs, monkeypatch):
    service = RecommendationService(Mock())
    monkeypatch.setattr(
        "app.services.recommendation_service.MarginGuard",
        lambda _db: inputs.service._guard,
    )
    inputs.policy.maximum_price_increase_rate = D("0.10")
    for candidate in (None, "100.00", "110.05", "109.99"):
        result = service._guard_business_decision(
            inputs.product,
            {
                "action": "RAISE",
                "confidence": 0.8,
                "candidate_price": candidate,
            },
        )
        assert result[:2] == ("HOLD", "LOW")
