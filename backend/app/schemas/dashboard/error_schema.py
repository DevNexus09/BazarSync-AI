from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    code: str = Field(..., description="Machine readable error code")
    message: str = Field(..., description="Human readable error detail")


class DashboardErrorResponse(BaseModel):
    error: ErrorDetail

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "invalid_sort_field",
                        "message": "Sort field 'unknown' is not supported.",
                    }
                }
            ]
        }
    )
