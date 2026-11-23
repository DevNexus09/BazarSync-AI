from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import pricing_overview as api_module
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.dynamic_pricing_recommendation import DynamicPricingAction, DynamicPricingRecommendationStatus
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus
from app.schemas.pricing_overview import MarketPosition
from app.services import pricing_overview_service as service_module
from app.services.pricing_overview_service import (
    POSITION_TOLERANCE_RATE,
    ProductRow,
    RecommendationRow,
    SnapshotRow,
    market_position,
)

SELLER_A = uuid4()
SELLER_B = uuid4()
NOW = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)


def product(title: str, price: str) -> ProductRow:
    return ProductRow(uuid4(), title, None, "Grocery", Decimal(price))


def snapshot(item: ProductRow, median: str | None, minimum_safe: str = "100.00") -> SnapshotRow:
    return SnapshotRow(
        id=uuid4(),
        product_id=item.id,
        competitor_median_price=Decimal(median) if median else None,
        competitor_count=5 if median else 0,
        minimum_safe_price=Decimal(minimum_safe),
        data_status=PricingAnalyticsDataStatus.SUFFICIENT,
        calculated_at=NOW - timedelta(hours=3),
    )


def recommendation(item: ProductRow, action=DynamicPricingAction.PRICE_LOWER, status=DynamicPricingRecommendationStatus.OPEN, expires_at=None) -> RecommendationRow:
    return RecommendationRow(
        id=uuid4(),
        product_id=item.id,
        action=action,
        recommended_price=Decimal("329.00"),
        recommendation_status=status,
        confidence_score=Decimal("55.00"),
        profit_impact=Decimal("1450.00"),
        generated_at=NOW - timedelta(hours=2),
        expires_at=expires_at,
    )


RICE = product("Rice 5kg", "349.00")  # 9% above median 320
OIL = product("Oil 1L", "180.00")  # 7.7% below median 195
SOAP = product("Soap 3-pack", "120.00")  # no snapshot
SUGAR = product("Sugar 1kg", "90.00")  # below minimum safe price 100, at market
FLOUR = product("Flour 2kg", "60.00")  # B's product

DATA = {
    SELLER_A: {
        "products": [OIL, RICE, SOAP, SUGAR],
        "snapshots": [snapshot(RICE, "320.00"), snapshot(OIL, "195.00", "150.00"), snapshot(SUGAR, "90.50")],
        "recommendations": [
            recommendation(RICE),
            recommendation(OIL, action=DynamicPricingAction.PRICE_RAISE, expires_at=NOW - timedelta(days=30)),
            recommendation(SUGAR, action=DynamicPricingAction.HOLD),
        ],
        "policies": {RICE.id},
    },
    SELLER_B: {
        "products": [FLOUR],
        "snapshots": [snapshot(FLOUR, "50.00", "40.00")],
        "recommendations": [recommendation(FLOUR, status=DynamicPricingRecommendationStatus.DISMISSED)],
    },
}


class FakeRepository:
    calls: list[tuple[str, object]] = []

    def __init__(self, db) -> None:
        pass

    def products(self, *, seller_id):
        self.calls.append(("products", seller_id))
        return DATA.get(seller_id, {}).get("products", [])

    def latest_snapshots(self, *, seller_id):
        self.calls.append(("snapshots", seller_id))
        return DATA.get(seller_id, {}).get("snapshots", [])

    def latest_recommendations(self, *, seller_id):
        self.calls.append(("recommendations", seller_id))
        return DATA.get(seller_id, {}).get("recommendations", [])

    def products_with_pricing_policy(self, *, seller_id, as_of):
        self.calls.append(("policies", seller_id))
        return DATA.get(seller_id, {}).get("policies", set())


class FakeSeller:
    def __init__(self, seller_id):
        self.id = seller_id


