from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.core.config import settings
from app.services.phase5_realtime_service import Phase5RealtimePublisher
from app.websocket.socket_events import DashboardRealtimeEnvelope, RealtimeEventType
from app.websocket.socket_manager import RealtimeSocketManager
from app.websocket.socket_rooms import RoomScope, RoomSubscriptionRequest, RoomTarget


class FakeEmitter:
    def __init__(self) -> None:
        self.calls: list[tuple[DashboardRealtimeEnvelope, list[str]]] = []

    async def emit_event(self, event, *, rooms):
        self.calls.append((event, rooms))


class FakeRedisManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, list[str]]] = []

    async def emit(self, event, payload, *, room):
        self.calls.append((event, payload, room))


class Phase5RealtimeDeliveryTest(unittest.TestCase):
    def test_dashboard_envelope_uses_versioned_snake_case_schema(self) -> None:
        seller_id = uuid4()
        product_id = uuid4()
        occurred_at = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)

        envelope = DashboardRealtimeEnvelope(
            event=RealtimeEventType.COMPETITOR_EVENT_CREATED,
            seller_id=seller_id,
            product_id=product_id,
            occurred_at=occurred_at,
            data={"event_count": 2},
        )

        payload = envelope.model_dump(mode="json", by_alias=True)

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["event"], "competitor.event.created")
        self.assertEqual(payload["seller_id"], str(seller_id))
        self.assertEqual(payload["product_id"], str(product_id))
        self.assertEqual(payload["occurred_at"], "2026-06-29T12:00:00Z")
        self.assertEqual(payload["data"], {"event_count": 2})
        self.assertNotIn("sellerId", payload)
        self.assertNotIn("productId", payload)

    def test_publish_targets_authenticated_seller_and_product_rooms(self) -> None:
        seller_id = uuid4()
        product_id = uuid4()
        fake_emitter = FakeEmitter()

        async def run_test() -> bool:
            with patch(
                "app.services.phase5_realtime_service.get_socket_emitter",
                return_value=fake_emitter,
            ):
                return await Phase5RealtimePublisher().publish(
                    event=RealtimeEventType.COMPETITOR_SUMMARY_UPDATED,
                    seller_id=seller_id,
                    product_id=product_id,
                    data={"scrape_run_id": str(uuid4())},
                )

        result = asyncio.run(run_test())

        self.assertTrue(result)
        self.assertEqual(len(fake_emitter.calls), 1)
        event, rooms = fake_emitter.calls[0]
        self.assertEqual(event.seller_id, seller_id)
        self.assertEqual(event.product_id, product_id)
        self.assertEqual(set(rooms), {f"seller:{seller_id}", f"product:{product_id}"})

    def test_publish_failure_is_logged_and_not_raised(self) -> None:
        async def run_test() -> bool:
            with patch.object(
                settings,
                "redis_broker_url",
                None,
            ), patch(
                "app.services.phase5_realtime_service.get_socket_emitter",
                side_effect=RuntimeError("redis unavailable"),
            ):
                return await Phase5RealtimePublisher().publish(
                    event=RealtimeEventType.COMPETITOR_SUMMARY_UPDATED,
                    seller_id=uuid4(),
                    product_id=uuid4(),
                    data={},
                )

        self.assertFalse(asyncio.run(run_test()))

    def test_publish_falls_back_to_redis_manager_from_worker_process(self) -> None:
        seller_id = uuid4()
        product_id = uuid4()
        fake_manager = FakeRedisManager()

        async def run_test() -> bool:
            with patch.object(
                settings,
                "redis_broker_url",
                "redis://localhost:6379/0",
            ), patch(
                "app.services.phase5_realtime_service.get_socket_emitter",
                side_effect=RuntimeError("Socket emitter not initialized."),
            ), patch(
                "app.services.phase5_realtime_service.socketio.AsyncRedisManager",
                return_value=fake_manager,
            ):
                return await Phase5RealtimePublisher().publish(
                    event=RealtimeEventType.COMPETITOR_SUMMARY_UPDATED,
                    seller_id=seller_id,
                    product_id=product_id,
                    data={"scrape_run_id": str(uuid4())},
                )

        result = asyncio.run(run_test())

        self.assertTrue(result)
        self.assertEqual(len(fake_manager.calls), 1)
        event, payload, rooms = fake_manager.calls[0]
        self.assertEqual(event, "competitor.summary.updated")
        self.assertEqual(payload["seller_id"], str(seller_id))
        self.assertEqual(payload["product_id"], str(product_id))
        self.assertEqual(set(rooms), {f"seller:{seller_id}", f"product:{product_id}"})

    def test_product_room_subscription_rejects_cross_seller_access(self) -> None:
        seller_id = str(uuid4())
        product_id = str(uuid4())
        manager = RealtimeSocketManager.__new__(RealtimeSocketManager)

        async def owns_product(_seller_id: str, _product_id: str) -> bool:
            return False

        manager._owns_product = owns_product

        request = RoomSubscriptionRequest(
            rooms=[RoomTarget(scope=RoomScope.PRODUCT, id=product_id)]
        )
        rooms, rejected = asyncio.run(
            manager._resolve_authorized_rooms(
                request,
                seller_id=seller_id,
                include_seller_room=True,
            )
        )

        self.assertEqual(rooms, {f"seller:{seller_id}"})
        self.assertEqual(rejected, [f"product:{product_id}"])


if __name__ == "__main__":
    unittest.main()
