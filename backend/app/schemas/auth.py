from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SellerBase(BaseModel):
    email: EmailStr = Field(..., description="Seller email address")
    phone: str | None = Field(None, description="Seller phone number")
    full_name: str | None = Field(None, max_length=120, description="Seller full name")
    business_name: str | None = Field(
        None, max_length=255, description="Registered business name"
    )
    industry: str | None = Field(None, max_length=120, description="Business industry")
    website: str | None = Field(None, max_length=255, description="Business website")
    address_line: str | None = Field(
        None, max_length=255, description="Business address line"
    )
    city: str | None = Field(None, max_length=120, description="Business city")
    country: str | None = Field(None, max_length=120, description="Business country")


class SellerCreate(SellerBase):
    password: str = Field(..., min_length=8, description="Seller password")


class SellerLogin(BaseModel):
    email: EmailStr = Field(..., description="Seller email address")
    password: str = Field(..., min_length=8, description="Seller password")


class SellerProfileUpdate(BaseModel):
    phone: str | None = Field(None, description="Seller phone number")
    full_name: str | None = Field(None, max_length=120, description="Seller full name")
    business_name: str | None = Field(
        None, max_length=255, description="Registered business name"
    )
    industry: str | None = Field(None, max_length=120, description="Business industry")
    website: str | None = Field(None, max_length=255, description="Business website")
    address_line: str | None = Field(
        None, max_length=255, description="Business address line"
    )
    city: str | None = Field(None, max_length=120, description="Business city")
    country: str | None = Field(None, max_length=120, description="Business country")


class SellerDeleteRequest(BaseModel):
    password: str = Field(..., min_length=8, description="Seller password")


class SellerResponse(SellerBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RegisterResponse(BaseModel):
    message: str = "Seller registered successfully."
    access_token: str
    token_type: str = "bearer"
    seller: SellerResponse


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    seller: SellerResponse


class DeleteAccountResponse(BaseModel):
    message: str = "Seller account deleted successfully."

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"message": "Seller account deleted successfully."}]
        }
    )
