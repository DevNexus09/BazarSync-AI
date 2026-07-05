from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.dead_stock_capital_recovery import (
    DeadStockCapitalRecoveryEstimateResponse,
    DeadStockRecoverySimulationRequest,
    LatestDeadStockCapitalRecoveryEstimateResponse,
)
from app.services.dead_stock_capital_recovery_service import DeadStockCapitalRecoveryService, RecoverySimulationInput
from app.services.product_service import ProductService

router = APIRouter(tags=["dead-stock-capital-recovery"])


@router.get("/products/{product_id}/dead-stock/capital-recovery", response_model=LatestDeadStockCapitalRecoveryEstimateResponse)
def get_latest_dead_stock_capital_recovery(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> LatestDeadStockCapitalRecoveryEstimateResponse:
    item = DeadStockCapitalRecoveryService(db).latest_estimate(
        seller_id=current_seller.id,
        product_id=product_id,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return LatestDeadStockCapitalRecoveryEstimateResponse(
        item=DeadStockCapitalRecoveryEstimateResponse.model_validate(item) if item else None,
    )


@router.post("/products/{product_id}/dead-stock/recovery-simulations", response_model=DeadStockCapitalRecoveryEstimateResponse)
def simulate_dead_stock_capital_recovery(
    product_id: UUID,
    payload: DeadStockRecoverySimulationRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DeadStockCapitalRecoveryEstimateResponse:
    if not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    estimate = DeadStockCapitalRecoveryService(db).simulate_for_product(
        seller_id=current_seller.id,
        product_id=product_id,
        simulation=RecoverySimulationInput(
            action=payload.action,
            candidate_discount=payload.candidate_discount,
            candidate_price=payload.candidate_price,
            duration_days=payload.duration_days,
            eligible_quantity=payload.eligible_quantity,
        ),
    )
    return DeadStockCapitalRecoveryEstimateResponse.model_validate(estimate)
