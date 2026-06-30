from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from uuid import UUID
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.scrape import (
    CompetitorSnapshotPageResponse,
    CompetitorSnapshotResponse,
    CompetitorTimelineResponse,
    ScrapeRunPageResponse,
    ScrapeRunSummaryResponse,
)
from app.schemas.products import (
    ProductCreate,
    ProductDeleteResponse,
    ProductDetailResponse,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.schemas.inventory_history import (
    InventoryHistoryPageResponse,
    InventoryHistoryResponse,
    LatestInventoryHistoryResponse,
)
from app.schemas.inventory_risk import (
    InventoryRiskPageResponse,
    InventoryRiskResponse,
    LatestInventoryRiskResponse,
)
from app.schemas.inventory_intelligence import ProductInventoryIntelligenceResponse
from app.schemas.sales_velocity import (
    LatestSalesVelocityResponse,
    SalesVelocityHistoryResponse,
    SalesVelocityResponse,
)
from app.schemas.reorder_recommendation import (
    LatestReorderRecommendationResponse,
    ReorderRecommendationHistoryResponse,
    ReorderRecommendationResponse,
)
from app.schemas.stockout_prediction import (
    LatestStockoutPredictionResponse,
    StockoutPredictionHistoryResponse,
    StockoutPredictionResponse,
)
from app.services.product_service import ProductNotFoundError, ProductService
from app.services.competitor_snapshot_service import CompetitorSnapshotService
from app.services.inventory_history_service import InventoryHistoryService
from app.services.inventory_intelligence_service import InventoryIntelligenceService
from app.services.inventory_risk_service import InventoryRiskService
from app.services.reorder_recommendation_service import ReorderRecommendationService
from app.services.sales_velocity_service import SalesVelocityService
from app.services.stockout_prediction_service import StockoutPredictionService
from app.repositories.competitor_snapshot_repository import ScrapeRunRepository

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductDetailResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductDetailResponse:
    service = ProductService(db)
    product = service.create_product(current_seller.id, payload)
    return ProductDetailResponse(message="Product created successfully.", product=product)


@router.get("", response_model=ProductListResponse)
def list_products(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ProductListResponse:
    service = ProductService(db)
    items, total = service.list_products(current_seller.id, limit=limit, offset=offset)
    return ProductListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductResponse:
    service = ProductService(db)
    product = service.get_product(current_seller.id, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return product


@router.put("/{product_id}", response_model=ProductDetailResponse)
def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductDetailResponse:
    service = ProductService(db)
    try:
        product = service.update_product(current_seller.id, product_id, payload)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc
    return ProductDetailResponse(message="Product updated successfully.", product=product)


@router.delete("/{product_id}", response_model=ProductDeleteResponse)
def delete_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductDeleteResponse:
    service = ProductService(db)
    try:
        service.delete_product(current_seller.id, product_id)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc
    return ProductDeleteResponse(message="Product deleted successfully.")


@router.get("/{product_id}/inventory-history", response_model=InventoryHistoryPageResponse)
def get_product_inventory_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> InventoryHistoryPageResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    items, total = InventoryHistoryService(db).list_product_history(
        seller_id=current_seller.id,
        product_id=product_id,
        from_date=from_date,
        to_date=to_date,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}/inventory-intelligence", response_model=ProductInventoryIntelligenceResponse)
def get_product_inventory_intelligence(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductInventoryIntelligenceResponse:
    item = InventoryIntelligenceService(db).product_intelligence(
        seller_id=current_seller.id,
        product_id=product_id,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return item
    if total == 0 and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return InventoryHistoryPageResponse(
        items=[InventoryHistoryResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}/inventory-history/latest", response_model=LatestInventoryHistoryResponse)
def get_latest_product_inventory_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> LatestInventoryHistoryResponse:
    item = InventoryHistoryService(db).latest_product_snapshot(
        seller_id=current_seller.id,
        product_id=product_id,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return LatestInventoryHistoryResponse(
        item=InventoryHistoryResponse.model_validate(item) if item else None
    )


@router.get("/{product_id}/sales-velocity", response_model=LatestSalesVelocityResponse)
def get_latest_product_sales_velocity(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    window_days: int | None = Query(None, ge=1, le=365),
    calculation_version: str | None = Query(None, max_length=20),
) -> LatestSalesVelocityResponse:
    item = SalesVelocityService(db).latest_velocity(
        seller_id=current_seller.id,
        product_id=product_id,
        window_days=window_days,
        calculation_version=calculation_version,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return LatestSalesVelocityResponse(
        item=SalesVelocityResponse.model_validate(item) if item else None
    )


@router.get("/{product_id}/sales-velocity/history", response_model=SalesVelocityHistoryResponse)
def get_product_sales_velocity_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    window_days: int | None = Query(None, ge=1, le=365),
    calculation_version: str | None = Query(None, max_length=20),
) -> SalesVelocityHistoryResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    items, total = SalesVelocityService(db).velocity_history(
        seller_id=current_seller.id,
        product_id=product_id,
        from_date=from_date,
        to_date=to_date,
        window_days=window_days,
        calculation_version=calculation_version,
        order=order,
        limit=limit,
        offset=offset,
    )
    if total == 0 and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return SalesVelocityHistoryResponse(
        items=[SalesVelocityResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}/stockout-prediction", response_model=LatestStockoutPredictionResponse)
def get_latest_product_stockout_prediction(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    calculation_version: str | None = Query(None, max_length=20),
) -> LatestStockoutPredictionResponse:
    item = StockoutPredictionService(db).latest_prediction(
        seller_id=current_seller.id,
        product_id=product_id,
        calculation_version=calculation_version,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return LatestStockoutPredictionResponse(
        item=StockoutPredictionResponse.model_validate(item) if item else None
    )


@router.get("/{product_id}/stockout-predictions/history", response_model=StockoutPredictionHistoryResponse)
def get_product_stockout_prediction_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    calculation_version: str | None = Query(None, max_length=20),
) -> StockoutPredictionHistoryResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    items, total = StockoutPredictionService(db).prediction_history(
        seller_id=current_seller.id,
        product_id=product_id,
        from_date=from_date,
        to_date=to_date,
        calculation_version=calculation_version,
        order=order,
        limit=limit,
        offset=offset,
    )
    if total == 0 and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return StockoutPredictionHistoryResponse(
        items=[StockoutPredictionResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}/reorder-recommendation", response_model=LatestReorderRecommendationResponse)
def get_latest_product_reorder_recommendation(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    calculation_version: str | None = Query(None, max_length=20),
) -> LatestReorderRecommendationResponse:
    item = ReorderRecommendationService(db).latest_recommendation(
        seller_id=current_seller.id,
        product_id=product_id,
        calculation_version=calculation_version,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return LatestReorderRecommendationResponse(
        item=ReorderRecommendationResponse.model_validate(item) if item else None
    )


@router.get("/{product_id}/reorder-recommendations/history", response_model=ReorderRecommendationHistoryResponse)
def get_product_reorder_recommendation_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    calculation_version: str | None = Query(None, max_length=20),
) -> ReorderRecommendationHistoryResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    items, total = ReorderRecommendationService(db).recommendation_history(
        seller_id=current_seller.id,
        product_id=product_id,
        from_date=from_date,
        to_date=to_date,
        calculation_version=calculation_version,
        order=order,
        limit=limit,
        offset=offset,
    )
    if total == 0 and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return ReorderRecommendationHistoryResponse(
        items=[ReorderRecommendationResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}/inventory-risk", response_model=LatestInventoryRiskResponse)
def get_latest_product_inventory_risk(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    calculation_version: str | None = Query(None, max_length=20),
) -> LatestInventoryRiskResponse:
    item = InventoryRiskService(db).latest_risk(
        seller_id=current_seller.id,
        product_id=product_id,
        calculation_version=calculation_version,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return LatestInventoryRiskResponse(item=InventoryRiskResponse.model_validate(item) if item else None)


@router.get("/{product_id}/inventory-risks/history", response_model=InventoryRiskPageResponse)
def get_product_inventory_risk_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    calculation_version: str | None = Query(None, max_length=20),
) -> InventoryRiskPageResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    items, total = InventoryRiskService(db).risk_history(
        seller_id=current_seller.id,
        product_id=product_id,
        from_date=from_date,
        to_date=to_date,
        calculation_version=calculation_version,
        order=order,
        limit=limit,
        offset=offset,
    )
    if total == 0 and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return InventoryRiskPageResponse(
        items=[InventoryRiskResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}/competitor-snapshots/latest", response_model=CompetitorSnapshotPageResponse)
def get_latest_competitor_snapshots(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> CompetitorSnapshotPageResponse:
    if not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    items, total = CompetitorSnapshotService(db).get_latest_product_snapshots(
        seller_id=current_seller.id,
        product_id=product_id,
        limit=limit,
        offset=offset,
    )
    return CompetitorSnapshotPageResponse(
        items=[CompetitorSnapshotResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}/competitors/{competitor_id}/snapshots", response_model=CompetitorTimelineResponse)
def get_competitor_snapshot_timeline(
    product_id: UUID,
    competitor_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    from_at: datetime | None = Query(None, alias="from"),
    to_at: datetime | None = Query(None, alias="to"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
) -> CompetitorTimelineResponse:
    if from_at and to_at and _ensure_utc(from_at) > _ensure_utc(to_at):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")

    items, total = CompetitorSnapshotService(db).get_competitor_timeline(
        seller_id=current_seller.id,
        product_id=product_id,
        competitor_id=competitor_id,
        from_at=_ensure_utc(from_at) if from_at else None,
        to_at=_ensure_utc(to_at) if to_at else None,
        order=order,
        limit=limit,
        offset=offset,
    )
    if total == 0 and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    return CompetitorTimelineResponse(
        product_id=product_id,
        competitor_id=competitor_id,
        items=[CompetitorSnapshotResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}/scrape-runs", response_model=ScrapeRunPageResponse)
def get_recent_product_scrape_runs(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    run_status: str | None = Query(None, alias="status"),
    marketplace: str | None = Query(None),
    from_at: datetime | None = Query(None, alias="from"),
    to_at: datetime | None = Query(None, alias="to"),
) -> ScrapeRunPageResponse:
    if from_at and to_at and _ensure_utc(from_at) > _ensure_utc(to_at):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    if not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    items, total = ScrapeRunRepository(db).recent_for_product(
        seller_id=current_seller.id,
        product_id=product_id,
        status=run_status.upper() if run_status else None,
        marketplace=marketplace,
        from_at=_ensure_utc(from_at) if from_at else None,
        to_at=_ensure_utc(to_at) if to_at else None,
        limit=limit,
        offset=offset,
    )
    return ScrapeRunPageResponse(
        items=[ScrapeRunSummaryResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
