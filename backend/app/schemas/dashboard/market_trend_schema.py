from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MarketTrendPoint(BaseModel):
    timestamp: datetime
    demand_index: float = Field(..., ge=0, le=100)
    urgency_index: float = Field(..., ge=0, le=100)
    opportunity_index: float = Field(..., ge=0, le=100)
    price_index: float = Field(..., ge=-100, le=100)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "timestamp": "2026-05-26T00:00:00Z",
                    "demand_index": 62.5,
                    "urgency_index": 58.1,
                    "opportunity_index": 71.4,
                    "price_index": -3.2,
                }
            ]
        }
    )
