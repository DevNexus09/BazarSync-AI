from __future__ import annotations

import unittest
from uuid import UUID, uuid4

from app.services.copilot.tool_registry import CopilotToolContext, CopilotToolRegistry, ToolExecutionStatus


SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")
PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000099")


def _evidence(table: str, source_id=None) -> dict:
    return {"source_table": table, "source_id": str(source_id or uuid4()), "payload": {}}


class _ProductToolDataAccess:
    def verify_product_owned(self, *, seller_id, product_id):
        return seller_id == SELLER_ID and product_id == PRODUCT_ID

    def get_business_overview(self, *, seller_id, **kwargs):
        assert seller_id == SELLER_ID
        return {
            "overview": {
                "total_products": 2,
                "products_with_stock": 1,
                "products_missing_cost": 1,
                "products_missing_fee_policy": 1,
                "products_missing_pricing_policy": 1,
                "products_with_inventory_risk": 1,
                "products_with_dead_stock_risk": 1,
                "active_alerts": 1,
                "pending_recommendations": 2,
            },
            "evidence": [_evidence("products")],
        }, ["Sales completeness is not tracked."]

    def count_products(self, *, seller_id, filters):
        assert seller_id == SELLER_ID
        return {"count": 2, "filters_used": filters, "evidence": [_evidence("products")]}, []

    def list_products(self, *, seller_id, filters, sort_by, limit, offset):
        assert seller_id == SELLER_ID
        product = {
            "id": str(PRODUCT_ID),
            "title": "Alpha",
            "stock_quantity": 4,
            "cost_price": None if filters.get("missing_cost") else "50.00",
            "has_fee_policy": not filters.get("missing_fee_policy", False),
            "missing_setup_fields": ["COST"] if filters.get("missing_cost") else [],
            "evidence": _evidence("products", PRODUCT_ID),
        }
        return {
            "products": [product],
            "pagination": {"total": 3, "limit": limit, "offset": offset, "has_next": offset + limit < 3},
            "filters_used": filters,
            "evidence": [_evidence("products")],
        }, []

    def search_products(self, *, seller_id, query, category, marketplace, limit):
        assert seller_id == SELLER_ID
        return {
            "products": [
                {"id": str(PRODUCT_ID), "title": "USB Charger 20W"},
                {"id": str(uuid4()), "title": "USB Charger 30W"},
            ],
            "confidence": "MEDIUM",
            "ambiguity_warning": "Multiple seller-owned products match this query.",
            "evidence": [_evidence("products")],
        }, []

    def get_product_profile(self, *, seller_id, product_id):
        assert seller_id == SELLER_ID
        return {
            "product": {
                "id": str(product_id),
                "name": "Alpha",
                "category": "Gadgets",
                "selling_price": "100.00",
                "cost_or_landed_cost": "50.00",
                "current_stock": 4,
                "sales_velocity": {"daily_sales_rate": "1.5"},
                "competitor_count": 2,
                "latest_inventory_risk": {"risk_level": "HIGH"},
                "missing_setup_data": ["MARKETPLACE_FEE_POLICY"],
            },
            "evidence": [_evidence("products", product_id), _evidence("inventory_risk_assessments")],
        }, ["Estimated margin is unavailable until fee policy is present."]

    def get_products_missing_setup(self, *, seller_id, setup_type, category, marketplace, limit, offset):
        assert seller_id == SELLER_ID
        return {
            "products": [
                {
                    "product": {"id": str(PRODUCT_ID), "title": "Alpha"},
                    "missing_setup_fields": [setup_type or "MARKETPLACE_FEE_POLICY"],
                    "next_actions": ["Configure marketplace fee policy."],
                    "evidence": _evidence("products", PRODUCT_ID),
                }
            ],
            "pagination": {"total": 1, "limit": limit, "offset": offset, "has_next": False},
            "evidence": [_evidence("products")],
        }, []

    def __getattr__(self, name):
        if name.startswith("get_") or name.startswith("retrieve_") or name.startswith("simulate_") or name.startswith("explain_"):
            def _unused(**kwargs):
                return {"evidence": [_evidence(name)]}, []

            return _unused
        raise AttributeError(name)


