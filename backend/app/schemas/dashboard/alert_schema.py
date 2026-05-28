from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.dashboard.pagination_schema import PaginatedResponse


class AlertSortField(str, Enum):
    created_at = "created_at"
    urgency_score = "urgency_score"
    delivery_status = "delivery_status"


class AlertRecord(BaseModel):
    alert_id: str
    product_id: str
    product_title: str
    alert_type: str
    urgency_level: str
    action_type: str
    confidence: str
    delivery_status: str
    delivery_timestamp: datetime | None = None
    telegram_reference: str | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime


class AlertListResponse(PaginatedResponse[AlertRecord]):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "alert_id": "a3ed1ac6-2470-4a7b-91b1-447f0f2a60de",
                            "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                            "product_title": "Dove Body Lotion 200ml",
                            "alert_type": "urgency_alert",
                            "urgency_level": "HIGH",
                            "action_type": "PRICE_LOWER",
                            "confidence": "MEDIUM",
                            "delivery_status": "delivered",
                            "delivery_timestamp": "2026-05-26T22:02:00Z",
                            "telegram_reference": "chat:12345 msg:67890",
                            "is_read": False,
                            "read_at": None,
                            "created_at": "2026-05-26T22:01:30Z",
                        }
                    ],
                    "meta": {
                        "total": 1,
                        "page": 1,
                        "page_size": 20,
                        "total_pages": 1,
                        "has_next": False,
                        "has_prev": False,
                    },
                }
            ]
        }
    )
