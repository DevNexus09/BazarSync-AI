"""Regression tests for Copilot tool bug fixes (dead-stock latest run, price simulation, event metadata)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.competitor_event import CompetitorEvent, CompetitorEventSeverity, CompetitorEventType
from app.models.dead_stock_assessment import (
    DeadStockAssessment,
    DeadStockClassification,
    DeadStockDataStatus,
    DeadStockInventoryAgeState,
    DeadStockNoSalesState,
    DeadStockRiskLevel,
    DeadStockVisibilityStatus,
)
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.demand_elasticity_estimate import DemandElasticityEstimate
from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
from app.models.product import Product
from app.models.seller import Seller
from app.services.copilot.tool_registry import SOURCE_TOOL_SPECS, SqlAlchemyCopilotToolDataAccess, _source_row_payload


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


class DeadStockAndSimulationFixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.seller = Seller(email="seller@example.com", password_hash="hash")
        self.db.add(self.seller)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def product(self, title: str, *, stock: int = 10, price: str = "100.00", cost: str = "40.00") -> Product:
        row = Product(seller_id=self.seller.id, title=title, sku=f"SKU-{title.replace(' ', '-')}", category="Shoes", cost_price=Decimal(cost), selling_price=Decimal(price), stock_quantity=stock, supplier_lead_time=7, minimum_margin=Decimal("10.00"))
        self.db.add(row)
        self.db.commit()
        return row

    def _assessment(self, product: Product, classification: DeadStockClassification, assessed: datetime) -> DeadStockAssessment:
        return DeadStockAssessment(
            seller_id=product.seller_id, product_id=product.id, as_of_date=assessed.date(), classification=classification, eligible_quantity=5,
            no_sales_state=DeadStockNoSalesState.NEVER_SOLD, inventory_age_state=DeadStockInventoryAgeState.AGE_THRESHOLD_EXCEEDED,
            visibility_status=DeadStockVisibilityStatus.VISIBILITY_DATA_UNAVAILABLE, risk_score=Decimal("90.00"), risk_level=DeadStockRiskLevel.CRITICAL,
            rule_results={}, triggered_rules=[], data_status=DeadStockDataStatus.SUFFICIENT, confidence_score=Decimal("80.00"), calculation_version="v1", assessed_at=assessed,
        )

    def _estimate(self, product: Product, assessment: DeadStockAssessment, locked: str, calculated: datetime) -> DeadStockCapitalRecoveryEstimate:
        return DeadStockCapitalRecoveryEstimate(
            seller_id=product.seller_id, product_id=product.id, dead_stock_assessment_id=assessment.id, eligible_quantity=5, unit_cost=Decimal("40.00"),
            locked_capital=Decimal(locked), estimation_method="CONSERVATIVE_HEURISTIC", estimate_status="CALCULATED", confidence_score=Decimal("80.00"), evidence={}, calculated_at=calculated, calculation_version="v1",
        )

    def test_dead_stock_summary_uses_only_each_products_latest_run(self) -> None:
        recovered = self.product("Recovered")
        stuck = self.product("Stuck")
        old = self._assessment(recovered, DeadStockClassification.DEAD_STOCK, datetime(2026, 11, 1, tzinfo=timezone.utc))
        new = self._assessment(recovered, DeadStockClassification.HEALTHY, datetime(2026, 11, 20, tzinfo=timezone.utc))
        dead = self._assessment(stuck, DeadStockClassification.DEAD_STOCK, datetime(2026, 11, 20, tzinfo=timezone.utc))
        self.db.add_all([old, new, dead])
        self.db.commit()
        self.db.add_all([
            self._estimate(recovered, old, "1000.00", datetime(2026, 11, 1, tzinfo=timezone.utc)),
            self._estimate(stuck, dead, "200.00", datetime(2026, 11, 10, tzinfo=timezone.utc)),
            self._estimate(stuck, dead, "150.00", datetime(2026, 11, 20, tzinfo=timezone.utc)),
        ])
        self.db.commit()

        payload, _ = SqlAlchemyCopilotToolDataAccess(self.db).get_dead_stock_summary(seller_id=self.seller.id, product_id=None, from_date=None, to_date=None, marketplace=None, category=None, limit=10, offset=0)

        self.assertEqual(1, payload["summary"]["dead_stock_product_count"])
        self.assertEqual(Decimal("150.00"), payload["summary"]["locked_capital"])

    def test_price_simulation_applies_elasticity_and_fees(self) -> None:
        product = self.product("Lex Loafer", price="100.00", cost="40.00")
        self.db.add(PricingAnalyticsSnapshot(**_snapshot_kwargs(product)))
        self.db.add(DemandElasticityEstimate(seller_id=product.seller_id, product_id=product.id, estimation_method="HISTORICAL_ELASTICITY", elasticity=Decimal("-2.0"), sample_count=30, baseline_units=Decimal("10"), observation_start=date(2026, 10, 1), observation_end=date(2026, 10, 31), quality_metrics={}, confidence=Decimal("70"), data_status="SUFFICIENT", calculation_version="v1", calculated_at=datetime(2026, 11, 1, tzinfo=timezone.utc)))
        self.db.commit()

        payload, _ = SqlAlchemyCopilotToolDataAccess(self.db).simulate_price_change(seller_id=self.seller.id, product_id=product.id, candidate_price=Decimal("110.00"), candidate_discount_rate=None, forecast_horizon_days=30)

        # 1 unit/day × 30 days × 1.1^-2 ≈ 24.79 units; profit per unit = 110 - 40 - 11 (10% fee) = 59.
        self.assertEqual(Decimal("24.79"), payload["expected_units"])
        self.assertAlmostEqual(float(payload["expected_profit"]), 59 * 24.793, delta=0.5)
        self.assertEqual("constant_elasticity", payload["demand_model"])

    def test_competitor_event_metadata_column_serializes(self) -> None:
        event = CompetitorEvent(id=uuid4(), seller_id=self.seller.id, product_id=uuid4(), competitor_id=uuid4(), event_type=CompetitorEventType.OUT_OF_STOCK, severity=CompetitorEventSeverity.LOW, dedupe_key="k", detected_at=datetime(2026, 11, 1, tzinfo=timezone.utc), event_metadata={"source": "test"})
        payload = _source_row_payload(event, spec=SOURCE_TOOL_SPECS["get_competitor_events"])
        self.assertEqual({"source": "test"}, payload["metadata"])
        json.dumps(payload, default=str)


def _snapshot_kwargs(product: Product) -> dict:
    return {
        "seller_id": product.seller_id, "product_id": product.id, "current_price": Decimal("100.00"), "unit_cost": Decimal("40.00"),
        "percentage_fee_rate": Decimal("0.10"), "fixed_fee_amount": Decimal("0"), "current_unit_profit": Decimal("50.00"), "current_margin_rate": Decimal("0.50"),
        "minimum_safe_price": Decimal("60.00"), "daily_sales_rate": Decimal("1"), "calculated_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
        "demand_data_status": "SUFFICIENT", "data_status": "SUFFICIENT", "confidence_score": Decimal("80"), "evidence": {}, "calculation_version": "v1", "dedupe_key": f"snap-{product.id}",
    }


if __name__ == "__main__":
    unittest.main()
