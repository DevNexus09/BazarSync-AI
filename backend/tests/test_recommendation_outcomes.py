from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.services.recommendation_outcomes import (
    SaleLine,
    confidence_band,
    evaluate_price_change,
    evaluate_reorder,
    reorder_window_days,
    track_record,
)

DAY = date(2026, 10, 1)


def days(n, value):
    return {DAY + timedelta(days=i): value for i in range(n)}


def test_reorder_window_covers_lead_time_and_buffer():
    assert reorder_window_days(14, 8, 3) == 14
    assert reorder_window_days(14, 20, 5) == 25


def test_reorder_hit_when_stock_never_ran_out():
    result = evaluate_reorder(
        decided_on=DAY, window_days=14, daily_sales_rate=Decimal("8"), reorder_deadline=DAY + timedelta(days=2),
        units_by_day=days(14, 9), available_by_day=days(14, 5),
    )
    assert result.observed and result.hit is True
    assert (result.predicted_value, result.observed_value) == (Decimal("112.0000"), Decimal("126"))
    assert result.details["units_error_rate"] == "0.1250"
    assert result.details["stockout_days"] == 0


def test_reorder_miss_records_first_stockout_and_deadline():
    available = days(14, 5) | {DAY + timedelta(days=1): 0, DAY + timedelta(days=6): 0}
    result = evaluate_reorder(
        decided_on=DAY, window_days=14, daily_sales_rate=Decimal("8"), reorder_deadline=DAY + timedelta(days=2),
        units_by_day={}, available_by_day=available,
    )
    assert result.hit is False
    assert result.details["first_stockout"] == (DAY + timedelta(days=1)).isoformat()
    assert result.details["stockout_before_deadline"] is True
    assert result.details["stockout_days"] == 2


def test_reorder_without_stock_counts_is_unavailable_not_a_hit():
    result = evaluate_reorder(
        decided_on=DAY, window_days=14, daily_sales_rate=Decimal("8"), reorder_deadline=None, units_by_day=days(14, 8), available_by_day={},
    )
    assert result.observed is False and result.hit is None
    assert result.details["unavailable_reason"] == "no_stock_snapshots_in_window"


def price_case(after_price="106.00", predicted="300.00", before_units=10, after_units=9):
    return dict(
        before=[SaleLine(DAY, Decimal("100.00"), before_units)],
        after=[SaleLine(DAY + timedelta(days=14), Decimal(after_price), after_units)],
        recommended_price=Decimal("106.00"),
        current_price=Decimal("100.00"),
        unit_cost=Decimal("78.00"),
        percentage_fee_rate=Decimal("0.05"),
        fixed_fee_amount=Decimal("0.00"),
        predicted_profit_impact=Decimal(predicted) if predicted is not None else None,
        window_days=14,
    )


def test_price_change_compares_profit_before_and_after_in_decimal():
    result = evaluate_price_change(**price_case())
    # before: 10 × (100 − 5 − 78) = 170.00; after: 9 × (106 − 5.30 − 78) = 204.30
    assert result.observed
    assert result.observed_value == Decimal("34.30")
    assert result.predicted_value == Decimal("140.00")  # 300 over 30 days → 14 days
    assert result.hit is True


def test_price_change_miss_when_profit_falls():
    result = evaluate_price_change(**price_case(after_units=6))
    assert result.observed_value < 0
    assert result.hit is False


def test_price_not_applied_cannot_be_attributed():
    result = evaluate_price_change(**price_case(after_price="100.00"))
    assert result.observed is False and result.hit is None
    assert result.details["unavailable_reason"] == "price_not_applied"


def test_no_sales_is_unavailable_not_zero():
    case = price_case()
    case["after"] = []
    result = evaluate_price_change(**case)
    assert result.observed is False and result.observed_value is None
    assert result.details["unavailable_reason"] == "no_priced_sales_before_or_after"


def test_track_record_overall_and_by_confidence_band():
    rows = [(True, Decimal("75"))] * 18 + [(False, Decimal("72"))] * 4 + [(True, Decimal("50"))] * 3 + [(None, Decimal("50"))] * 5
    record = track_record(rows, min_outcomes=20)

    assert record["outcomes"] == 25 and record["hit_rate"] == 0.84 and record["reliable"] is True
    assert record["bands"]["HIGH"] == {"outcomes": 22, "hit_rate": 0.8182, "reliable": True}
    assert record["bands"]["MEDIUM"] == {"outcomes": 3, "hit_rate": 1.0, "reliable": False}
    assert record["bands"]["LOW"] == {"outcomes": 0, "hit_rate": None, "reliable": False}


def test_confidence_bands_match_ui_labels():
    assert [confidence_band(Decimal(v)) for v in ("0", "39.99", "40", "69.99", "70", "100")] == ["LOW", "LOW", "MEDIUM", "MEDIUM", "HIGH", "HIGH"]
    assert confidence_band(None) is None
