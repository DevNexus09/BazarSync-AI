from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

ItemT = TypeVar("ItemT")


class PaginationMeta(BaseModel):
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    total_pages: int = Field(..., ge=0)
    has_next: bool
    has_prev: bool

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "total": 120,
                    "page": 2,
                    "page_size": 20,
                    "total_pages": 6,
                    "has_next": True,
                    "has_prev": True,
                }
            ]
        }
    )


class PaginatedResponse(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    meta: PaginationMeta

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [],
                    "meta": {
                        "total": 0,
                        "page": 1,
                        "page_size": 20,
                        "total_pages": 0,
                        "has_next": False,
                        "has_prev": False,
                    },
                }
            ]
        }
    )