@pytest.fixture
def client_for(monkeypatch):
    monkeypatch.setattr(service_module, "PricingOverviewRepository", FakeRepository)
    FakeRepository.calls = []

    def make(seller_id):
        app = FastAPI()
        app.include_router(api_module.router)
        app.dependency_overrides[get_current_seller] = lambda: FakeSeller(seller_id)
        app.dependency_overrides[get_db] = lambda: object()
        return TestClient(app)

    return make


def by_title(payload):
    return {row["title"]: row for row in payload["items"]}


def test_rows_positions_and_summary(client_for):
    payload = client_for(SELLER_A).get("/pricing/overview").json()
    rows = by_title(payload)

    assert payload["total"] == 4
    assert rows["Rice 5kg"]["position"] == "ABOVE_MARKET"
    assert rows["Rice 5kg"]["price_vs_median_rate"] == "0.0906"
    assert rows["Oil 1L"]["position"] == "BELOW_MARKET"
    assert rows["Sugar 1kg"]["position"] == "AT_MARKET"
    assert rows["Sugar 1kg"]["margin_at_risk"] is True
    assert rows["Rice 5kg"]["has_pricing_policy"] is True
    assert rows["Oil 1L"]["has_pricing_policy"] is False
    assert rows["Rice 5kg"]["recommendation"]["is_actionable"] is True
    # Expired and HOLD recommendations are shown but do not count as waiting.
    assert rows["Oil 1L"]["recommendation"]["is_actionable"] is False
    assert rows["Sugar 1kg"]["recommendation"]["is_actionable"] is False
    assert payload["summary"] == {
        "product_count": 4,
        "priced_above_market": 1,
        "priced_below_market": 1,
        "margin_at_risk": 1,
        "recommendations_waiting": 1,
        "without_analytics": 1,
        "products_with_pricing_policy": 1,
        "products_with_competitor_data": 3,
        "last_calculated_at": "2026-11-23T09:00:00Z",
        "position_tolerance_rate": "0.02",
    }


def test_product_without_snapshot_is_listed_as_no_market_data(client_for):
    soap = by_title(client_for(SELLER_A).get("/pricing/overview").json())["Soap 3-pack"]

    assert soap["analytics_id"] is None
    assert soap["position"] == "NO_MARKET_DATA"
    assert soap["market_median_price"] is None
    assert soap["price_vs_median_rate"] is None
    assert soap["minimum_safe_price"] is None
    assert soap["margin_at_risk"] is False
    assert soap["competitor_count"] == 0
    assert soap["recommendation"] is None


def test_pagination_keeps_summary_over_all_products(client_for):
    payload = client_for(SELLER_A).get("/pricing/overview", params={"limit": 2, "offset": 2}).json()

    assert [row["title"] for row in payload["items"]] == ["Soap 3-pack", "Sugar 1kg"]
    assert (payload["total"], payload["limit"], payload["offset"]) == (4, 2, 2)
    assert payload["summary"]["product_count"] == 4


def test_limit_is_bounded(client_for):
    assert client_for(SELLER_A).get("/pricing/overview", params={"limit": 500}).status_code == 422


def test_seller_isolation(client_for):
    payload = client_for(SELLER_B).get("/pricing/overview").json()

    assert [row["title"] for row in payload["items"]] == ["Flour 2kg"]
    assert payload["summary"]["recommendations_waiting"] == 0
    assert {seller for _, seller in FakeRepository.calls} == {SELLER_B}


def test_unknown_seller_gets_empty_overview(client_for):
    payload = client_for(uuid4()).get("/pricing/overview").json()

    assert payload["items"] == []
    assert payload["summary"]["product_count"] == 0
    assert payload["summary"]["last_calculated_at"] is None


def test_position_tolerance_boundaries():
    assert market_position(None) == MarketPosition.NO_MARKET_DATA
    assert market_position(POSITION_TOLERANCE_RATE) == MarketPosition.AT_MARKET
    assert market_position(-POSITION_TOLERANCE_RATE) == MarketPosition.AT_MARKET
    assert market_position(Decimal("0.0201")) == MarketPosition.ABOVE_MARKET
    assert market_position(Decimal("-0.0201")) == MarketPosition.BELOW_MARKET
