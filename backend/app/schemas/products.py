from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID

Price = Annotated[Decimal, Field(max_digits=12, decimal_places=2, ge=0)]
Margin = Annotated[Decimal, Field(max_digits=8, decimal_places=2, ge=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class ProductBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Product title")
    cost_price: Price = Field(..., description="Product cost price")
    selling_price: Price = Field(..., description="Product selling price")
    stock_quantity: NonNegativeInt = Field(..., description="Current stock quantity")
    supplier_lead_time: PositiveInt = Field(..., description="Supplier lead time in days")
    minimum_margin: Margin = Field(..., description="Minimum margin threshold")


class ProductCreate(ProductBase):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "Wireless Mouse",
                    "cost_price": "8.50",
                    "selling_price": "12.99",
                    "stock_quantity": 120,
                    "supplier_lead_time": 5,
                    "minimum_margin": "2.00",
                }
            ]
        }
    )


class ProductUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    cost_price: Price | None = None
    selling_price: Price | None = None
    stock_quantity: NonNegativeInt | None = None
    supplier_lead_time: PositiveInt | None = None
    minimum_margin: Margin | None = None


class ProductResponse(ProductBase):
    id: UUID
    seller_id: UUID
    created_at: datetime
    pricing_warning: str | None = Field(None, description="Warning when selling price is below cost")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                    "seller_id": "360c1da3-bffc-42c4-97b1-8cf5440700cb",
                    "title": "Wireless Mouse",
                    "cost_price": "8.50",
                    "selling_price": "12.99",
                    "stock_quantity": 120,
                    "supplier_lead_time": 5,
                    "minimum_margin": "2.00",
                    "created_at": "2026-05-19T08:00:00Z",
                    "pricing_warning": None,
                }
            ]
        },
    )


class ProductDetailResponse(BaseModel):
    message: str
    product: ProductResponse

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "message": "Product created successfully.",
                    "product": {
                        "id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                        "seller_id": "360c1da3-bffc-42c4-97b1-8cf5440700cb",
                        "title": "Wireless Mouse",
                        "cost_price": "8.50",
                        "selling_price": "12.99",
                        "stock_quantity": 120,
                        "supplier_lead_time": 5,
                        "minimum_margin": "2.00",
                        "created_at": "2026-05-19T08:00:00Z",
                        "pricing_warning": None,
                    },
                }
            ]
        }
    )


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                            "seller_id": "360c1da3-bffc-42c4-97b1-8cf5440700cb",
                            "title": "Wireless Mouse",
                            "cost_price": "8.50",
                            "selling_price": "12.99",
                            "stock_quantity": 120,
                            "supplier_lead_time": 5,
                            "minimum_margin": "2.00",
                            "created_at": "2026-05-19T08:00:00Z",
                            "pricing_warning": None,
                        }
                    ],
                    "total": 1,
                    "limit": 20,
                    "offset": 0,
                }
            ]
        }
    )


class ProductDeleteResponse(BaseModel):
    message: str

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"message": "Product deleted successfully."}]}
    )
