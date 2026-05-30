from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ActivityCategory(str, Enum):
    recommendation = "recommendation"
    alert = "alert"
    competitor = "competitor"
    system = "system"


class ActivitySeverity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class ActivityItem(BaseModel):
    id: str
    title: str
    description: str
    timestamp: datetime
    category: ActivityCategory
    severity: ActivitySeverity

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "rec-9f3a4f02",
                    "title": "Recommendation generated",
                    "description": "Lower price recommendation for Dove Body Lotion 200ml.",
                    "timestamp": "2026-05-26T22:05:00Z",
                    "category": "recommendation",
                    "severity": "info",
                }
            ]
        }
    )
