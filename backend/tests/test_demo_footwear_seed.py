from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import verify_password
from app.models.demo_seed_record import DemoSeedRecord
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.inventory_stock_in import InventoryStockIn
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.pricing_policy import PricingPolicy
from app.models.product import Product, ProductMarketplaceListing
from app.models.product_price_history import ProductPriceHistory
from app.models.sales_data_coverage import SalesDataCoverage
from app.models.sales_record import SalesRecord
from app.models.seller import Seller
from app.schemas.demo_seed import DemoFootwearManifest
from app.schemas.auth import SellerLogin
from app.services.auth_service import AuthService
from app.services.demo_seed_service import (
    DEFAULT_MANIFEST,
    DEMO_EMAIL,
    DemoFootwearSeedService,
    DemoSeedConflictError,
    DemoSeedSafetyError,
    load_demo_manifest,
)
from app.services.margin_guard import MarginGuard
from app.services.historical_dataset_service import HistoricalDatasetService
from app.services.reorder_recommendation_service import ReorderRecommendationService
from app.services.sales_velocity_service import SalesVelocityService

pytest_plugins = ("test_recommendation_evidence",)


@pytest.fixture
def seed_db(db, monkeypatch):
    with db() as session:
        Product.metadata.create_all(
            session.get_bind(),
            tables=[
                DemoSeedRecord.__table__,
                ProductMarketplaceListing.__table__,
                InventoryStockIn.__table__,
                InventoryAgingSnapshot.__table__,
                ProductPriceHistory.__table__,
            ],
        )
    monkeypatch.setattr(settings, "env", "test")
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg2:///fixture")
    return db


def _manifest() -> DemoFootwearManifest:
    return load_demo_manifest(DEFAULT_MANIFEST)


def _run(seed_db, *, sales=False):
    with seed_db() as session:
        return DemoFootwearSeedService(
            session, now=datetime.now(timezone.utc) - timedelta(minutes=1)
        ).run(
            manifest=_manifest(),
            manifest_path=DEFAULT_MANIFEST,
            apply=True,
            password="local-demo-password",
            with_synthetic_sales=sales,
        )


def test_manifest_has_15_distinct_verified_bata_store_listings():
    manifest = _manifest()
    assert len(manifest.products) == 15
    assert len({item.listing_id for item in manifest.products}) == 15
    assert {item.source.store_name for item in manifest.products} == {"Bata"}
    assert {item.audience for item in manifest.products} == {"MEN", "WOMEN", "CHILDREN"}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["products"].append(dict(data["products"][0])),
        lambda data: data["products"][0].update(current_price_bdt="-1"),
        lambda data: data["products"][0]["source"].update(store_name="Other Seller"),
        lambda data: data["products"][0]["source"].update(listing_url=""),
    ],
)
def test_manifest_rejects_duplicate_invalid_price_wrong_seller_and_missing_source(mutation):
    data = _manifest().model_dump(mode="json")
    mutation(data)
    with pytest.raises(ValidationError):
        DemoFootwearManifest.model_validate(data)


def test_dry_run_makes_no_database_changes(seed_db):
    with seed_db() as session:
        report = DemoFootwearSeedService(session).run(
            manifest=_manifest(),
            manifest_path=DEFAULT_MANIFEST,
            apply=False,
            password=None,
        )
        assert report.seller_status == "WOULD_CREATE"
        assert session.scalar(select(func.count()).select_from(Seller)) == 0
        assert session.scalar(select(func.count()).select_from(Product)) == 0


def test_seed_creates_login_compatible_isolated_records_and_safe_margins(seed_db):
    report = _run(seed_db)
    assert report.seller_status == "CREATED"
    assert report.products_created == 15
    assert report.inventory_records_created == 15
    assert report.synthetic_sales_created == 0

    with seed_db() as session:
        seller = session.scalar(select(Seller).where(Seller.email == DEMO_EMAIL))
        assert seller is not None
        assert seller.phone == "+8801870211787"
        assert verify_password("local-demo-password", seller.password_hash)
        assert AuthService(session).authenticate_seller(
            SellerLogin(email=DEMO_EMAIL, password="local-demo-password")
        ).id == seller.id
        products = session.scalars(
            select(Product).where(Product.seller_id == seller.id).order_by(Product.sku)
        ).all()
        assert len(products) == 15
        assert all(product.selling_price > 0 and product.cost_price > 0 for product in products)
        assert session.scalar(select(func.count()).select_from(InventoryHistory)) == 15
        assert session.scalar(select(func.count()).select_from(InventoryAgingSnapshot)) == 15
        assert session.scalar(select(func.count()).select_from(PricingPolicy)) == 15
        assert session.scalar(select(func.count()).select_from(MarketplaceFeePolicy)) == 15
        snapshots = session.scalars(select(InventoryHistory)).all()
        assert all(row.quantity_available == row.quantity_on_hand - row.quantity_reserved for row in snapshots)
        for product in products:
            guard = MarginGuard(session).validate_candidate(
                seller_id=seller.id,
                product=product,
                candidate_price=Decimal(product.selling_price),
            )
            assert guard.is_allowed, guard.rejection_reasons


