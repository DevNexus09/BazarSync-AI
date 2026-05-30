from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class OpportunityMetricRecord(BaseModel):
    id: str
    label: str
    value: float | str
    delta: float | str | None
    trend: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "revenue-opportunity",
                    "label": "Revenue opportunity",
                    "value": 4200.0,
                    "delta": 650.0,
                    "trend": "up",
                }
            ]
        }
    )
