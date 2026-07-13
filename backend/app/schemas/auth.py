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
    profile_image_url: str | None = Field(None, description="Seller profile image URL or data URL")
    address_line: str | None = Field(
        None, max_length=255, description="Business address line"
    )
    city: str | None = Field(None, max_length=120, description="Business city")
    country: str | None = Field(None, max_length=120, description="Business country")


class SellerCreate(SellerBase):
    password: str = Field(..., min_length=8, max_length=72, description="Seller password")


class SellerLogin(BaseModel):
    email: EmailStr = Field(..., description="Seller email address")
    password: str = Field(..., min_length=8, max_length=72, description="Seller password")


class SellerProfileUpdate(BaseModel):
    phone: str | None = Field(None, description="Seller phone number")
    full_name: str | None = Field(None, max_length=120, description="Seller full name")
    business_name: str | None = Field(
        None, max_length=255, description="Registered business name"
    )
    industry: str | None = Field(None, max_length=120, description="Business industry")
    website: str | None = Field(None, max_length=255, description="Business website")
    profile_image_url: str | None = Field(None, description="Seller profile image URL or data URL")
    address_line: str | None = Field(
        None, max_length=255, description="Business address line"
    )
    city: str | None = Field(None, max_length=120, description="Business city")
    country: str | None = Field(None, max_length=120, description="Business country")


class SellerDeleteRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=72, description="Seller password")


class PasswordResetEmailRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address for the reset request")


class PasswordResetCodeRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address used for the reset request")
    # Keep code shape validation in the route so validation errors never echo
    # a submitted secret back to the client.
    code: str = Field(..., description="One-time verification code")


class PasswordResetMessageResponse(BaseModel):
    message: str


class PasswordResetVerifyResponse(BaseModel):
    message: str
    reset_authorization: str
    expires_at: datetime


class PasswordResetSetPasswordRequest(BaseModel):
    # Password policy validation belongs to the shared security service. Plain
    # values are deliberately not included in validation error responses.
    new_password: str = Field(..., description="New account password")
    confirm_password: str = Field(..., description="Confirmation of new password")


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
