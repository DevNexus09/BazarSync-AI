from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.seller import Seller
from app.schemas.auth import SellerCreate, SellerLogin, SellerProfileUpdate


class DuplicateSellerError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AuthService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_seller_by_email(self, email: str) -> Seller | None:
        normalized_email = _normalize_email(email)
        statement = select(Seller).where(func.lower(Seller.email) == normalized_email)
        return self._db.execute(statement).scalar_one_or_none()

    def get_seller_by_id(self, seller_id: UUID) -> Seller | None:
        return self._db.get(Seller, seller_id)

    def register_seller(self, payload: SellerCreate) -> Seller:
        if self.get_seller_by_email(payload.email):
            raise DuplicateSellerError

        seller = Seller(
            email=_normalize_email(payload.email),
            password_hash=payload.password,
            phone=payload.phone,
            full_name=payload.full_name,
            business_name=payload.business_name,
            industry=payload.industry,
            website=payload.website,
            profile_image_url=payload.profile_image_url,
            address_line=payload.address_line,
            city=payload.city,
            country=payload.country,
        )
        self._db.add(seller)
        self._db.commit()
        self._db.refresh(seller)
        return seller

    def authenticate_seller(self, payload: SellerLogin) -> Seller:
        seller = self.get_seller_by_email(payload.email)
        if not seller or payload.password != seller.password_hash:
            raise InvalidCredentialsError
        return seller

    def update_seller_profile(self, seller: Seller, payload: SellerProfileUpdate) -> Seller:
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(seller, field, value)
        self._db.add(seller)
        self._db.commit()
        self._db.refresh(seller)
        return seller

    def delete_seller_account(self, seller: Seller, password: str) -> None:
        if password != seller.password_hash:
            raise InvalidCredentialsError
        self._db.delete(seller)
        self._db.commit()


def _normalize_email(email: str) -> str:
    return str(email).strip().lower()
