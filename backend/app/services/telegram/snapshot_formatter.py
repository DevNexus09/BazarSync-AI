from __future__ import annotations

from datetime import timezone

from app.schemas.product_snapshot import ProductSnapshot


def format_product_snapshot(snapshot: ProductSnapshot) -> str:
    return "\n".join(
        [
            "📊 BazarSync AI Product Intelligence",
            "",
            f"🛒 Product:\n{snapshot.product_name}",
            "",
            f"💰 Current Price:\n{_format_currency(snapshot.current_price, snapshot.currency)}",
            "",
            f"📦 Current Stock:\n{snapshot.current_stock} units",
            "",
            f"🚚 Supplier Lead Time:\n{_format_lead_time(snapshot.supplier_lead_time)}",
            "",
            f"📉 Competitor Median Price:\n"
            f"{_format_currency(snapshot.competitor_median_price, snapshot.currency)}",
            "",
            f"⚠️ Price Gap:\n{_format_percent(snapshot.price_gap_percent)}",
            "",
            f"🤖 Latest AI Recommendation:\n{_format_action(snapshot.recommendation_action)}",
            "",
            f"🧠 AI Reason:\n{_format_reason(snapshot.ai_reason)}",
            "",
            f"📈 Confidence:\n{snapshot.confidence}",
            "",
            f"⏰ Updated:\n{_format_timestamp(snapshot.updated_at)}",
        ]
    )


def _format_currency(value: float | None, currency: str) -> str:
    if value is None:
        return "N/A"
    return f"{currency}{value:,.0f}"


def _format_lead_time(value: int | None) -> str:
    if value is None:
        return "N/A"
    return f"{value} days"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f}%"


def _format_action(action: str) -> str:
    normalized = action.strip().upper()
    mapping = {
        "LOWER": "PRICE LOWER",
        "RAISE": "PRICE RAISE",
        "HOLD": "PRICE HOLD",
        "REORDER": "REORDER STOCK",
    }
    return mapping.get(normalized, normalized.replace("_", " "))


def _format_reason(reason: str | None) -> str:
    if not reason:
        return "N/A"
    return reason.strip()


def _format_timestamp(value) -> str:
    timestamp = value.astimezone(timezone.utc)
    return timestamp.strftime("%Y-%m-%d %I:%M %p")
