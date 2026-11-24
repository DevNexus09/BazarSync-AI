from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.core.config import settings
from app.core.demo_mode import client_ip, consume_demo_quota
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.auth import (
    DeleteAccountResponse,
    LoginResponse,
    PasswordResetCodeRequest,
    PasswordResetEmailRequest,
    PasswordResetMessageResponse,
    PasswordResetSetPasswordRequest,
    PasswordResetVerifyResponse,
    RegisterResponse,
    SellerCreate,
    SellerDeleteRequest,
    SellerLogin,
    SellerProfileUpdate,
    SellerResponse,
)
from app.services.auth_service import (
    AuthService,
    DuplicateSellerError,
    InvalidCredentialsError,
    InvalidPasswordError,
)
from app.services.demo_seed_service import DEMO_EMAIL
from app.services.password_reset_rate_limiter import PasswordResetRateLimitExceeded
from app.services.password_reset_service import (
    PasswordResetError,
    PasswordResetInvalidCodeError,
    PasswordResetService,
    PasswordResetSessionExpiredError,
    PasswordResetValidationError,
)

router = APIRouter(prefix="/auth", tags=["auth"])
PASSWORD_RESET_GENERIC_MESSAGE = "If an account exists for this email, a verification code has been sent."


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
    except InvalidPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    access_token = create_access_token(
        subject=str(seller.id), auth_version=seller.auth_version
    )
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

    access_token = create_access_token(
        subject=str(seller.id), auth_version=seller.auth_version
    )
    return LoginResponse(access_token=access_token, seller=seller)


@router.post("/demo", response_model=LoginResponse)
def start_demo_session(request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    """Issue a restricted token for the seeded demo seller; no password is exposed."""
    if not settings.demo_mode_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if not consume_demo_quota("sessions", client_ip(request), settings.demo_max_sessions_per_ip_per_hour):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many demo sessions. Please try again later.",
            headers={"Retry-After": "3600"},
        )
    seller = db.scalar(select(Seller).where(func.lower(Seller.email) == DEMO_EMAIL))
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The demo store is not ready yet.",
        )
    access_token = create_access_token(
        subject=str(seller.id),
        expires_minutes=settings.demo_token_expire_minutes,
        auth_version=seller.auth_version,
        demo=True,
    )
    return LoginResponse(access_token=access_token, seller=SellerResponse.model_validate(seller))


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


@router.post("/delete-account", response_model=DeleteAccountResponse)
def delete_account(
    payload: SellerDeleteRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DeleteAccountResponse:
    service = AuthService(db)
    try:
        service.delete_seller_account(current_seller, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return DeleteAccountResponse()


@router.post(
    "/forgot-password/request-code",
    response_model=PasswordResetMessageResponse,
)
def request_password_reset_code(
    payload: PasswordResetEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> PasswordResetMessageResponse:
    try:
        PasswordResetService(db).request_code(
            email=str(payload.email),
            request_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", ""),
        )
    except PasswordResetRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please try again later.",
            headers={"Retry-After": "3600"},
        ) from exc
    except PasswordResetError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset is temporarily unavailable.",
        ) from exc
    return PasswordResetMessageResponse(message=PASSWORD_RESET_GENERIC_MESSAGE)


@router.post(
    "/forgot-password/resend-code",
    response_model=PasswordResetMessageResponse,
)
def resend_password_reset_code(
    payload: PasswordResetEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> PasswordResetMessageResponse:
    return request_password_reset_code(payload, request, db)


@router.post(
    "/forgot-password/verify-code",
    response_model=PasswordResetVerifyResponse,
)
def verify_password_reset_code(
    payload: PasswordResetCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> PasswordResetVerifyResponse:
    if (
        len(payload.code) != settings.password_reset_code_length
        or not payload.code.isascii()
        or not payload.code.isdigit()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The code is invalid or has expired.",
        )
    try:
        reset_authorization, expires_at = PasswordResetService(db).verify_code(
            email=str(payload.email),
            code=payload.code,
            request_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", ""),
        )
    except PasswordResetInvalidCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The code is invalid or has expired.",
        ) from exc
    except PasswordResetError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset is temporarily unavailable.",
        ) from exc
    return PasswordResetVerifyResponse(
        message="Code verified. You can now choose a new password.",
        reset_authorization=reset_authorization,
        expires_at=expires_at,
    )


@router.post(
    "/forgot-password/reset",
    response_model=PasswordResetMessageResponse,
)
def reset_password(
    payload: PasswordResetSetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    reset_authorization: str | None = Header(
        default=None,
        alias="X-Password-Reset-Authorization",
    ),
) -> PasswordResetMessageResponse:
    try:
        PasswordResetService(db).reset_password(
            reset_authorization=reset_authorization or "",
            new_password=payload.new_password,
            confirm_password=payload.confirm_password,
            request_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", ""),
        )
    except PasswordResetValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except PasswordResetSessionExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your reset session has expired. Start again.",
        ) from exc
    except PasswordResetError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset is temporarily unavailable.",
        ) from exc
    return PasswordResetMessageResponse(
        message="Your password has been reset successfully. Please log in with your new password."
    )
