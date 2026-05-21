from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.auth import (
    LoginResponse,
    RegisterResponse,
    SellerCreate,
    SellerLogin,
    SellerProfileUpdate,
    SellerResponse,
)
from app.services.auth_service import AuthService, DuplicateSellerError, InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register_seller(payload: SellerCreate, db: Session = Depends(get_db)) -> RegisterResponse:
    service = AuthService(db)
    try:
        seller = service.register_seller(payload)
    except DuplicateSellerError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seller account already exists.",
        ) from exc
    access_token = create_access_token(subject=str(seller.id))
    return RegisterResponse(access_token=access_token, seller=seller)


@router.post("/login", response_model=LoginResponse)
def login_seller(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> LoginResponse:
    service = AuthService(db)
    payload = SellerLogin(email=form_data.username, password=form_data.password)
    try:
        seller = service.authenticate_seller(payload)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    access_token = create_access_token(subject=str(seller.id))
    return LoginResponse(access_token=access_token, seller=seller)


@router.get("/me", response_model=SellerResponse)
def get_me(current_seller: Seller = Depends(get_current_seller)) -> SellerResponse:
    return current_seller


@router.patch("/profile", response_model=SellerResponse)
def update_profile(
    payload: SellerProfileUpdate,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> SellerResponse:
    service = AuthService(db)
    seller = service.update_seller_profile(current_seller, payload)
    return seller
