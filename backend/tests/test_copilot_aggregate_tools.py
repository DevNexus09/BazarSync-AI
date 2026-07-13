from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.action_center_item import ActionCenterItem
from app.models.product import Product
from app.models.reorder_recommendation import ReorderRecommendation, ReorderRecommendationAction, ReorderRecommendationStatus
from app.models.seller import Seller
from app.services.copilot.question_planner import DOMAIN_TOOL_PRIORITIES
from app.services.copilot.query_constraints import BusinessDomainKey
from app.services.copilot.tool_registry import SqlAlchemyCopilotToolDataAccess


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


class CopilotAggregateToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(
            self.engine,
            tables=[
                Seller.__table__,
                Product.__table__,
                ReorderRecommendation.__table__,
                ActionCenterItem.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.seller = Seller(email="seller@example.com", password_hash="hash")
        self.other_seller = Seller(email="other@example.com", password_hash="hash")
        self.db.add_all([self.seller, self.other_seller])
        self.db.commit()
        self.data = SqlAlchemyCopilotToolDataAccess(self.db)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(
            self.engine,
            tables=[
                ActionCenterItem.__table__,
                ReorderRecommendation.__table__,
                Product.__table__,
                Seller.__table__,
            ],
        )
        self.engine.dispose()

    def test_inventory_summary_is_aggregate_and_seller_scoped(self) -> None:
        self.db.add_all(
            [
                self._product("Own A", stock=8, cost=Decimal("10.00")),
                self._product("Own B", stock=0, cost=Decimal("12.00")),
                self._product("Own C", stock=3, cost=Decimal("5.00")),
                self._product("Other", seller=self.other_seller, stock=50, cost=Decimal("99.00")),
            ]
        )
        self.db.commit()

        payload, missing = self.data.get_inventory_summary(
            seller_id=self.seller.id,
            product_id=None,
            from_date=None,
            to_date=None,
            marketplace=None,
            category=None,
            limit=5,
            offset=0,
        )

        self.assertEqual(2, payload["summary"]["total_products_with_stock"])
        self.assertEqual(11, payload["summary"]["total_available_units"])
        self.assertEqual(2, payload["summary"]["low_stock_count"])
        self.assertEqual(Decimal("95.00"), payload["summary"]["inventory_value"])
        self.assertNotIn("MISSING_PRODUCT_COST", missing)
        self.assertEqual("products", payload["evidence"][0]["source_table"])
        self.assertLessEqual(len(payload["top_affected_products"]), 5)

    def test_inventory_summary_uses_bounded_query_count(self) -> None:
        self.db.add_all([self._product(f"Bulk {index}", stock=index % 9, cost=Decimal("10.00")) for index in range(40)])
        self.db.commit()
        query_count = 0

        def _count_query(*_args) -> None:
            nonlocal query_count
            query_count += 1

        event.listen(self.engine, "before_cursor_execute", _count_query)
        try:
            payload, missing = self.data.get_inventory_summary(
                seller_id=self.seller.id,
                product_id=None,
                from_date=None,
                to_date=None,
                marketplace=None,
                category=None,
                limit=5,
                offset=0,
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", _count_query)

        self.assertFalse(missing)
        self.assertLessEqual(len(payload["top_affected_products"]), 5)
        self.assertLessEqual(query_count, 20)

    def test_action_center_sync_is_idempotent_and_read_only_marketplace(self) -> None:
        product = self._product("Reorder Product", stock=2, cost=Decimal("20.00"))
        self.db.add(product)
        self.db.commit()
        self.db.add(
            ReorderRecommendation(
                seller_id=self.seller.id,
                product_id=product.id,
                as_of_date=date(2026, 7, 13),
                action=ReorderRecommendationAction.REORDER,
                recommended_quantity=25,
                reorder_deadline=date(2026, 7, 13),
                supplier_lead_time_days=7,
                safety_buffer_days=3,
                review_period_days=7,
                reorder_point=20,
                target_stock=50,
                inventory_position=2,
                daily_sales_rate=Decimal("3.0000"),
                confidence_score=Decimal("90.00"),
                recommendation_status=ReorderRecommendationStatus.OPEN,
                explanation="Stock will run out before supplier lead time.",
                evidence={"source": "test"},
                calculation_version="v1",
                generated_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
            )
        )
        self.db.commit()

        first, first_missing = self.data.get_today_actions(seller_id=self.seller.id, product_id=None, limit=5)
        second, second_missing = self.data.get_today_actions(seller_id=self.seller.id, product_id=None, limit=5)
        item_count = self.db.query(ActionCenterItem).filter(ActionCenterItem.seller_id == self.seller.id).count()

        self.assertFalse(first_missing)
        self.assertFalse(second_missing)
        self.assertEqual(1, item_count)
        self.assertEqual(first[0]["source_type"], "reorder_recommendations")
        self.assertEqual("REORDER", first[0]["action_type"])
        self.assertEqual("CRITICAL", first[0]["priority"])

    def test_planner_prioritizes_aggregate_tools_before_row_drilldown(self) -> None:
        inventory_tools = DOMAIN_TOOL_PRIORITIES[BusinessDomainKey.INVENTORY]
        competitor_tools = DOMAIN_TOOL_PRIORITIES[BusinessDomainKey.COMPETITOR]
        pricing_tools = DOMAIN_TOOL_PRIORITIES[BusinessDomainKey.PRICING]

        self.assertLess(inventory_tools.index("get_inventory_summary"), inventory_tools.index("get_inventory_risks"))
        self.assertLess(competitor_tools.index("get_competitor_summary"), competitor_tools.index("get_competitor_snapshots"))
        self.assertLess(pricing_tools.index("get_pricing_summary"), pricing_tools.index("get_price_history"))

    def _product(self, title: str, *, seller: Seller | None = None, stock: int, cost: Decimal | None) -> Product:
        return Product(
            seller_id=(seller or self.seller).id,
            title=title,
            sku=f"sku-{title}",
            category="cat",
            cost_price=cost,
            selling_price=Decimal("100.00"),
            stock_quantity=stock,
            supplier_lead_time=7,
            minimum_margin=Decimal("10.00"),
        )


if __name__ == "__main__":
    unittest.main()
