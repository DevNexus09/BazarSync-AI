from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.revenue_simulator import RevenueSimulationExplanationResponse, RevenueSimulationRequest, RevenueSimulationResponse
from app.services.pricing_simulator_explanation_service import PricingSimulatorExplanationService
from app.services.revenue_simulator_service import RevenueSimulatorService

router = APIRouter(tags=["pricing-simulator"])


@router.post("/products/{product_id}/pricing/simulate", response_model=RevenueSimulationResponse)
def simulate_product_revenue(
    product_id: UUID,
    payload: RevenueSimulationRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> RevenueSimulationResponse:
    try:
        return RevenueSimulatorService(db).simulate(
            seller_id=current_seller.id,
            product_id=product_id,
            candidate_prices=payload.candidate_prices,
            forecast_horizon_days=payload.forecast_horizon_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/products/{product_id}/pricing/simulate/explain", response_model=RevenueSimulationExplanationResponse)
async def explain_product_revenue_simulation(
    product_id: UUID,
    payload: RevenueSimulationRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> RevenueSimulationExplanationResponse:
    try:
        simulation = RevenueSimulatorService(db).simulate(
            seller_id=current_seller.id,
            product_id=product_id,
            candidate_prices=payload.candidate_prices,
            forecast_horizon_days=payload.forecast_horizon_days,
        )
        explanation = await PricingSimulatorExplanationService().explain(
            RevenueSimulationResponse.model_validate(simulation)
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return RevenueSimulationExplanationResponse(
        simulation=RevenueSimulationResponse.model_validate(simulation),
        explanation=str(explanation["explanation"]),
        summary=str(explanation["summary"]),
        risks=list(explanation["risks"]),
        next_steps=list(explanation["next_steps"]),
        model=explanation.get("model"),
    )
