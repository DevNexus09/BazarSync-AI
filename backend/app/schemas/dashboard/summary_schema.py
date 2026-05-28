from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RealtimeActivityCounters(BaseModel):
    recommendations_last_hour: int = Field(..., ge=0)
    alerts_last_hour: int = Field(..., ge=0)
    competitor_updates_last_hour: int = Field(..., ge=0)
    stock_risk_events_last_hour: int = Field(..., ge=0)


class DashboardSummaryResponse(BaseModel):
    total_monitored_products: int = Field(..., ge=0)
    active_alerts: int = Field(..., ge=0)
    opportunity_count: int = Field(..., ge=0)
    high_risk_stock_count: int = Field(..., ge=0)
    average_urgency_score: float = Field(..., ge=0, le=100)
    average_competitor_price_gap: float = Field(..., ge=-100, le=100)
    market_trend_summary: str
    realtime_activity: RealtimeActivityCounters
    generated_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "total_monitored_products": 125,
                    "active_alerts": 6,
                    "opportunity_count": 22,
                    "high_risk_stock_count": 4,
                    "average_urgency_score": 58.3,
                    "average_competitor_price_gap": 6.2,
                    "market_trend_summary": "Moderate volatility with rising competitor pressure.",
                    "realtime_activity": {
                        "recommendations_last_hour": 12,
                        "alerts_last_hour": 4,
                        "competitor_updates_last_hour": 31,
                        "stock_risk_events_last_hour": 3,
                    },
                    "generated_at": "2026-05-26T22:00:00Z",
                }
            ]
        }
    )