def test_rerun_is_idempotent_and_does_not_reset_password(seed_db):
    _run(seed_db)
    with seed_db.begin() as session:
        seller = session.scalar(select(Seller).where(Seller.email == DEMO_EMAIL))
        original_hash = seller.password_hash
    second = _run(seed_db)
    assert second.products_created == 0
    assert second.products_existing == 15
    with seed_db() as session:
        seller = session.scalar(select(Seller).where(Seller.email == DEMO_EMAIL))
        assert seller.password_hash == original_hash
        assert session.scalar(select(func.count()).select_from(Product)) == 15
        assert session.scalar(select(func.count()).select_from(InventoryHistory)) == 15


def test_conflicting_normal_account_aborts_without_modification(seed_db):
    with seed_db.begin() as session:
        seller = Seller(email=DEMO_EMAIL, password_hash="ordinary-account")
        session.add(seller)
    with seed_db() as session:
        with pytest.raises(DemoSeedConflictError):
            DemoFootwearSeedService(session).run(
                manifest=_manifest(),
                manifest_path=DEFAULT_MANIFEST,
                apply=True,
                password="local-demo-password",
            )
    with seed_db() as session:
        assert session.scalar(select(func.count()).select_from(Product)) == 0
        assert session.scalar(select(func.count()).select_from(DemoSeedRecord)) == 0


def test_optional_sales_are_reproducible_idempotent_and_seller_scoped(seed_db):
    first = _run(seed_db, sales=True)
    assert first.synthetic_sales_created > 0
    with seed_db() as session:
        seller = session.scalar(select(Seller).where(Seller.email == DEMO_EMAIL))
        rows = session.scalars(select(SalesRecord).order_by(SalesRecord.source_reference)).all()
        fingerprint = [
            (row.source_reference, row.quantity_sold, row.unit_price, row.line_total)
            for row in rows
        ]
        assert all(row.seller_id == seller.id and not row.is_test_order for row in rows)
        assert all(row.line_total == row.unit_price * row.quantity_sold for row in rows)
        assert all(row.sold_at <= datetime.now(timezone.utc) for row in rows)
        assert session.scalar(select(func.count()).select_from(SalesDataCoverage)) == 15
    second = _run(seed_db, sales=True)
    assert second.synthetic_sales_created == 0
    with seed_db() as session:
        rows = session.scalars(select(SalesRecord).order_by(SalesRecord.source_reference)).all()
        assert fingerprint == [
            (row.source_reference, row.quantity_sold, row.unit_price, row.line_total)
            for row in rows
        ]


def test_synthetic_sales_support_operations_but_are_blocked_from_ml_labels(seed_db):
    _run(seed_db, sales=True)
    with seed_db() as session:
        seller = session.scalar(select(Seller).where(Seller.email == DEMO_EMAIL))
        product = session.scalar(
            select(Product)
            .where(Product.seller_id == seller.id)
            .order_by(Product.sku)
        )
        inventory = session.scalar(
            select(InventoryHistory).where(InventoryHistory.product_id == product.id)
        )
        as_of = SalesVelocityService.business_date_for_seller(
            seller, datetime.now(timezone.utc)
        )
        velocity = SalesVelocityService(session).measure_for_product(
            product=product, seller=seller, as_of_date=as_of, window_days=30
        )
        assert velocity.daily_sales_rate > 0
        reorder = ReorderRecommendationService(session).build_recommendation(
            product=product,
            seller=seller,
            inventory_snapshot=inventory,
            sales_velocity=velocity,
            stockout_prediction=None,
            as_of_date=as_of,
            generated_at=datetime.now(timezone.utc),
            calculation_version="demo-compat-v1",
        )
        assert reorder.recommended_quantity >= 0

        dataset = HistoricalDatasetService(
            session, authorized_seller_id=seller.id
        ).build(
            start_date=as_of - timedelta(days=7),
            end_date=as_of - timedelta(days=1),
            as_of=datetime.now(timezone.utc),
            product_id=product.id,
        )
        assert any("SYNTHETIC_DEMO_SALES" in row.data_quality_flags for row in dataset.rows)
        assert not any(row.forecast_label_eligible for row in dataset.rows)


def test_production_and_remote_database_writes_are_refused(seed_db, monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    with seed_db() as session, pytest.raises(DemoSeedSafetyError):
        DemoFootwearSeedService(session).run(
            manifest=_manifest(), manifest_path=Path("manifest.json"),
            apply=True, password="local-demo-password",
        )
    monkeypatch.setattr(settings, "env", "development")
    monkeypatch.setattr(settings, "database_url", "postgresql://db.example.com/bazarsync")
    with seed_db() as session, pytest.raises(DemoSeedSafetyError):
        DemoFootwearSeedService(session).run(
            manifest=_manifest(), manifest_path=Path("manifest.json"),
            apply=True, password="local-demo-password",
        )
