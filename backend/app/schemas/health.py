from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(..., description="Overall service status")
    database: str = Field(..., description="Database connectivity status")
