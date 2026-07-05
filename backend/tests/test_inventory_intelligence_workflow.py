from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.models.product import Product
from app.schemas.products import ProductUpdate
from app.services.product_service import _requires_dead_stock_recalculation, _requires_inventory_recalculation
from app.tasks.inventory_intelligence_workflow_tasks import _workflow_chain


class InventoryIntelligenceWorkflowTests(unittest.TestCase):
    def test_complete_daily_workflow_order(self):
        workflow = _workflow_chain(
            batch_size=100,
            as_of_date="2026-06-29",
            seller_id=str(uuid4()),
            product_id=None,
        )
        task_names = [signature.task for signature in workflow.tasks]

        self.assertEqual(
            [
                "inventory_history.capture_daily_inventory_snapshots",
                "inventory_aging.calculate_inventory_aging",
                "sales_velocity.calculate_daily_sales_velocity",
                "dead_stock.assess_dead_stock",
                "stockout_predictions.calculate_stockout_predictions",
                "reorder_recommendations.calculate_reorder_recommendations",
                "inventory_risks.calculate_inventory_risks",
                "inventory_intelligence.generate_alerts_for_latest_risks",
                "telegram_inventory_alerts.enqueue_due",
            ],
            task_names,
        )

    def test_product_level_recalculation_chain_is_scoped_to_product(self):
        product_id = uuid4()
        seller_id = uuid4()
        workflow = _workflow_chain(
            batch_size=1,
            as_of_date="2026-06-29",
            seller_id=str(seller_id),
            product_id=str(product_id),
        )

        for signature in workflow.tasks[:5]:
            self.assertEqual(str(seller_id), signature.kwargs["seller_id"])
            self.assertEqual(str(product_id), signature.kwargs["product_id"])

    def test_stock_and_supplier_changes_trigger_recalculation(self):
        product = SimpleNamespace(stock_quantity=15, supplier_lead_time=8, specifications={})

        self.assertTrue(
            _requires_inventory_recalculation(
                updates={"stock_quantity": 15},
                old_stock_quantity=20,
                old_supplier_lead_time=8,
                old_specifications={},
                product=product,
            )
        )
        self.assertTrue(
            _requires_inventory_recalculation(
                updates={"supplier_lead_time": 8},
                old_stock_quantity=15,
                old_supplier_lead_time=5,
                old_specifications={},
                product=product,
            )
        )

    def test_irrelevant_metadata_change_does_not_trigger_recalculation(self):
        product = SimpleNamespace(stock_quantity=15, supplier_lead_time=8, specifications={"color": "blue"})

        self.assertFalse(
            _requires_inventory_recalculation(
                updates={"title": "New title", "specifications": {"color": "blue"}},
                old_stock_quantity=15,
                old_supplier_lead_time=8,
                old_specifications={"color": "red"},
                product=product,
            )
        )

    def test_incoming_quantity_spec_change_triggers_recalculation(self):
        product = SimpleNamespace(
            stock_quantity=15,
            supplier_lead_time=8,
            specifications={"confirmed_incoming_quantity": "50"},
        )

        self.assertTrue(
            _requires_inventory_recalculation(
                updates={"specifications": {"confirmed_incoming_quantity": "50"}},
                old_stock_quantity=15,
                old_supplier_lead_time=8,
                old_specifications={"confirmed_incoming_quantity": "0"},
                product=product,
            )
        )

    def test_dead_stock_cost_and_stock_changes_trigger_recalculation(self):
        product = SimpleNamespace(stock_quantity=12, cost_price=Decimal("20.00"))

        self.assertTrue(
            _requires_dead_stock_recalculation(
                updates={"stock_quantity": 12},
                old_stock_quantity=10,
                old_cost_price=Decimal("20.00"),
                product=product,
            )
        )
        self.assertTrue(
            _requires_dead_stock_recalculation(
                updates={"cost_price": Decimal("20.00")},
                old_stock_quantity=12,
                old_cost_price=Decimal("15.00"),
                product=product,
            )
        )
        self.assertFalse(
            _requires_dead_stock_recalculation(
                updates={"description": "metadata"},
                old_stock_quantity=12,
                old_cost_price=Decimal("20.00"),
                product=product,
            )
        )


if __name__ == "__main__":
    unittest.main()
