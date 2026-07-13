from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CatalogValidationError(ValueError):
    """Raised when a catalog or metric request is outside the allowlist."""


class BusinessDomainKey(str, Enum):
    PRODUCT_CATALOG = "PRODUCT_CATALOG"
    SALES_REVENUE = "SALES_REVENUE"
    PROFIT_MARGIN = "PROFIT_MARGIN"
    INVENTORY = "INVENTORY"
    COMPETITOR = "COMPETITOR"
    PRICING = "PRICING"
    PROMOTION = "PROMOTION"
    DEAD_STOCK = "DEAD_STOCK"
    SEO_VISIBILITY = "SEO_VISIBILITY"
    RECOMMENDATIONS = "RECOMMENDATIONS"
    ALERTS = "ALERTS"
    RAG_MEMORY = "RAG_MEMORY"
    COPILOT = "COPILOT"


DEFAULT_RESTRICTED_FIELDS: tuple[str, ...] = (
    "password",
    "password_hash",
    "token",
    "api_key",
    "apikey",
    "cookie",
    "secret",
    "stack_trace",
    "traceback",
    "raw_html",
    "html",
    "unrelated_seller_data",
    "customer_email",
    "customer_phone",
    "customer_name",
    "customer_message",
    "private_customer_data",
    "telegram_chat_id",
    "telegram_user_id",
    "telegram_message_id",
)


COMMON_SELLER_FILTERS: tuple[str, ...] = (
    "seller_id",
    "product_id",
    "category",
    "marketplace",
    "from_date",
    "to_date",
)


@dataclass(frozen=True, slots=True)
class QueryConstraint:
    seller_field: str
    product_field: str | None
    date_field: str | None
    allowed_filters: tuple[str, ...]
    allowed_group_by: tuple[str, ...] = ()
    required_filters: tuple[str, ...] = ("seller_id",)

    def validate(
        self,
        *,
        filters: dict[str, Any] | None = None,
        group_by: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        filter_keys = set(filters or {})
        group_by_values = set(group_by or ())
        missing_required = set(self.required_filters) - filter_keys
        if missing_required:
            raise CatalogValidationError(f"Missing required filter(s): {sorted(missing_required)}")
        unsupported_filters = filter_keys - set(self.allowed_filters)
        if unsupported_filters:
            raise CatalogValidationError(f"Unsupported filter(s): {sorted(unsupported_filters)}")
        unsupported_group_by = group_by_values - set(self.allowed_group_by)
        if unsupported_group_by:
            raise CatalogValidationError(f"Unsupported group_by field(s): {sorted(unsupported_group_by)}")


def field_is_restricted(field_name: str, restricted_fields: tuple[str, ...] = DEFAULT_RESTRICTED_FIELDS) -> bool:
    normalized = field_name.lower()
    return any(restricted in normalized for restricted in restricted_fields)


def safe_field_tuple(fields: tuple[str, ...], restricted_fields: tuple[str, ...] = DEFAULT_RESTRICTED_FIELDS) -> tuple[str, ...]:
    return tuple(field for field in fields if not field_is_restricted(field, restricted_fields))


def ensure_no_restricted_fields(fields: tuple[str, ...], restricted_fields: tuple[str, ...] = DEFAULT_RESTRICTED_FIELDS) -> None:
    restricted = [field for field in fields if field_is_restricted(field, restricted_fields)]
    if restricted:
        raise CatalogValidationError(f"Restricted field(s) are not allowed: {restricted}")

