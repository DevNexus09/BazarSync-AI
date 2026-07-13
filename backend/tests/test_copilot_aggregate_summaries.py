from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.alert import Alert, AlertActionType, AlertConfidence, AlertDeliveryStatus, AlertUrgencyLevel
from app.models.competitor import Competitor
from app.models.competitor_event import CompetitorEvent, CompetitorEventSeverity, CompetitorEventType
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.dead_stock_assessment import (
    DeadStockClassification,
    DeadStockDataStatus,
    DeadStockInventoryAgeState,
    DeadStockNoSalesState,
    DeadStockRiskLevel,
    DeadStockVisibilityStatus,
    DeadStockAssessment,
)
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.product import Product, ProductMarketplaceListing, ProductMarketplaceListingStatus
from app.models.product_visibility_metric import ProductVisibilityMetric
from app.models.rag_memory import RagMemoryDocument, RagMemoryEmbeddingStatus, RagMemorySensitivityLevel, RagMemorySourceType, RagMemoryVisibilityScope
from app.models.recommendation import Recommendation, RecommendationAction, RecommendationConfidence
from app.models.sales_record import SalesRecord, SalesRecordPriceSource, SalesRecordStatus
from app.models.scrape_run import ScrapeRun
from app.models.seller import Seller
from app.services.copilot.tool_registry import SqlAlchemyCopilotToolDataAccess


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


class CopilotAggregateSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.seller = Seller(email="seller@example.com", password_hash="hash")
        self.other = Seller(email="other@example.com", password_hash="hash")
        self.db.add_all([self.seller, self.other])
        self.db.commit()
        self.data = SqlAlchemyCopilotToolDataAccess(self.db)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_business_overview_returns_aggregates_evidence_and_freshness(self) -> None:
        product = self._product("A", stock=3)
        self.db.add(product)
        self.db.commit()
        self.db.add_all([
            self._listing(product),
            self._sale(product, Decimal("100.00")),
            self._memory(product, RagMemoryEmbeddingStatus.PENDING),
        ])
        self.db.commit()

        payload, missing = self.data.get_business_overview(seller_id=self.seller.id, from_date=date(2025, 1, 1), to_date=date(2025, 1, 31), marketplace=None, category=None)

        self.assertEqual(1, payload["overview"]["product_counts"]["total_products"])
        self.assertIn("revenue_summary", payload["overview"])
        self.assertIn("MEMORY_COVERAGE_INCOMPLETE", missing)
        self.assertTrue(payload["evidence"])
        self.assertTrue(payload["freshness"])

    def test_inventory_summary_aggregates_correctly_and_is_seller_scoped(self) -> None:
        self.db.add_all([self._product("A", stock=3), self._product("B", stock=10), self._product("Other", seller=self.other, stock=99)])
        self.db.commit()

        payload, missing = self.data.get_inventory_summary(seller_id=self.seller.id, product_id=None, from_date=None, to_date=None, marketplace=None, category=None, limit=5, offset=0)

        self.assertEqual(2, payload["summary"]["total_products_with_stock"])
        self.assertEqual(13, payload["summary"]["total_available_units"])
        self.assertEqual(1, payload["summary"]["low_stock_count"])
        self.assertEqual(Decimal("520.00"), payload["summary"]["inventory_value"])
        self.assertFalse(missing)
        self.assertTrue(payload["freshness"])

    def test_competitor_summary_aggregates_correctly(self) -> None:
        product = self._product("A")
        self.db.add(product)
        self.db.commit()
        run = self._scrape_run(product)
        self.db.add(run)
        self.db.commit()
        competitor = self._competitor(product, run)
        self.db.add(competitor)
        self.db.commit()
        self.db.add_all([
            CompetitorSnapshot(scrape_run_id=run.id, competitor_id=competitor.id, product_id=product.id, price=Decimal("90.00"), stock_status="IN_STOCK", captured_at=datetime(2025, 1, 2, tzinfo=timezone.utc)),
            CompetitorEvent(seller_id=self.seller.id, product_id=product.id, competitor_id=competitor.id, scrape_run_id=run.id, event_type=CompetitorEventType.PRICE_DROP, severity=CompetitorEventSeverity.HIGH, dedupe_key="drop", detected_at=datetime(2025, 1, 2, tzinfo=timezone.utc)),
        ])
        self.db.commit()

        payload, _ = self.data.get_competitor_summary(seller_id=self.seller.id, product_id=None, from_date=date(2025, 1, 1), to_date=date(2025, 1, 31), marketplace=None, category=None, limit=5, offset=0)

        self.assertEqual(1, payload["summary"]["tracked_competitor_count"])
        self.assertEqual(1, payload["summary"]["products_with_competitor_data"])
        self.assertEqual(1, payload["summary"]["recent_competitor_price_drops"])
        self.assertEqual(1, payload["summary"]["undercut_products_count"])

    def test_pricing_summary_identifies_missing_setup(self) -> None:
        product = self._product("A")
        self.db.add(product)
        self.db.commit()

        payload, _ = self.data.get_pricing_summary(seller_id=self.seller.id, product_id=None, from_date=None, to_date=None, marketplace=None, category=None, limit=5, offset=0)

        self.assertEqual(1, payload["summary"]["products_missing_fee_policy"])
        self.assertEqual(1, payload["summary"]["products_missing_pricing_policy"])
        self.assertTrue(payload["evidence"])

    def test_promotion_summary_uses_persisted_tables(self) -> None:
        payload, missing = self.data.get_promotion_summary(seller_id=self.seller.id, product_id=None, from_date=None, to_date=None, marketplace=None, category=None, limit=5, offset=0)

        self.assertEqual([], missing)
        self.assertFalse(payload["summary"]["missing_promotion_persistence_warning"])
        self.assertEqual(0, payload["summary"]["active_planned_promotions"])

    def test_dead_stock_summary_does_not_calculate_locked_capital_without_estimate(self) -> None:
        product = self._product("A")
        self.db.add(product)
        self.db.commit()
        self.db.add(self._dead_stock(product))
        self.db.commit()

        payload, missing = self.data.get_dead_stock_summary(seller_id=self.seller.id, product_id=None, from_date=None, to_date=None, marketplace=None, category=None, limit=5, offset=0)

        self.assertEqual(1, payload["summary"]["dead_stock_product_count"])
        self.assertIsNone(payload["summary"]["locked_capital"])
        self.assertIn("MISSING_LOCKED_CAPITAL", missing)

    def test_visibility_summary_does_not_claim_low_visibility_without_data(self) -> None:
        self.db.add(self._product("A"))
        self.db.commit()

        payload, missing = self.data.get_visibility_summary(seller_id=self.seller.id, product_id=None, from_date=None, to_date=None, marketplace=None, category=None, limit=5, offset=0)

        self.assertIsNone(payload["summary"]["low_visibility_count"])
        self.assertIn("VISIBILITY_DATA_UNAVAILABLE", missing)

    def test_visibility_summary_counts_low_visibility_when_evidence_exists(self) -> None:
        product = self._product("A")
        self.db.add(product)
        self.db.commit()
        self.db.add(ProductVisibilityMetric(seller_id=self.seller.id, product_id=product.id, marketplace="Daraz", metric_date=date(2025, 1, 1), impressions=0, views=0, clicks=0, listing_quality_score=Decimal("40.00")))
        self.db.commit()

        payload, missing = self.data.get_visibility_summary(seller_id=self.seller.id, product_id=None, from_date=None, to_date=None, marketplace=None, category=None, limit=5, offset=0)

        self.assertEqual(1, payload["summary"]["low_visibility_count"])
        self.assertFalse(missing)

    def _product(self, title: str, *, seller: Seller | None = None, stock: int = 10) -> Product:
        return Product(seller_id=(seller or self.seller).id, title=title, sku=f"sku-{title}", category="cat", cost_price=Decimal("40.00"), selling_price=Decimal("100.00"), stock_quantity=stock, supplier_lead_time=7, minimum_margin=Decimal("10.00"))

    def _listing(self, product: Product) -> ProductMarketplaceListing:
        return ProductMarketplaceListing(seller_id=product.seller_id, product_id=product.id, marketplace="Daraz", marketplace_listing_id=f"listing-{product.id}", listing_status=ProductMarketplaceListingStatus.ACTIVE)

    def _sale(self, product: Product, unit_price: Decimal) -> SalesRecord:
        return SalesRecord(seller_id=product.seller_id, product_id=product.id, status=SalesRecordStatus.COMPLETED, sold_at=datetime(2025, 1, 2, tzinfo=timezone.utc), quantity_sold=1, unit_price=unit_price, line_total=unit_price, currency="BDT", price_source=SalesRecordPriceSource.IMPORTED_TRANSACTION)

    def _scrape_run(self, product: Product) -> ScrapeRun:
        return ScrapeRun(seller_id=self.seller.id, product_id=product.id, marketplace="Daraz", run_key=f"run-{product.id}", status="COMPLETED", created_at=datetime(2025, 1, 2, tzinfo=timezone.utc))

    def _competitor(self, product: Product, run: ScrapeRun) -> Competitor:
        return Competitor(scrape_run_id=run.id, product_id=product.id, competitor_title="Competitor A", competitor_price=Decimal("90.00"), marketplace="Daraz")

    def _dead_stock(self, product: Product) -> DeadStockAssessment:
        return DeadStockAssessment(
            seller_id=product.seller_id,
            product_id=product.id,
            as_of_date=date(2025, 1, 2),
            classification=DeadStockClassification.DEAD_STOCK,
            eligible_quantity=5,
            no_sales_state=DeadStockNoSalesState.NEVER_SOLD,
            inventory_age_state=DeadStockInventoryAgeState.AGE_THRESHOLD_EXCEEDED,
            visibility_status=DeadStockVisibilityStatus.VISIBILITY_DATA_UNAVAILABLE,
            risk_score=Decimal("90.00"),
            risk_level=DeadStockRiskLevel.CRITICAL,
            rule_results={},
            triggered_rules=[],
            data_status=DeadStockDataStatus.SUFFICIENT,
            confidence_score=Decimal("80.00"),
            calculation_version="v1",
            assessed_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )

    def _memory(self, product: Product, status: RagMemoryEmbeddingStatus) -> RagMemoryDocument:
        return RagMemoryDocument(
            seller_id=product.seller_id,
            product_id=product.id,
            source_type=RagMemorySourceType.PRODUCT_PROFILE,
            source_table="products",
            source_id=str(product.id),
            source_version="v1",
            title="Product profile",
            content_text="Product profile.",
            sensitivity_level=RagMemorySensitivityLevel.INTERNAL,
            visibility_scope=RagMemoryVisibilityScope.PRODUCT,
            content_hash="hash",
            chunking_version="v1",
            embedding_status=status,
        )


if __name__ == "__main__":
    unittest.main()
