from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RoomScope(str, Enum):
    SELLER = "seller"
    PRODUCT = "product"
    ALERTS = "alerts"
    DASHBOARD = "dashboard"
    ACTIVITY = "activity"
    CUSTOM = "custom"


class RoomTarget(BaseModel):
    scope: RoomScope
    id: str | None = None


class RoomSubscriptionRequest(BaseModel):
    rooms: list[RoomTarget] = Field(default_factory=list)


ALERTS_ROOM = "alerts"
DASHBOARD_ROOM = "dashboard"
ACTIVITY_ROOM = "activity"


def seller_room(seller_id: str) -> str:
    return f"seller:{seller_id}"


def product_room(product_id: str) -> str:
    return f"product:{product_id}"


def resolve_room(target: RoomTarget) -> str | None:
    if target.scope is RoomScope.SELLER and target.id:
        return seller_room(target.id)
    if target.scope is RoomScope.PRODUCT and target.id:
        return product_room(target.id)
    if target.scope is RoomScope.ALERTS:
        return ALERTS_ROOM
    if target.scope is RoomScope.DASHBOARD:
        return DASHBOARD_ROOM
    if target.scope is RoomScope.ACTIVITY:
        return ACTIVITY_ROOM
    if target.scope is RoomScope.CUSTOM and target.id:
        return target.id
    return None


def resolve_rooms(request: RoomSubscriptionRequest) -> set[str]:
    rooms: set[str] = set()
    for target in request.rooms:
        resolved = resolve_room(target)
        if resolved:
            rooms.add(resolved)
    return rooms
