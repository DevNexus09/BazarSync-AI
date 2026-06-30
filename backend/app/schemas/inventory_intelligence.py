from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.inventory_risk import InventoryRiskDataStatus, InventoryRiskLevel
from app.models.reorder_recommendation import ReorderRecommendationAction, ReorderRecommendationStatus
from app.models.sales_velocity import SalesVelocityDataStatus
from app.models.stockout_prediction import StockoutPredictionStatus


class InventoryIntelligenceSummaryResponse(BaseModel):
    total_active_products: int
    low_risk_products: int
    medium_risk_products: int
    high_risk_products: int
    critical_risk_products: int
    insufficient_data_products: int
    products_requiring_reorder: int
    products_already_out_of_stock: int
    last_calculation_time: datetime | None
    data_freshness_status: str


class ProductInventoryIntelligenceResponse(BaseModel):
    product_id: UUID
    product_name: str
    category: str | None
    latest_inventory_snapshot_id: UUID | None
    inventory_snapshot_date: date | None
    quantity_on_hand: int | None
    quantity_reserved: int | None
    quantity_available: int | None
    quantity_incoming: int | None
    daily_sales_rate: Decimal | None
    velocity_window_days: int | None
    velocity_data_status: SalesVelocityDataStatus | None
    days_remaining: Decimal | None
    predicted_stockout_date: date | None
    stockout_prediction_status: StockoutPredictionStatus | None
    supplier_lead_time_days: int | None
    safety_buffer_days: int | None
    inventory_risk_score: Decimal | None
    risk_level: InventoryRiskLevel | None
    reorder_action: ReorderRecommendationAction | None
    recommended_quantity: int | None
    reorder_deadline: date | None
    confidence_score: Decimal | None
    data_status: InventoryRiskDataStatus | None
    explanation: str | None
    calculation_version: str | None
    as_of_date: date | None
    last_updated_at: datetime | None
    metadata: dict[str, Any] | None = None


class InventoryIntelligenceListItem(BaseModel):
    product_id: UUID
    product_name: str
    category: str | None
    risk_level: InventoryRiskLevel | None
    risk_score: Decimal | None
    data_status: InventoryRiskDataStatus | None
    days_remaining: Decimal | None
    predicted_stockout_date: date | None
    reorder_action: ReorderRecommendationAction | None
    recommendation_status: ReorderRecommendationStatus | None
    recommended_quantity: int | None
    reorder_deadline: date | None
    calculation_version: str | None
    as_of_date: date | None
    last_updated_at: datetime | None


class InventoryIntelligencePageResponse(BaseModel):
    items: list[InventoryIntelligenceListItem]
    total: int
    limit: int
    offset: int


class InventoryWorkflowEnqueueResponse(BaseModel):
    workflow_id: str
    scope: str
    seller_id: UUID | None = None
    product_id: UUID | None = None
    as_of_date: date | None = None

    model_config = ConfigDict(from_attributes=True)
