from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from statistics import NormalDist, stdev
import math
from unittest.mock import patch

from app.core.config import settings
from app.services.reorder_recommendation_service import ReorderRecommendationService
from app.services.safety_stock import product_service_level, variability_safety_stock
from tests.test_reorder_recommendation_service import (
    FakeReorderRepository,
    inventory,
    product,
    seller,
    stockout,
    velocity,
)

AS_OF = date(2026, 6, 29)
START = AS_OF - timedelta(days=55)


def alternating_history(days: int = 56):
    # 6, 14, 6, 14 ... mean 10, sample std dev ~4.04
    return {START + timedelta(days=offset): (6 if offset % 2 else 14) for offset in range(days)}


class HistoryRepository(FakeReorderRepository):
    def __init__(self) -> None:
        super().__init__()
        self.history = {}
        self.history_calls = []

    def daily_demand_history(self, *, seller_id, product_ids, start, end):
        self.history_calls.append((seller_id, tuple(product_ids), start, end))
        return {pid: self.history[(seller_id, pid)] for pid in product_ids if (seller_id, pid) in self.history}


def test_formula_z_sigma_sqrt_lead_time():
    units = alternating_history()
    result = variability_safety_stock(
        units_by_day=units, available_by_day={}, start=START, end=AS_OF, lead_time_days=8, service_level=Decimal("0.95"), min_days=14,
    )
    expected = math.ceil(NormalDist().inv_cdf(0.95) * stdev(units.values()) * math.sqrt(8))

    assert result.status == "ok"
    assert result.units == expected == 19
    assert result.days_used == 56
    assert result.z_score == Decimal("1.6449")


def test_zero_sale_days_count_but_stockout_days_do_not():
    units = {START: 10}
    available = {START + timedelta(days=offset): 0 for offset in range(1, 50)}
    result = variability_safety_stock(
        units_by_day=units, available_by_day=available, start=START, end=AS_OF, lead_time_days=8, service_level=Decimal("0.95"), min_days=14,
    )
    # 49 stocked-out days are excluded, leaving 7 usable days: too little history.
    assert result.status == "insufficient_history"
    assert (result.days_used, result.days_censored) == (7, 49)


def test_per_product_service_level_override():
    assert product_service_level({"reorder_service_level": "0.99"}, Decimal("0.95")) == Decimal("0.99")
    assert product_service_level({"reorder_service_level": "1.5"}, Decimal("0.95")) == Decimal("0.95")
    assert product_service_level({"reorder_service_level": "abc"}, Decimal("0.95")) == Decimal("0.95")
    assert product_service_level(None, Decimal("0.95")) == Decimal("0.95")


def _calculate(repo, owner, item, **flags):
    with patch.multiple(settings, forecast_aware_reorder_enabled=False, **flags):
        service = ReorderRecommendationService(repository=repo)
        return service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            stockout_prediction=stockout(owner, item),
            as_of_date=AS_OF,
        ).recommendation


def test_flag_on_sizes_reorder_point_from_variability():
    owner, repo = seller(), HistoryRepository()
    item = product(owner)
    repo.history[(owner.id, item.id)] = (alternating_history(), {})

    rec = _calculate(repo, owner, item, variability_safety_stock_enabled=True)

    # rate 10 × lead 8 = 80, + 19 safety units; target adds the 7-day review period.
    assert rec.reorder_point == 99
    assert rec.target_stock == 169
    assert rec.evidence["safety_stock_method"] == "variability"
    assert rec.evidence["safety_stock_units"] == 19
    assert rec.evidence["safety_stock_service_level"] == "0.95"
    assert rec.calculation_version.endswith("+vss")
    assert repo.history_calls == [(owner.id, (item.id,), START, AS_OF)]


def test_flag_on_without_enough_history_falls_back_to_buffer_days():
    owner, repo = seller(), HistoryRepository()
    item = product(owner)
    repo.history[(owner.id, item.id)] = ({AS_OF: 5}, {day: 0 for day in (START + timedelta(days=o) for o in range(50))})

    rec = _calculate(repo, owner, item, variability_safety_stock_enabled=True)

    assert rec.reorder_point == 110  # 10 × (8 + 3 buffer days), as before
    assert rec.evidence["safety_stock_method"] == "buffer_days"
    assert rec.evidence["safety_stock_status"] == "insufficient_history"
    assert rec.calculation_version.endswith("+vss")


def test_flag_off_is_unchanged_and_reads_no_history():
    owner, repo = seller(), HistoryRepository()
    item = product(owner)
    repo.history[(owner.id, item.id)] = (alternating_history(), {})

    rec = _calculate(repo, owner, item, variability_safety_stock_enabled=False)

    assert (rec.reorder_point, rec.target_stock, rec.recommended_quantity) == (110, 180, 140)
    assert rec.evidence["safety_stock_method"] == "buffer_days"
    assert "safety_stock_units" not in rec.evidence
    assert not rec.calculation_version.endswith("+vss")
    assert repo.history_calls == []


def test_batch_reads_history_per_seller_only():
    owner_a, owner_b, repo = seller(), seller(), HistoryRepository()
    item_a, item_b = product(owner_a), product(owner_b)
    repo.products = [(item_a, owner_a), (item_b, owner_b)]
    for owner, item in ((owner_a, item_a), (owner_b, item_b)):
        repo.velocities[item.id] = velocity(owner, item, rate="10.0000")
        repo.inventory[item.id] = inventory(owner, item, on_hand=40)
    repo.history[(owner_a.id, item_a.id)] = (alternating_history(), {})

    with patch.multiple(settings, forecast_aware_reorder_enabled=False, variability_safety_stock_enabled=True):
        ReorderRecommendationService(repository=repo).calculate_for_batch(as_of_date=AS_OF)

    assert {call[0] for call in repo.history_calls} == {owner_a.id, owner_b.id}
    assert all(len(call[1]) == 1 for call in repo.history_calls)
    by_product = {row.product_id: row for row in repo.rows.values()}
    assert by_product[item_a.id].evidence["safety_stock_method"] == "variability"
    # Seller B has no history: falls back, and never sees seller A's data.
    assert by_product[item_b.id].evidence["safety_stock_status"] == "history_unavailable"
