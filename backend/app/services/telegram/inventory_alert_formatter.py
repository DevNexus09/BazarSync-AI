from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.models.inventory_risk import InventoryRiskLevel
from app.models.telegram_inventory_alert import TelegramInventoryAlertType


@dataclass(frozen=True)
class InventoryAlertMessageContext:
    alert_type: TelegramInventoryAlertType
    product_name: str
    current_stock: int | None
    daily_sales_rate: Decimal | None
    days_remaining: Decimal | None
    predicted_stockout_date: date | None
    supplier_lead_time_days: int | None
    safety_buffer_days: int | None
    risk_level: InventoryRiskLevel | str | None
    recommended_action: str | None
    recommended_quantity: int | None
    reorder_deadline: date | None
    dashboard_url: str | None = None


def format_inventory_alert_message(context: InventoryAlertMessageContext) -> str:
    lines = [
        "Inventory Alert",
        "",
        f"Product: {context.product_name}",
    ]
    if context.current_stock is not None:
        lines.append(f"Current Stock: {context.current_stock} units")
    if context.daily_sales_rate is not None:
        lines.append(f"Daily Sales Rate: {_format_decimal(context.daily_sales_rate)} units/day")
    if context.days_remaining is not None:
        lines.append(f"Predicted Stockout: {_format_decimal(context.days_remaining)} days")
    if context.predicted_stockout_date is not None:
        lines.append(f"Predicted Stockout Date: {context.predicted_stockout_date.isoformat()}")
    if context.supplier_lead_time_days is not None:
        lines.append(f"Supplier Lead Time: {context.supplier_lead_time_days} days")
    if context.safety_buffer_days is not None:
        lines.append(f"Safety Buffer: {context.safety_buffer_days} days")
    if context.risk_level is not None:
        lines.append(f"Risk Level: {_enum_value(context.risk_level)}")
    if context.recommended_action:
        lines.append("")
        lines.append(f"Recommended Action: {context.recommended_action}")
    if context.recommended_quantity is not None:
        lines.append(f"Recommended Quantity: {context.recommended_quantity} units")
    if context.reorder_deadline is not None:
        lines.append(f"Order Deadline: {_format_deadline(context.reorder_deadline)}")
    if context.dashboard_url:
        lines.append("")
        lines.append(f"Dashboard: {context.dashboard_url}")
    return "\n".join(lines)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _format_decimal(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.01"))
    return format(normalized.normalize(), "f")


def _format_deadline(value: date) -> str:
    return value.isoformat()
