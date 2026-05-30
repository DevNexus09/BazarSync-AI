from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CompetitorPriceTrendPoint(BaseModel):
    timestamp: datetime
    competitor_price: float = Field(..., ge=0)
    seller_price: float = Field(..., ge=0)
    market_average: float = Field(..., ge=0)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "timestamp": "2026-05-26T00:00:00Z",
                    "competitor_price": 410.0,
                    "seller_price": 450.0,
                    "market_average": 432.5,
                }
            ]
        }
    )
