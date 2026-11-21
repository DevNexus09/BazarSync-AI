from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import unittest
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.product import Product, ProductMarketplaceListing
from app.models.seller import Seller
from app.services.copilot.category_resolver import CategoryResolver
from app.services.copilot.competitor_resolver import CompetitorCandidate, CompetitorResolver
from app.services.copilot.entity_resolver import CopilotEntityResolver, EntityConfidence, ProductEntityCandidate
from app.services.copilot.intent_classifier import CopilotIntentClassifier
from app.services.copilot.marketplace_resolver import MarketplaceResolver
from app.services.copilot.product_resolver import ProductResolver, SqlAlchemyProductEntitySource
from app.services.copilot.question_planner import CopilotPlanningContext, CopilotQuestionPlanner
from app.services.copilot.tool_registry import CopilotToolRegistry


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")
PRODUCT_A_ID = UUID("00000000-0000-0000-0000-000000000010")
PRODUCT_B_ID = UUID("00000000-0000-0000-0000-000000000011")


class _ProductSource:
    def __init__(self, products: list[ProductEntityCandidate]) -> None:
        self.products = products

    def list_products(self, *, seller_id, limit: int = 1000):
        return self.products[:limit]


class EntityResolverUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.products = [
            ProductEntityCandidate(
                id=PRODUCT_A_ID,
                title="Rice 5kg Pack",
                category="Grocery",
                searchable_text="premium rice চাল",
                sku="SKU-R5",
                marketplace_listing_ids=("DRZ-1001",),
                listing_titles=("Premium Rice Five Kilogram",),
                aliases=("Family Rice Pack",),
            ),
            ProductEntityCandidate(id=PRODUCT_B_ID, title="Rice 10kg Pack", category="Grocery", sku="RICE-10KG"),
        ]
        self.product_resolver = ProductResolver(source=_ProductSource(self.products))

    def test_exact_product_name(self) -> None:
        result = self.product_resolver.resolve(seller_id=SELLER_ID, query_text="Show Rice 5kg Pack revenue")

        self.assertEqual(str(PRODUCT_A_ID), result.selected_id)
        self.assertEqual("EXACT_NAME", result.matches[0].match_type)
        self.assertEqual(EntityConfidence.HIGH, result.confidence)
        self.assertEqual(
            {"entity_type", "query_text", "matches", "selected_id", "confidence", "ambiguous", "clarification_question"},
            set(result.to_dict()),
        )

    def test_exact_sku(self) -> None:
        result = self.product_resolver.resolve(seller_id=SELLER_ID, query_text="Stock for SKU-R5")

        self.assertEqual(str(PRODUCT_A_ID), result.selected_id)
        self.assertEqual("EXACT_SKU", result.matches[0].match_type)

    def test_listing_id(self) -> None:
        result = self.product_resolver.resolve(seller_id=SELLER_ID, query_text="How is DRZ-1001 doing?")

        self.assertEqual(str(PRODUCT_A_ID), result.selected_id)
        self.assertEqual("LISTING_ID", result.matches[0].match_type)

    def test_ambiguous_products_are_not_selected(self) -> None:
        result = self.product_resolver.resolve(seller_id=SELLER_ID, query_text="How is rice selling?")

        self.assertTrue(result.ambiguous)
        self.assertIsNone(result.selected_id)
        self.assertEqual(2, len(result.matches))

    def test_exact_and_bangla_category_alias(self) -> None:
        resolver = CategoryResolver(categories=["Grocery", "Electronics"])

        exact = resolver.resolve(seller_id=SELLER_ID, query_text="Show Grocery products")
        bangla = resolver.resolve(seller_id=SELLER_ID, query_text="মুদি ক্যাটাগরির পণ্য দেখাও")

        self.assertEqual("Grocery", exact.selected_id)
        self.assertEqual("Grocery", bangla.selected_id)

    def test_registered_marketplace_and_missing_marketplace_data(self) -> None:
        registered = CopilotEntityResolver(
            product_resolver=self.product_resolver,
            category_resolver=CategoryResolver(categories=[]),
            marketplace_resolver=MarketplaceResolver(marketplaces=["Daraz Bangladesh"]),
            competitor_resolver=CompetitorResolver(competitors=[]),
        ).resolve(seller_id=SELLER_ID, question="Which products are listed on দারাজ?")
        missing = CopilotEntityResolver(
            product_resolver=self.product_resolver,
            category_resolver=CategoryResolver(categories=[]),
            marketplace_resolver=MarketplaceResolver(marketplaces=[]),
            competitor_resolver=CompetitorResolver(competitors=[]),
        ).resolve(seller_id=SELLER_ID, question="Which products are listed on Daraz?")

        self.assertEqual(["Daraz Bangladesh"], registered.marketplaces)
        self.assertIn("MISSING_MARKETPLACE_DATA", missing.missing_data)
        self.assertIsNone(missing.marketplace_resolution.selected_id)

    def test_exact_and_ambiguous_competitor(self) -> None:
        competitors = [
            CompetitorCandidate(uuid4(), "Fresh Rice 5kg", "Fresh Mart", PRODUCT_A_ID, "Rice 5kg Pack", "https://fresh.example/item", "Daraz"),
            CompetitorCandidate(uuid4(), "Daily Rice 5kg", "Daily Mart", PRODUCT_A_ID, "Rice 5kg Pack", "https://daily.example/item", "Daraz"),
        ]
        resolver = CompetitorResolver(competitors=competitors)

        exact = resolver.resolve(seller_id=SELLER_ID, query_text="What did Fresh Mart change?")
        ambiguous = resolver.resolve(seller_id=SELLER_ID, query_text="Competitors for Rice 5kg Pack")

        self.assertEqual(str(competitors[0].id), exact.selected_id)
        self.assertTrue(ambiguous.ambiguous)
        self.assertIsNone(ambiguous.selected_id)

    def test_own_product_question_is_not_a_competitor_clarification(self) -> None:
        # Baseline eval: "selling price of <own product>" asked "Which competitor do you mean?" because every
        # competitor tracked for that product matched, and a store named like the brand matched inside the SKU.
        competitors = [
            CompetitorCandidate(uuid4(), "Fresh Rice 5kg", "Fresh Mart", PRODUCT_A_ID, "Rice 5kg Pack", None, "Daraz"),
            CompetitorCandidate(uuid4(), "Daily Rice 5kg", "Daily Mart", PRODUCT_A_ID, "Rice 5kg Pack", None, "Daraz"),
        ]
        resolver = CopilotEntityResolver(
            product_resolver=self.product_resolver,
            category_resolver=CategoryResolver(categories=[]),
            marketplace_resolver=MarketplaceResolver(marketplaces=[]),
            competitor_resolver=CompetitorResolver(competitors=competitors),
        )

        own = resolver.resolve(seller_id=SELLER_ID, question="What is the selling price of Rice 5kg Pack?")
        asked = resolver.resolve(seller_id=SELLER_ID, question="Which competitors undercut Rice 5kg Pack?")

        self.assertIsNone(own.clarification_question)
        self.assertEqual(str(PRODUCT_A_ID), own.product_resolution.selected_id)
        self.assertFalse(own.competitor_resolution.ambiguous)
        self.assertIsNotNone(asked.clarification_question)

    def test_follow_up_inherits_entity_and_explicit_entity_overrides_it(self) -> None:
        resolver = CopilotEntityResolver(
            product_resolver=self.product_resolver,
            category_resolver=CategoryResolver(categories=[]),
            marketplace_resolver=MarketplaceResolver(marketplaces=[]),
            competitor_resolver=CompetitorResolver(competitors=[]),
        )
        planner = CopilotQuestionPlanner(entity_resolver=resolver, now=datetime(2026, 7, 13, 10, 0))
        context = CopilotPlanningContext(active_products=[{"product_id": str(PRODUCT_A_ID), "title": "Rice 5kg Pack"}], active_domains=["SALES_REVENUE"])

        inherited = self._plan(planner, "What about last week?", context)
        overridden = self._plan(planner, "What about Rice 10kg Pack?", context)

        self.assertEqual(str(PRODUCT_A_ID), inherited.entities.products[0]["product_id"])
        self.assertEqual(str(PRODUCT_B_ID), overridden.entities.products[0]["product_id"])

    def test_follow_up_persists_competitor_id(self) -> None:
        competitor = CompetitorCandidate(uuid4(), "Fresh Rice", "Fresh Mart", PRODUCT_A_ID, "Rice 5kg Pack", None, "Daraz")
        resolver = CopilotEntityResolver(
            product_resolver=self.product_resolver,
            category_resolver=CategoryResolver(categories=[]),
            marketplace_resolver=MarketplaceResolver(marketplaces=[]),
            competitor_resolver=CompetitorResolver(competitors=[competitor]),
        )
        planner = CopilotQuestionPlanner(entity_resolver=resolver, now=datetime(2026, 7, 13, 10, 0))
        context = CopilotPlanningContext(
            active_competitors=["Fresh Mart"],
            active_competitor_ids=[str(competitor.id)],
            active_domains=["COMPETITOR"],
        )

        inherited = self._plan(planner, "What about last week?", context)

        self.assertEqual([str(competitor.id)], inherited.entities.competitor_ids)
        self.assertEqual([str(competitor.id)], inherited.execution_plan["resolved_entities"]["competitor_ids"])

    def test_missing_marketplace_data_blocks_unfiltered_execution(self) -> None:
        resolver = CopilotEntityResolver(
            product_resolver=self.product_resolver,
            category_resolver=CategoryResolver(categories=[]),
            marketplace_resolver=MarketplaceResolver(marketplaces=[]),
            competitor_resolver=CompetitorResolver(competitors=[]),
        )
        planner = CopilotQuestionPlanner(entity_resolver=resolver, now=datetime(2026, 7, 13, 10, 0))

        plan = self._plan(planner, "Which products are listed on Daraz?", CopilotPlanningContext())

        self.assertTrue(plan.needs_clarification)
        self.assertIn("MISSING_MARKETPLACE_DATA", plan.safety_flags)
        self.assertEqual([], plan.entities.marketplaces)

    def _plan(self, planner: CopilotQuestionPlanner, question: str, context: CopilotPlanningContext):
        classifier = CopilotIntentClassifier(now=datetime(2026, 7, 13, 10, 0), seller_timezone="Asia/Dhaka")
        classification = classifier.classify(seller_id=SELLER_ID, question=question)
        return planner.plan(
            seller_id=SELLER_ID,
            question=question,
            language=classification.language,
            conversation_history=[],
            product_id=None,
            from_date=None,
            to_date=None,
            top_k=8,
            include_memory=True,
            business_catalog=None,
            metric_catalog=None,
            tool_registry=CopilotToolRegistry(),
            classification_hint=classification,
            max_tools=6,
            planning_context=context,
        )


class EntityResolverSellerIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine, tables=[Seller.__table__, Product.__table__, ProductMarketplaceListing.__table__])
        self.db = Session(self.engine)
        self.seller = Seller(email="seller@example.com", password_hash="hash")
        self.other_seller = Seller(email="other@example.com", password_hash="hash")
        self.db.add_all([self.seller, self.other_seller])
        self.db.flush()
        self.own_product = self._product(self.seller, "Own Product", "OWN")
        self.other_product = self._product(self.other_seller, "Secret Product", "SECRET")
        self.db.add_all([self.own_product, self.other_product])
        self.db.flush()
        self.db.add(ProductMarketplaceListing(seller_id=self.seller.id, product_id=self.own_product.id, marketplace="Daraz", marketplace_listing_id="OWN-LISTING"))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_cross_seller_product_and_listing_are_blocked(self) -> None:
        resolver = ProductResolver(source=SqlAlchemyProductEntitySource(self.db))

        by_name = resolver.resolve(seller_id=self.seller.id, query_text="Secret Product")
        by_id = resolver.resolve(seller_id=self.seller.id, query_text=str(self.other_product.id), product_id=self.other_product.id)

        self.assertIsNone(by_name.selected_id)
        self.assertIsNone(by_id.selected_id)

    def test_marketplace_values_are_seller_scoped(self) -> None:
        result = MarketplaceResolver(db=self.db).resolve(seller_id=self.seller.id, query_text="Show Daraz products")

        self.assertEqual("Daraz", result.selected_id)

    @staticmethod
    def _product(seller: Seller, title: str, sku: str) -> Product:
        return Product(
            seller_id=seller.id,
            title=title,
            sku=sku,
            category="Grocery",
            searchable_text=title,
            cost_price=Decimal("50.00"),
            selling_price=Decimal("100.00"),
            stock_quantity=10,
            supplier_lead_time=7,
            minimum_margin=Decimal("10.00"),
        )


if __name__ == "__main__":
    unittest.main()
