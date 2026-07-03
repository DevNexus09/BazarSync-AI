from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.pricing_policy import (
    MarketplaceFeePolicyExpire,
    MarketplaceFeePolicyListResponse,
    MarketplaceFeePolicyResponse,
    MarketplaceFeePolicyUpsert,
    MinimumSafePricePreviewRequest,
    MinimumSafePricePreviewResponse,
    PricingPolicyResponse,
    PricingPolicyUpsert,
)
from app.services.pricing_calculator import PricingCalculationError
from app.services.pricing_policy_service import PricingPolicyNotFoundError, ProductOwnershipError, PricingPolicyService

router = APIRouter(prefix="/pricing-policies", tags=["pricing-policies"])


@router.get("/products/{product_id}", response_model=PricingPolicyResponse)
def get_product_pricing_policy(
    product_id: UUID,
    marketplace: str = Query("Daraz Bangladesh", min_length=1, max_length=120),
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> PricingPolicyResponse:
    try:
        return PricingPolicyService(db).get_product_policy(
            seller_id=current_seller.id,
            product_id=product_id,
            marketplace=marketplace,
        )
    except ProductOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc


@router.put("/products/{product_id}", response_model=PricingPolicyResponse)
def update_product_pricing_policy(
    product_id: UUID,
    payload: PricingPolicyUpsert,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> PricingPolicyResponse:
    try:
        return PricingPolicyService(db).upsert_product_policy(
            seller_id=current_seller.id,
            product_id=product_id,
            payload=payload,
        )
    except ProductOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/marketplace-fees", response_model=MarketplaceFeePolicyResponse, status_code=status.HTTP_201_CREATED)
def create_marketplace_fee_policy(
    payload: MarketplaceFeePolicyUpsert,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> MarketplaceFeePolicyResponse:
    try:
        return PricingPolicyService(db).create_marketplace_fee_policy(
            seller_id=current_seller.id,
            payload=payload,
        )
    except ProductOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/marketplace-fees", response_model=MarketplaceFeePolicyListResponse)
def list_marketplace_fee_policies(
    product_id: UUID | None = Query(None),
    marketplace: str | None = Query(None, min_length=1, max_length=120),
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> MarketplaceFeePolicyListResponse:
    try:
        items = PricingPolicyService(db).list_marketplace_fee_policies(
            seller_id=current_seller.id,
            product_id=product_id,
            marketplace=marketplace,
        )
    except ProductOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc
    return MarketplaceFeePolicyListResponse(items=items, total=len(items))


@router.patch("/marketplace-fees/{fee_policy_id}/expire", response_model=MarketplaceFeePolicyResponse)
def expire_marketplace_fee_policy(
    fee_policy_id: UUID,
    payload: MarketplaceFeePolicyExpire,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> MarketplaceFeePolicyResponse:
    try:
        return PricingPolicyService(db).expire_marketplace_fee_policy(
            seller_id=current_seller.id,
            fee_policy_id=fee_policy_id,
            effective_to=payload.effective_to,
        )
    except PricingPolicyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fee policy not found.") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/products/{product_id}/fees/effective", response_model=MarketplaceFeePolicyResponse)
def get_effective_marketplace_fee_policy(
    product_id: UUID,
    marketplace: str = Query("Daraz Bangladesh", min_length=1, max_length=120),
    as_of: datetime | None = Query(None),
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> MarketplaceFeePolicyResponse:
    try:
        return PricingPolicyService(db).effective_fee_policy(
            seller_id=current_seller.id,
            product_id=product_id,
            marketplace=marketplace,
            as_of=as_of,
        )
    except ProductOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc


@router.post("/products/{product_id}/minimum-safe-price/preview", response_model=MinimumSafePricePreviewResponse)
def preview_minimum_safe_price(
    product_id: UUID,
    payload: MinimumSafePricePreviewRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> MinimumSafePricePreviewResponse:
    try:
        return PricingPolicyService(db).preview_minimum_safe_price(
            seller_id=current_seller.id,
            product_id=product_id,
            marketplace=payload.marketplace,
            candidate_price=payload.candidate_price,
            as_of=payload.as_of,
        )
    except ProductOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc
    except PricingCalculationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
