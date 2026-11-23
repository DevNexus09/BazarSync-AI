from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch


from app.core.config import settings
from app.models.reorder_recommendation import ReorderRecommendationAction
from app.services import reorder_recommendation_service as module
from app.services.reorder_recommendation_service import ReorderRecommendationService, summarize_shadow
from tests.test_reorder_recommendation_service import FakeReorderRepository, inventory, product, seller, stockout, velocity

AS_OF = date(2026, 6, 29)


def build(owner, item, **flags):
    with patch.multiple(settings, variability_safety_stock_enabled=False, **flags):
        service = ReorderRecommendationService(repository=FakeReorderRepository())
        with patch.object(service, "_build_forecast_recommendation", side_effect=_fake_forecast) as forecast:
            rec = service.calculate_for_product(
                product=item,
                seller=owner,
                inventory_snapshot=inventory(owner, item, on_hand=40),
                sales_velocity=velocity(owner, item, rate="10.0000"),
                stockout_prediction=stockout(owner, item),
                as_of_date=AS_OF,
            ).recommendation
        return rec, forecast.call_count


def _fake_forecast(**kwargs):
    item = kwargs["product"]
    return module.ReorderRecommendation(
        seller_id=item.seller_id, product_id=item.id, as_of_date=AS_OF, action=ReorderRecommendationAction.HOLD,
        recommended_quantity=0, reorder_deadline=None, supplier_lead_time_days=8, safety_buffer_days=3, review_period_days=7,
        reorder_point=90, target_stock=150, inventory_position=40, daily_sales_rate=10, confidence_score=45,
        recommendation_status=module.ReorderRecommendationStatus.OPEN, explanation="forecast", evidence={"planning_method": "forecast"},
        calculation_version="fr-v1-test", generated_at=kwargs["inputs"].evaluated_at,
    )


def test_allowlisted_seller_uses_forecast_and_others_stay_standard():
    allowed, other = seller(), seller()
    flags = dict(forecast_aware_reorder_enabled=True, forecast_aware_reorder_seller_allowlist=f" {allowed.id} ,", forecast_aware_reorder_shadow_enabled=False)

    allowed_rec, allowed_calls = build(allowed, product(allowed), **flags)
    other_rec, other_calls = build(other, product(other), **flags)

    assert (allowed_rec.calculation_version, allowed_calls) == ("fr-v1-test", 1)
    assert other_calls == 0 and other_rec.action == ReorderRecommendationAction.REORDER
    assert "shadow" not in other_rec.evidence


def test_empty_allowlist_keeps_existing_global_behaviour():
    owner = seller()
    rec, calls = build(owner, product(owner), forecast_aware_reorder_enabled=True, forecast_aware_reorder_seller_allowlist="", forecast_aware_reorder_shadow_enabled=False)
    assert (rec.calculation_version, calls) == ("fr-v1-test", 1)


def test_shadow_records_the_other_method_without_changing_the_decision():
    owner = seller()
    rec, calls = build(owner, product(owner), forecast_aware_reorder_enabled=False, forecast_aware_reorder_seller_allowlist="", forecast_aware_reorder_shadow_enabled=True)

    assert rec.action == ReorderRecommendationAction.REORDER  # standard advice is still the decision
    assert rec.recommended_quantity == 140
    assert calls == 1
    assert rec.evidence["shadow"] == {
        "method": "forecast_aware", "action": "HOLD", "status": "OPEN", "recommended_quantity": 0,
        "reorder_point": 90, "reorder_deadline": None, "calculation_version": "fr-v1-test",
    }


def test_shadow_failure_never_blocks_primary_advice():
    owner = seller()
    with patch.multiple(settings, forecast_aware_reorder_enabled=False, forecast_aware_reorder_shadow_enabled=True, variability_safety_stock_enabled=False):
        service = ReorderRecommendationService(repository=FakeReorderRepository())
        with patch.object(service, "_build_forecast_recommendation", side_effect=RuntimeError("model down")):
            item = product(owner)
            rec = service.calculate_for_product(
                product=item, seller=owner, inventory_snapshot=inventory(owner, item, on_hand=40),
                sales_velocity=velocity(owner, item, rate="10.0000"), stockout_prediction=stockout(owner, item), as_of_date=AS_OF,
            ).recommendation

    assert rec.recommended_quantity == 140
    assert rec.evidence["shadow"] == {"method": "forecast_aware", "error": "RuntimeError"}


def test_summarize_shadow_agreement():
    def row(action, quantity, shadow):
        return SimpleNamespace(action=ReorderRecommendationAction(action), recommended_quantity=quantity, evidence={"shadow": shadow} if shadow is not None else {})

    summary = summarize_shadow([
        row("REORDER", 100, {"action": "REORDER", "recommended_quantity": 90}),
        row("REORDER", 50, {"action": "HOLD", "recommended_quantity": 0}),
        row("HOLD", 0, {"action": "HOLD", "recommended_quantity": 0}),
        row("HOLD", 0, {"method": "forecast_aware", "error": "RuntimeError"}),
        row("HOLD", 0, None),
    ])

    assert summary == {
        "recommendations": 5, "compared": 3, "shadow_failures": 1, "same_action_rate": 0.6667,
        "mean_quantity_gap": 20.0, "primary_reorders_only": 1, "shadow_reorders_only": 0,
    }
