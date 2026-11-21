from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MARKETPLACE = "Daraz Bangladesh"
SOURCE_STORE = "Bata"


class DemoProductSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marketplace: Literal["Daraz Bangladesh"]
    store_name: Literal["Bata"]
    store_url: str
    listing_url: str
    acquired_at: datetime
    acquisition_method: str = Field(min_length=1, max_length=80)
    validation_status: Literal["VERIFIED_PUBLIC_LISTING"]

    @field_validator("store_url", "listing_url")
    @classmethod
    def validate_daraz_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname not in {
            "daraz.com.bd", "www.daraz.com.bd"
        }:
            raise ValueError("source URL must be an HTTPS Daraz Bangladesh URL")
        return value

    @model_validator(mode="after")
    def validate_listing_shape(self) -> Self:
        if "/products/" not in urlparse(self.listing_url).path:
            raise ValueError("listing_url must identify a Daraz product page")
        if "/shop/bata" not in urlparse(self.store_url).path.rstrip("/").lower():
            raise ValueError("store_url must identify the Bata store")
        return self


class DemoProductListing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_id: str = Field(pattern=r"^[0-9]+$")
    title: str = Field(min_length=3, max_length=255)
    brand: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=120)
    product_type: str = Field(min_length=1, max_length=120)
    audience: Literal["MEN", "WOMEN", "CHILDREN"]
    current_price_bdt: Decimal = Field(gt=0, decimal_places=2)
    original_price_bdt: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    discount_percent: Decimal | None = Field(default=None, ge=0, le=100)
    concise_description: str = Field(min_length=3, max_length=500)
    material: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, max_length=120)
    available_sizes: list[str] | None = None
    specifications: dict[str, str] = Field(default_factory=dict)
    image_url: str | None = None
    availability_status: Literal["IN_STOCK", "OUT_OF_STOCK", "UNKNOWN"]
    price_observed_at: datetime
    missing_fields: list[str]
    source: DemoProductSource

    @field_validator("brand")
    @classmethod
    def normalize_brand(cls, value: str) -> str:
        return value.strip()

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("image_url must use HTTPS")
        return value

    @model_validator(mode="after")
    def validate_identity_and_prices(self) -> Self:
        path = urlparse(self.source.listing_url).path
        if f"i{self.listing_id}.html" not in path:
            raise ValueError("listing_id must match the source listing URL")
        if self.original_price_bdt is not None and self.original_price_bdt < self.current_price_bdt:
            raise ValueError("original price cannot be below the observed current price")
        if self.available_sizes is None and "available_sizes" not in self.missing_fields:
            raise ValueError("unverified sizes must be declared in missing_fields")
        return self


class DemoFootwearManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: Literal["1.0"]
    seed_name: Literal["demo-footwear-store-v1"]
    generated_at: datetime
    currency: Literal["BDT"]
    source_store_url: str
    products: list[DemoProductListing] = Field(min_length=1, max_length=15)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        ids = [item.listing_id for item in self.products]
        urls = [item.source.listing_url for item in self.products]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate Daraz listing IDs are not allowed")
        if len(urls) != len(set(urls)):
            raise ValueError("duplicate Daraz listing URLs are not allowed")
        if any(item.source.store_url != self.source_store_url for item in self.products):
            raise ValueError("all product sources must use the manifest store URL")
        return self
