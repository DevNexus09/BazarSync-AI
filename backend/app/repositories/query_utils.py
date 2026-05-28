from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import ceil
from typing import Any, Iterable, Mapping

from sqlalchemy import ColumnElement
from sqlalchemy.sql import Select

from app.services.dashboard.exceptions import InvalidSortFieldError, PaginationOverflowError


class SortDirection(str, Enum):
    asc = "asc"
    desc = "desc"


@dataclass(frozen=True)
class PaginationParams:
    limit: int
    offset: int
    page: int
    page_size: int
    max_page_size: int = 100

    @classmethod
    def from_request(
        cls,
        *,
        limit: int | None = None,
        offset: int | None = None,
        page: int | None = None,
        page_size: int | None = None,
        max_page_size: int = 100,
        default_page_size: int = 20,
    ) -> "PaginationParams":
        if page is not None or page_size is not None:
            resolved_page = max(1, page or 1)
            resolved_size = max(1, page_size or default_page_size)
            resolved_size = min(resolved_size, max_page_size)
            resolved_offset = (resolved_page - 1) * resolved_size
            return cls(
                limit=resolved_size,
                offset=resolved_offset,
                page=resolved_page,
                page_size=resolved_size,
                max_page_size=max_page_size,
            )

        resolved_limit = max(1, limit or default_page_size)
        resolved_limit = min(resolved_limit, max_page_size)
        resolved_offset = max(0, offset or 0)
        resolved_page = (resolved_offset // resolved_limit) + 1
        return cls(
            limit=resolved_limit,
            offset=resolved_offset,
            page=resolved_page,
            page_size=resolved_limit,
            max_page_size=max_page_size,
        )


def build_pagination_meta(total: int, params: PaginationParams) -> dict[str, Any]:
    total_pages = ceil(total / params.page_size) if params.page_size else 0
    if total_pages and params.page > total_pages:
        raise PaginationOverflowError("Requested page exceeds total pages.")
    return {
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "total_pages": total_pages,
        "has_next": (params.offset + params.limit) < total,
        "has_prev": params.page > 1,
    }


def apply_sorting(
    statement: Select,
    *,
    sort_by: str,
    sort_direction: SortDirection,
    allowed: Mapping[str, ColumnElement[Any]],
) -> Select:
    if sort_by not in allowed:
        raise InvalidSortFieldError(f"Sort field '{sort_by}' is not supported.")
    column = allowed[sort_by]
    return statement.order_by(column.asc() if sort_direction == SortDirection.asc else column.desc())


def apply_search(
    statement: Select,
    *,
    search: str | None,
    columns: Iterable[ColumnElement[str]],
) -> Select:
    if not search:
        return statement
    sanitized = f"%{search.strip()}%"
    conditions = [column.ilike(sanitized) for column in columns]
    if not conditions:
        return statement
    return statement.where(_or_(*conditions))


def apply_date_range(
    statement: Select,
    *,
    column: ColumnElement[datetime],
    start: datetime | None,
    end: datetime | None,
) -> Select:
    if start is not None:
        statement = statement.where(column >= start)
    if end is not None:
        statement = statement.where(column <= end)
    return statement


def _or_(*conditions: ColumnElement[bool]) -> ColumnElement[bool]:
    from sqlalchemy import or_

    return or_(*conditions)
