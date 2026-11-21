from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.models.demand_elasticity_estimate import (
    DemandEstimateDataStatus,
    DemandEstimationMethod,
)
from app.models.sales_record import SalesRecordStatus
from app.services.comprehensive_demo_seed_service import (
    ComprehensiveDemoSeedService,
    SCENARIOS,
)
from app.services.demand_response_service import (
    DemandElasticityResult,
    DemandResponseService,
)


def test_scenario_matrix_has_stable_complete_p01_to_p15_assignment():
    assert [item.code for item in SCENARIOS] == [f"P{index:02d}" for index in range(1, 16)]
    assert {item.pricing_intent for item in SCENARIOS} == {
        "LOWER",
        "RAISE",
        "HOLD",
        "INSUFFICIENT_DATA",
    }
    assert SCENARIOS[4].incoming > 0
    assert SCENARIOS[4].moq % SCENARIOS[4].pack_size == 0
    assert SCENARIOS[14].demand == "sparse"


def test_no_recent_pattern_never_generates_units_in_final_35_days():
    rng = MagicMock()
    rng.random.return_value = 0
    values = [
        ComprehensiveDemoSeedService._daily_quantity("no_recent", offset, rng)
        for offset in range(120)
    ]
    assert any(values[:85])
    assert values[85:] == [0] * 35


def test_nullable_elasticity_window_is_application_idempotent():
    existing = SimpleNamespace(id=uuid4())
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db = MagicMock()
    db.execute.return_value = result
    service = DemandResponseService(db)
    estimate = DemandElasticityResult(
        method=DemandEstimationMethod.CONSERVATIVE_HEURISTIC,
        elasticity=Decimal("-0.8"),
        sample_count=0,
        baseline_units=None,
        observation_start=None,
        observation_end=None,
        price_range=None,
        quality_metrics={},
        confidence=Decimal("35"),
        data_status=DemandEstimateDataStatus.LIMITED,
        calculation_version="demo-comp-v5",
        evidence={},
    )

    saved = service.persist_estimate(
        seller_id=uuid4(), product_id=uuid4(), estimate=estimate
    )

    assert saved is existing
    db.add.assert_not_called()


def test_sales_loader_uses_transaction_price_and_marks_promotion_overlap():
    seller_id = uuid4()
    product_id = uuid4()
    sold_at = datetime(2026, 11, 5, tzinfo=timezone.utc)
    sale = SimpleNamespace(
        seller_id=seller_id,
        product_id=product_id,
        sold_at=sold_at,
        unit_price=Decimal("899.00"),
        quantity_sold=2,
        returned_units=0,
        refunded_restocked_units=0,
        status=SalesRecordStatus.COMPLETED,
        is_test_order=False,
        source_reference="sale-1",
    )
    promotion = SimpleNamespace(
        planned_start_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        planned_end_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
    )
    first = MagicMock()
    first.scalars.return_value.all.return_value = [sale]
    second = MagicMock()
    second.scalars.return_value.all.return_value = [promotion]
    db = MagicMock()
    db.execute.side_effect = [first, second]

    rows = DemandResponseService(db)._load_observations_from_sales_records(
        seller_id=seller_id,
        product_id=product_id,
        as_of_date=date(2026, 11, 21),
    )

    assert rows[0].price == Decimal("899.00")
    assert rows[0].promotion_active is True

