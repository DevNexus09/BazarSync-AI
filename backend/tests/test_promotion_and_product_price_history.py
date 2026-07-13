from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.competitor import Competitor
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory, ProductPriceHistorySource
from app.models.promotion import PromotionPlanStatus, PromotionResultStatus
from app.models.scrape_run import ScrapeRun
from app.models.seller import Seller
from app.schemas.products import ProductUpdate
from app.services.copilot.tool_registry import SqlAlchemyCopilotToolDataAccess
from app.services.product_price_history_service import ProductPriceHistoryService
from app.services.product_service import ProductService
from app.services.promotion_service import PromotionService
from app.services.rag_memory_document_builder import RagMemoryDocumentBuilder


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


class PromotionAndProductPriceHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.seller = Seller(email="seller@example.com", password_hash="hash")
        self.other = Seller(email="other@example.com", password_hash="hash")
        self.db.add_all([self.seller, self.other])
        self.db.commit()
        self.product = self._product(self.seller, "A", "100.00")
        self.other_product = self._product(self.other, "B", "120.00")
        self.db.add_all([self.product, self.other_product])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)

    def _product(self, seller: Seller, title: str, price: str) -> Product:
        return Product(
            seller_id=seller.id,
            title=title,
            description="Long enough product description",
            category="Cat",
            specifications={},
            searchable_text=title,
            cost_price=Decimal("60.00"),
            selling_price=Decimal(price),
            stock_quantity=10,
            supplier_lead_time=3,
            minimum_margin=Decimal("5.00"),
        )

    def test_create_promotion_plan_and_approval_does_not_execute_marketplace_action(self) -> None:
        plan = PromotionService(self.db).create_plan(
            seller_id=self.seller.id,
            product_id=self.product.id,
            promotion_type="DISCOUNT",
            title="July discount",
            proposed_discount_rate=Decimal("0.10"),
            source="COPILOT_PROPOSAL",
        )

        approved = PromotionService(self.db).approve_plan(seller_id=self.seller.id, promotion_plan_id=plan.id)

        self.assertEqual(PromotionPlanStatus.APPROVED, approved["promotion_plan"].status)
        self.assertFalse(approved["marketplace_execution_created"])

    def test_promotion_result_partial_when_missing_cost_or_spend(self) -> None:
        result = PromotionService(self.db).record_result(
            seller_id=self.seller.id,
            product_id=self.product.id,
            started_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            gross_revenue=Decimal("500.00"),
        )

        self.assertEqual(PromotionResultStatus.PARTIAL, result.result_status)
        self.assertTrue(result.missing_data_json["MISSING_COST_OR_FEE_DATA"])
        self.assertTrue(result.missing_data_json["MISSING_SPEND_OR_DISCOUNT_COST"])

    def test_promotion_tools_are_seller_isolated(self) -> None:
        PromotionService(self.db).create_plan(seller_id=self.seller.id, product_id=self.product.id, promotion_type="DISCOUNT", title="Mine")
        PromotionService(self.db).create_plan(seller_id=self.other.id, product_id=self.other_product.id, promotion_type="DISCOUNT", title="Other")

        payload, _ = SqlAlchemyCopilotToolDataAccess(self.db).get_promotion_plans(
            seller_id=self.seller.id,
            product_id=None,
            status=None,
            marketplace=None,
            from_date=None,
            to_date=None,
            limit=10,
            offset=0,
        )

        self.assertEqual(["Mine"], [row["title"] for row in payload["rows"]])

    def test_promotion_rag_builder_uses_persisted_plan(self) -> None:
        plan = PromotionService(self.db).create_plan(seller_id=self.seller.id, product_id=self.product.id, promotion_type="DISCOUNT", title="RAG plan")

        document = RagMemoryDocumentBuilder().build_from_promotion_plan(plan)

        self.assertEqual(str(plan.id), document.source_id)
        self.assertIn("promotion_plans", document.content_text)

    def test_product_price_update_creates_seller_price_history(self) -> None:
        ProductService(self.db).update_product(self.seller.id, self.product.id, ProductUpdate(selling_price=Decimal("110.00")))

        row = self.db.query(ProductPriceHistory).filter_by(seller_id=self.seller.id, product_id=self.product.id).one()
        self.assertEqual(Decimal("100.00"), row.old_price)
        self.assertEqual(Decimal("110.00"), row.new_price)
        self.assertEqual(ProductPriceHistorySource.PRODUCT_EDIT, row.source)

    def test_baseline_current_price_is_labelled_baseline(self) -> None:
        row = ProductPriceHistoryService(self.db).create_baseline_current_price(seller_id=self.seller.id, product_id=self.product.id)
        self.db.commit()

        self.assertEqual(ProductPriceHistorySource.BASELINE_CURRENT_PRICE, row.source)
        payload, _ = SqlAlchemyCopilotToolDataAccess(self.db).get_price_history(
            seller_id=self.seller.id,
            product_id=self.product.id,
            marketplace=None,
            from_date=None,
            to_date=None,
            limit=5,
            offset=0,
        )
        self.assertTrue(payload["rows"][0]["baseline_not_historical_change"])

    def test_price_history_tools_are_seller_isolated(self) -> None:
        ProductPriceHistoryService(self.db).record_price_change(seller_id=self.seller.id, product_id=self.product.id, old_price=Decimal("100.00"), new_price=Decimal("110.00"))
        ProductPriceHistoryService(self.db).record_price_change(seller_id=self.other.id, product_id=self.other_product.id, old_price=Decimal("120.00"), new_price=Decimal("130.00"))
        self.db.commit()

        payload, _ = SqlAlchemyCopilotToolDataAccess(self.db).get_price_history(
            seller_id=self.seller.id,
            product_id=None,
            marketplace=None,
            from_date=None,
            to_date=None,
            limit=10,
            offset=0,
        )

        self.assertEqual(1, len(payload["rows"]))
        self.assertEqual(str(self.product.id), payload["rows"][0]["product"]["id"])

    def test_competitor_price_history_is_not_returned_as_seller_price_history(self) -> None:
        scrape = ScrapeRun(seller_id=self.seller.id, product_id=self.product.id, marketplace="Daraz", run_key="run-1", status="COMPLETED")
        self.db.add(scrape)
        self.db.commit()
        competitor = Competitor(scrape_run_id=scrape.id, product_id=self.product.id, competitor_title="Comp", competitor_price=Decimal("90.00"), marketplace="Daraz")
        self.db.add(competitor)
        self.db.commit()
        self.db.add(PriceHistory(competitor_id=competitor.id, observed_price=Decimal("90.00"), observed_at=datetime(2026, 7, 1, tzinfo=timezone.utc)))
        self.db.commit()

        payload, missing = SqlAlchemyCopilotToolDataAccess(self.db).get_price_history(
            seller_id=self.seller.id,
            product_id=None,
            marketplace=None,
            from_date=None,
            to_date=None,
            limit=10,
            offset=0,
        )

        self.assertEqual("product_price_history", payload["source_table"])
        self.assertEqual([], payload["rows"])
        self.assertTrue(missing)
