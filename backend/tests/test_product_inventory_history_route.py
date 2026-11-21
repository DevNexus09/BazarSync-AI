from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.api.v1.products import get_product_inventory_history
from app.models.inventory_history import InventorySnapshotSource


def test_inventory_history_route_returns_page_instead_of_falling_through():
    seller = SimpleNamespace(id=uuid4())
    product_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        seller_id=seller.id,
        product_id=product_id,
        snapshot_date=date(2026, 11, 21),
        captured_at=datetime(2026, 11, 21, tzinfo=timezone.utc),
        quantity_on_hand=10,
        quantity_reserved=2,
        quantity_available=8,
        quantity_incoming=0,
        source=InventorySnapshotSource.BACKFILL,
        source_reference="demo",
        content_hash="a" * 64,
        created_at=datetime(2026, 11, 21, tzinfo=timezone.utc),
    )
    service = MagicMock()
    service.list_product_history.return_value = ([row], 1)

    with patch("app.api.v1.products.InventoryHistoryService", return_value=service):
        page = get_product_inventory_history(
            product_id=product_id,
            db=MagicMock(),
            current_seller=seller,
            limit=20,
            offset=0,
            from_date=None,
            to_date=None,
            order="desc",
        )

    assert page.total == 1
    assert page.items[0].quantity_available == 8

