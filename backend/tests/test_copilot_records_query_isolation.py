"""Every query_business_records entity excludes other sellers' rows, including the join-scoped ones."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.alert import Alert, AlertActionType, AlertConfidence
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.inventory_stock_in import InventoryStockIn
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory, ProductPriceHistorySource
from app.models.promotion import PromotionPlan
from app.models.recommendation import Recommendation, RecommendationConfidence
from app.models.sales_record import SalesRecord, SalesRecordPriceSource, SalesRecordStatus
from app.models.seller import Seller
from app.services.copilot.records_query import ENTITY_SPECS
from app.services.copilot.tool_registry import CopilotToolContext, CopilotToolRegistry, ToolExecutionStatus


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


NOW = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)
MODELS = [Seller, Product, SalesRecord, InventoryStockIn, InventoryHistory, ProductPriceHistory, PromotionPlan, Recommendation, Alert, CompetitorSnapshot]


def _rows_for(product: Product) -> dict[str, object]:
    seller_id = product.seller_id
    return {
        "sales": SalesRecord(seller_id=seller_id, product_id=product.id, status=SalesRecordStatus.COMPLETED, sold_at=NOW, quantity_sold=1, unit_price=Decimal("10"), line_total=Decimal("10"), currency="BDT", price_source=SalesRecordPriceSource.TRANSACTION, returned_units=0, refunded_restocked_units=0, is_test_order=False),
        "stock_ins": InventoryStockIn(seller_id=seller_id, product_id=product.id, quantity=5, received_at=NOW, unit_cost=Decimal("4"), currency="BDT"),
        "inventory_history": InventoryHistory(seller_id=seller_id, product_id=product.id, snapshot_date=date(2026, 11, 10), captured_at=NOW, quantity_on_hand=3, quantity_available=3, source=InventorySnapshotSource.DAILY_SNAPSHOT, content_hash=uuid4().hex),
        "price_history": ProductPriceHistory(seller_id=seller_id, product_id=product.id, new_price=Decimal("12"), currency="BDT", source=ProductPriceHistorySource.IMPORT, changed_at=NOW),
        "promotions": PromotionPlan(seller_id=seller_id, product_id=product.id, promotion_type="DISCOUNT", title="Plan", planned_start_at=NOW),
        "alerts": Alert(seller_id=seller_id, product_id=product.id, alert_type="LOW_STOCK", action_type=list(AlertActionType)[0], confidence=list(AlertConfidence)[0], created_at=NOW),
        "recommendations": Recommendation(product_id=product.id, confidence=list(RecommendationConfidence)[0], reasoning_bn="x", recommendation_context={"source": "test"}, created_at=NOW),
        "competitor_snapshots": CompetitorSnapshot(scrape_run_id=uuid4(), competitor_id=uuid4(), product_id=product.id, stock_status="IN_STOCK", price=Decimal("9"), currency="BDT", captured_at=NOW),
    }


class RecordsQuerySellerIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine, tables=[model.__table__ for model in MODELS])
        self.db = Session(self.engine)
        self.seller = Seller(email="own@example.com", password_hash="hash")
        other = Seller(email="other@example.com", password_hash="hash")
        self.db.add_all([self.seller, other])
        self.db.flush()
        own, foreign = (
            Product(seller_id=owner.id, title=title, sku=title, category="Shoes", cost_price=Decimal("5"), selling_price=Decimal("10"), stock_quantity=3, supplier_lead_time=7, minimum_margin=Decimal("1"))
            for owner, title in ((self.seller, "own-product"), (other, "foreign-product"))
        )
        self.db.add_all([own, foreign])
        self.db.flush()
        self.foreign_rows = _rows_for(foreign)
        self.db.add_all([*_rows_for(own).values(), *self.foreign_rows.values()])
        self.db.commit()
        self.foreign_product_id = str(foreign.id)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine, tables=[model.__table__ for model in reversed(MODELS)])
        self.engine.dispose()

    def test_every_entity_returns_only_the_authenticated_sellers_rows(self):
        registry = CopilotToolRegistry()
        context = CopilotToolContext(seller_id=self.seller.id, db=self.db)
        self.assertEqual(set(ENTITY_SPECS), {*self.foreign_rows, "products"})
        for entity in ENTITY_SPECS:
            with self.subTest(entity=entity):
                counted = registry.execute(name="query_business_records", context=context, arguments={"entity": entity, "aggregate": "count"})
                listed = registry.execute(name="query_business_records", context=context, arguments={"entity": entity, "limit": 200})

                self.assertEqual(ToolExecutionStatus.SUCCEEDED, counted.status, counted.error)
                self.assertEqual(1, counted.data["rows"][0]["value"])
                ids = {row["id"] for row in listed.data["rows"]}
                foreign = self.foreign_rows.get(entity)
                self.assertNotIn(str(foreign.id) if foreign is not None else self.foreign_product_id, ids)
                self.assertNotIn("foreign-product", str(listed.data))


if __name__ == "__main__":
    unittest.main()