class _FailingProductToolDataAccess(_ProductToolDataAccess):
    def list_products(self, *, seller_id, filters, sort_by, limit, offset):
        raise RuntimeError("database enum failure")


class _RollbackSession:
    def __init__(self) -> None:
        self.rollbacks = 0

    def rollback(self) -> None:
        self.rollbacks += 1


class CopilotProductToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = CopilotToolRegistry(_ProductToolDataAccess())
        self.context = CopilotToolContext(seller_id=SELLER_ID)

    def test_count_products_for_seller(self):
        result = self.registry.execute(name="count_products", context=self.context, arguments={})

        self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
        self.assertEqual(2, result.data["count"])

    def test_count_excludes_other_sellers_by_context(self):
        other_context = CopilotToolContext(seller_id=UUID("00000000-0000-0000-0000-000000000002"))
        result = self.registry.execute(name="count_products", context=other_context, arguments={})

        self.assertEqual(ToolExecutionStatus.FAILED, result.status)

    def test_list_products_with_missing_cost(self):
        result = self.registry.execute(name="list_products", context=self.context, arguments={"missing_cost": True, "limit": 5, "offset": 0})

        self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
        self.assertIn("COST", result.data["products"][0]["missing_setup_fields"])

    def test_list_products_with_stock(self):
        result = self.registry.execute(name="list_products", context=self.context, arguments={"has_stock": True, "limit": 5, "offset": 0})

        self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
        self.assertGreater(result.data["products"][0]["stock_quantity"], 0)

    def test_listed_status_maps_to_listing_filter(self):
        result = self.registry.execute(name="list_products", context=self.context, arguments={"status": "listed", "limit": 5, "offset": 0})

        self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
        self.assertIsNone(result.data["filters_used"]["status"])
        self.assertTrue(result.data["filters_used"]["listed"])

    def test_tool_failure_rolls_back_database_session(self):
        session = _RollbackSession()
        result = CopilotToolRegistry(_FailingProductToolDataAccess()).execute(
            name="list_products",
            context=CopilotToolContext(seller_id=SELLER_ID, db=session),
            arguments={"status": "listed", "limit": 5, "offset": 0},
        )

        self.assertEqual(ToolExecutionStatus.FAILED, result.status)
        self.assertEqual(1, session.rollbacks)

    def test_list_products_missing_fee_policy(self):
        result = self.registry.execute(name="list_products", context=self.context, arguments={"missing_fee_policy": True, "limit": 5, "offset": 0})

        self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
        self.assertFalse(result.data["products"][0]["has_fee_policy"])

    def test_product_profile_includes_available_data(self):
        result = self.registry.execute(name="get_product_profile", context=self.context, arguments={"product_id": str(PRODUCT_ID)})

        self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
        self.assertEqual("Alpha", result.data["product"]["name"])
        self.assertEqual(2, result.data["product"]["competitor_count"])

    def test_product_profile_marks_missing_data(self):
        result = self.registry.execute(name="get_product_profile", context=self.context, arguments={"product_id": str(PRODUCT_ID)})

        self.assertIn("MARKETPLACE_FEE_POLICY", result.data["product"]["missing_setup_data"])
        self.assertTrue(result.missing_data)

    def test_search_handles_ambiguous_names(self):
        result = self.registry.execute(name="search_products", context=self.context, arguments={"query": "USB Charger", "limit": 5})

        self.assertEqual("MEDIUM", result.data["confidence"])
        self.assertIsNotNone(result.data["ambiguity_warning"])

    def test_cross_seller_product_blocked(self):
        result = self.registry.execute(name="get_product_profile", context=self.context, arguments={"product_id": str(OTHER_PRODUCT_ID)})

        self.assertEqual(ToolExecutionStatus.BLOCKED, result.status)
        self.assertEqual("PRODUCT_ACCESS_DENIED", result.error["code"])

    def test_list_pagination_works(self):
        result = self.registry.execute(name="list_products", context=self.context, arguments={"limit": 1, "offset": 1})

        self.assertEqual({"total": 3, "limit": 1, "offset": 1, "has_next": True}, result.data["pagination"])


if __name__ == "__main__":
    unittest.main()
