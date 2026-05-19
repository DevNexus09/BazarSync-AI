from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from uuid import UUID
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.products import (
    ProductCreate,
    ProductDeleteResponse,
    ProductDetailResponse,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.services.product_service import ProductNotFoundError, ProductService

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
