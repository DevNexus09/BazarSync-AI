from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import random
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash, validate_password
from app.models.demo_seed_record import DemoSeedRecord
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.pricing_policy import PricingObjective, PricingPolicy
from app.models.product import Product, ProductStatus
from app.models.product_price_history import ProductPriceHistory, ProductPriceHistorySource
from app.models.sales_data_coverage import SalesDataCompletenessStatus, SalesDataCoverage
from app.models.sales_record import SalesRecord, SalesRecordPriceSource, SalesRecordStatus
from app.models.seller import Seller
from app.schemas.demo_seed import DemoProductListing, DemoStoreManifest

SEED_NAME = "demo-watch-wise-v1"
DEMO_EMAIL = "bazardemo@gmail.com"
DEMO_PHONE_E164 = "+8801617390260"
DEMO_SHOP_NAME = "Watch Wise - Choice"
CLOCK_CATEGORY = "Table & Alarm Clocks"
# One product deliberately has no fee evidence so MarginGuard shows the missing-evidence path.
FEE_EVIDENCE_WITHHELD_SKUS = frozenset({"WW-002-OLV-2872"})
MARKETPLACE = "Daraz Bangladesh"
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2] / "seed_data" / "demo_watch_wise_products.json"
)
SALES_DAYS = 150
SALES_RANDOM_SEED = 1622


class DemoSeedError(RuntimeError):
    pass


class DemoSeedSafetyError(DemoSeedError):
    pass


class DemoSeedConflictError(DemoSeedError):
    pass


@dataclass(frozen=True)
class InventoryScenario:
    name: str
    on_hand: int
    reserved: int
    incoming: int
    lead_days: int
    safety_stock: int
    minimum_order: int
    pack_size: int
    maximum_stock: int
    age_days: int
    cost_rate: Decimal
    demand_pattern: str


@dataclass
class DemoSeedReport:
    mode: str
    manifest_path: str
    manifest_valid: bool = False
    verified_products: int = 0
    target_products: int = 25
    seller_status: str = "NOT_INSPECTED"
    products_created: int = 0
    products_existing: int = 0
    products_updated: int = 0
    inventory_records_created: int = 0
    pricing_policies_created: int = 0
    fee_policies_created: int = 0
    synthetic_sales_created: int = 0
    synthetic_sales_enabled: bool = False
    skipped_records: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    tables_affected: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SCENARIOS: tuple[InventoryScenario, ...] = (
    InventoryScenario("healthy", 48, 3, 12, 7, 10, 12, 6, 100, 25, Decimal("0.58"), "high"),
    InventoryScenario("healthy", 36, 2, 0, 8, 8, 12, 6, 80, 35, Decimal("0.61"), "medium"),
    InventoryScenario("low", 8, 2, 12, 12, 8, 12, 6, 70, 55, Decimal("0.64"), "increasing"),
    InventoryScenario("near_stockout", 3, 1, 0, 10, 6, 12, 6, 60, 70, Decimal("0.66"), "medium"),
    InventoryScenario("out_of_stock", 0, 0, 18, 14, 8, 18, 6, 70, 90, Decimal("0.62"), "intermittent"),
    InventoryScenario("slow_moving", 42, 4, 0, 9, 6, 12, 6, 90, 115, Decimal("0.67"), "low"),
    InventoryScenario("recently_stocked", 60, 5, 0, 6, 10, 12, 6, 110, 8, Decimal("0.57"), "increasing"),
    InventoryScenario("potential_dead_stock", 75, 0, 0, 10, 6, 12, 6, 100, 190, Decimal("0.69"), "zero"),
    InventoryScenario("healthy", 32, 3, 6, 8, 8, 12, 6, 75, 45, Decimal("0.60"), "seasonal"),
    InventoryScenario("slow_moving", 50, 2, 0, 11, 7, 12, 6, 90, 130, Decimal("0.68"), "declining"),
    InventoryScenario("low", 10, 3, 12, 13, 9, 12, 6, 75, 60, Decimal("0.63"), "high"),
    InventoryScenario("near_stockout", 4, 1, 12, 15, 8, 12, 6, 65, 80, Decimal("0.65"), "intermittent"),
    InventoryScenario("healthy", 28, 2, 0, 7, 7, 12, 6, 70, 30, Decimal("0.59"), "medium"),
    InventoryScenario("potential_dead_stock", 66, 1, 0, 12, 6, 12, 6, 90, 210, Decimal("0.70"), "zero"),
    InventoryScenario("recently_stocked", 40, 4, 6, 6, 8, 12, 6, 85, 12, Decimal("0.56"), "seasonal"),
)


def load_demo_manifest(path: Path = DEFAULT_MANIFEST) -> DemoStoreManifest:
    return DemoStoreManifest.model_validate_json(path.read_text(encoding="utf-8"))


def assert_safe_seed_environment(*, apply: bool) -> None:
    if settings.env not in {"development", "test"}:
        raise DemoSeedSafetyError(
            "Demo seeding is restricted to development and test environments."
        )
    parsed = urlparse(settings.database_url.replace("postgresql+psycopg2", "postgresql"))
    host = (parsed.hostname or "").casefold()
    if apply and host not in {"", "localhost", "127.0.0.1", "::1"}:
        raise DemoSeedSafetyError(
            "Demo seeding refuses writes to non-local databases; no production override exists."
        )


class DemoStoreSeedService:
    def __init__(self, db: Session, *, now: datetime | None = None) -> None:
        self._db = db
        self._now = _ensure_utc(now or datetime.now(timezone.utc))

    def run(
        self,
        *,
        manifest: DemoStoreManifest,
        manifest_path: Path,
        apply: bool,
        password: str | None,
        with_synthetic_sales: bool = False,
        update_managed_records: bool = False,
    ) -> DemoSeedReport:
        assert_safe_seed_environment(apply=apply)
        report = DemoSeedReport(
            mode="APPLY" if apply else "DRY_RUN",
            manifest_path=str(manifest_path),
            manifest_valid=True,
            verified_products=len(manifest.products),
            synthetic_sales_enabled=with_synthetic_sales,
            categories=sorted({item.category for item in manifest.products}),
        )
        if len(manifest.products) < report.target_products:
            report.warnings.append(
                f"Verified listing shortfall: {len(manifest.products)} of {report.target_products}."
            )

        if not apply:
            self._inspect_dry_run(manifest, report)
            return report

        try:
            with self._db.begin():
                seller, created = self._resolve_seller(password=password)
                report.seller_status = "CREATED" if created else "EXISTING_MANAGED"
                for index, listing in enumerate(manifest.products):
                    scenario = SCENARIOS[index % len(SCENARIOS)]
                    product, state = self._upsert_product(
                        seller=seller,
                        listing=listing,
                        scenario=scenario,
                        update_managed_records=update_managed_records,
                    )
                    if state == "CREATED":
                        report.products_created += 1
                        self._create_supporting_records(
                            seller=seller,
                            product=product,
                            listing=listing,
                            scenario=scenario,
                            report=report,
                        )
                    elif state == "UPDATED":
                        report.products_updated += 1
                        self._update_managed_product(product, listing, scenario)
                    else:
                        report.products_existing += 1
                        report.skipped_records += 1

                    if with_synthetic_sales:
                        report.synthetic_sales_created += self._create_synthetic_sales(
                            seller=seller,
                            product=product,
                            listing=listing,
                            scenario=scenario,
                            product_index=index,
                        )
                if report.seller_status == "CREATED" or report.products_created:
                    report.tables_affected.extend(
                        [
                            "sellers", "products", "demo_seed_records",
                            "inventory_history", "pricing_policies",
                            "marketplace_fee_policies", "product_price_history",
                        ]
                    )
                elif report.products_updated:
                    report.tables_affected.extend(["products", "demo_seed_records"])
                if report.synthetic_sales_created:
                    for table in ("sales_records", "sales_data_coverage", "demo_seed_records"):
                        if table not in report.tables_affected:
                            report.tables_affected.append(table)
        except Exception:
            self._db.rollback()
            raise
        return report

    def _inspect_dry_run(
        self, manifest: DemoStoreManifest, report: DemoSeedReport
    ) -> None:
        seller = self._seller_by_email()
        if seller is None:
            report.seller_status = "WOULD_CREATE"
            report.products_created = len(manifest.products)
            return
        if not self._managed("SELLER", DEMO_EMAIL, entity_id=seller.id):
            raise DemoSeedConflictError(
                f"{DEMO_EMAIL} exists but is not owned by this seed system."
            )
        report.seller_status = "EXISTING_MANAGED"
        for item in manifest.products:
            marker = self._marker("PRODUCT", item.listing_id)
            if marker is None:
                report.products_created += 1
            else:
                product = self._db.get(Product, marker.entity_id)
                if product is None or product.seller_id != seller.id:
                    raise DemoSeedConflictError(
                        f"Managed product marker is invalid for listing {item.listing_id}."
                    )
                report.products_existing += 1

    def _resolve_seller(self, *, password: str | None) -> tuple[Seller, bool]:
        seller = self._seller_by_email()
        if seller is not None:
            if not self._managed("SELLER", DEMO_EMAIL, entity_id=seller.id):
                raise DemoSeedConflictError(
                    f"{DEMO_EMAIL} exists but was not created by this seed system; aborting."
                )
            return seller, False
        if not password:
            raise DemoSeedSafetyError(
                "DEMO_SELLER_PASSWORD is required to create the demo account."
            )
        validate_password(password)
        seller = Seller(
            email=DEMO_EMAIL,
            password_hash=get_password_hash(password),
            phone=DEMO_PHONE_E164,
            full_name=DEMO_SHOP_NAME,
            business_name=DEMO_SHOP_NAME,
            industry="Watches & Clocks",
            website="https://www.daraz.com.bd/blzdnq-selection/",
            address_line="Mirpur 10",
            city="Dhaka",
            country="Bangladesh",
        )
        self._db.add(seller)
        self._db.flush()
        self._mark(
            seller=seller,
            record_type="SELLER",
            external_key=DEMO_EMAIL,
            entity_id=seller.id,
            provenance={
                "synthetic_demo_business": True,
                "business_category": "Watches & Clocks",
                "currency": "BDT",
                "marketplace_reference": MARKETPLACE,
                "independent_from_reference_retailer": True,
            },
        )
        return seller, True

    def _upsert_product(
        self,
        *,
        seller: Seller,
        listing: DemoProductListing,
        scenario: InventoryScenario,
        update_managed_records: bool,
    ) -> tuple[Product, str]:
        marker = self._marker("PRODUCT", listing.listing_id)
        sku = listing.sku
        if marker is not None:
            product = self._db.get(Product, marker.entity_id)
            if product is None or product.seller_id != seller.id or product.sku != sku:
                raise DemoSeedConflictError(
                    f"Managed product ownership mismatch for listing {listing.listing_id}."
                )
            return product, "UPDATED" if update_managed_records else "EXISTING"
        conflict = self._db.execute(
            select(Product).where(Product.seller_id == seller.id, Product.sku == sku)
        ).scalar_one_or_none()
        if conflict is not None:
            raise DemoSeedConflictError(
                f"SKU {sku} exists without a demo ownership marker."
            )
        product = Product(
            seller_id=seller.id,
            title=listing.title,
            sku=sku,
            status=ProductStatus.ACTIVE,
            description=listing.concise_description,
            category=listing.category,
            specifications=self._product_specs(listing, scenario),
            searchable_text=f"{listing.title} {listing.brand} {listing.category} {listing.product_type}",
            cost_price=_money(listing.current_price_bdt * scenario.cost_rate),
            selling_price=_money(listing.current_price_bdt),
            stock_quantity=scenario.on_hand,
            supplier_lead_time=scenario.lead_days,
            minimum_margin=Decimal("12.00"),
        )
        self._db.add(product)
        self._db.flush()
        self._mark(
            seller=seller,
            record_type="PRODUCT",
            external_key=listing.listing_id,
            entity_id=product.id,
            provenance={
                "source_listing_url": listing.source.listing_url,
                "source_store": listing.source.store_name,
                "marketplace_reference_only": True,
                "synthetic_demo_business_fields": [
                    "cost_price", "stock_quantity", "supplier_lead_time", "minimum_margin"
                ],
            },
        )
        return product, "CREATED"

    def _create_supporting_records(
        self,
        *,
        seller: Seller,
        product: Product,
        listing: DemoProductListing,
        scenario: InventoryScenario,
        report: DemoSeedReport,
    ) -> None:
        business_date = self._now.astimezone(timezone(timedelta(hours=6))).date()
        available = scenario.on_hand - scenario.reserved
        inventory = InventoryHistory(
            seller_id=seller.id,
            product_id=product.id,
            snapshot_date=business_date,
            captured_at=self._now,
            quantity_on_hand=scenario.on_hand,
            quantity_reserved=scenario.reserved,
            quantity_available=available,
            quantity_incoming=scenario.incoming,
            source=InventorySnapshotSource.MANUAL_ADJUSTMENT,
            source_reference=f"{SEED_NAME}:inventory:{listing.listing_id}:{business_date}",
            content_hash=_content_hash(
                seller.id, product.id, business_date, scenario.on_hand,
                scenario.reserved, scenario.incoming
            ),
        )
        self._db.add(inventory)
        self._db.flush()
        report.inventory_records_created += 1

        # Receipts (purchase orders) and aging are seeded by the comprehensive stage.

        minimum_allowed = _money(product.cost_price / Decimal("0.78"))
        pricing = PricingPolicy(
            seller_id=seller.id,
            product_id=product.id,
            marketplace=MARKETPLACE,
            currency="BDT",
            minimum_margin_rate=Decimal("0.12"),
            minimum_unit_profit=Decimal("10.00"),
            maximum_price_decrease_rate=Decimal("0.15"),
            maximum_price_increase_rate=Decimal("0.20"),
            minimum_allowed_price=minimum_allowed,
            maximum_allowed_price=_money(product.selling_price * Decimal("1.35")),
            price_increment=Decimal("1.00"),
            recommendation_cooldown_hours=24,
            objective=(
                PricingObjective.CLEAR_EXCESS_STOCK
                if scenario.name in {"slow_moving", "potential_dead_stock"}
                else PricingObjective.MAXIMIZE_EXPECTED_PROFIT
            ),
            is_active=True,
            effective_from=self._now - timedelta(days=150),
        )
        self._db.add(pricing)
        report.pricing_policies_created += 1

        fee = self._fee_policy(seller=seller, product=product)
        if fee is not None:
            report.fee_policies_created += 1

        price_history = ProductPriceHistory(
            seller_id=seller.id,
            product_id=product.id,
            listing_id=None,
            marketplace=MARKETPLACE,
            old_price=None,
            new_price=product.selling_price,
            currency="BDT",
            reason=(
                "Opening price matches the public Watch Wise - Choice listing on Daraz; "
                "demo account, not a seller-authorized marketplace listing."
            ),
            source=ProductPriceHistorySource.IMPORT,
            changed_at=listing.price_observed_at,
        )
        self._db.add(price_history)

        self._db.flush()

        self._mark(seller, "INVENTORY", listing.listing_id, inventory.id, {"synthetic": True})
        self._mark(seller, "PRICING_POLICY", listing.listing_id, pricing.id, {"synthetic": True})
        if fee is not None:
            self._mark(seller, "FEE_POLICY", listing.listing_id, fee.id, {"synthetic": True})

    def _fee_policy(self, *, seller: Seller, product: Product) -> MarketplaceFeePolicy | None:
        """Daraz-style fees: product-level for watches, one shared category policy for clocks."""
        if product.sku in FEE_EVIDENCE_WITHHELD_SKUS:
            return None
        is_clock = product.category == CLOCK_CATEGORY
        if is_clock and self._db.execute(
            select(MarketplaceFeePolicy.id).where(
                MarketplaceFeePolicy.seller_id == seller.id,
                MarketplaceFeePolicy.product_id.is_(None),
                MarketplaceFeePolicy.category == CLOCK_CATEGORY,
            )
        ).first():
            return None
        fee = MarketplaceFeePolicy(
            seller_id=seller.id,
            product_id=None if is_clock else product.id,
            marketplace=MARKETPLACE,
            category=CLOCK_CATEGORY if is_clock else None,
            currency="BDT",
            percentage_commission_rate=Decimal("0.120000") if is_clock else Decimal("0.100000"),
            payment_fee_rate=Decimal("0.015000"),
            fixed_per_order_fee=Decimal("0.00"),
            fixed_per_unit_fee=Decimal("5.00"),
            fulfilment_fee=Decimal("0.00"),
            shipping_subsidy=Decimal("0.00"),
            other_variable_cost=Decimal("3.00"),
            source="SELLER_ENTERED",
            version="2026-07",
            is_active=True,
            effective_from=self._now - timedelta(days=150),
        )
        self._db.add(fee)
        return fee

    def _create_synthetic_sales(
        self,
        *,
        seller: Seller,
        product: Product,
        listing: DemoProductListing,
        scenario: InventoryScenario,
        product_index: int,
    ) -> int:
        if self._marker("SALES_BATCH", listing.listing_id) is not None:
            return 0
        end_date = self._now.astimezone(timezone(timedelta(hours=6))).date() - timedelta(days=1)
        start_date = end_date - timedelta(days=SALES_DAYS - 1)
        rng = random.Random(SALES_RANDOM_SEED + product_index)
        sales: list[tuple[date, int]] = []
        for offset in range(SALES_DAYS):
            day = start_date + timedelta(days=offset)
            quantity = _daily_quantity(
                scenario.demand_pattern, offset, SALES_DAYS, rng
            )
            if quantity > 0:
                sales.append((day, quantity))

        for sale_date, quantity in sales:
            sold_at = datetime.combine(sale_date, time(hour=12), tzinfo=timezone(timedelta(hours=6))).astimezone(timezone.utc)
            self._db.add(
                SalesRecord(
                    seller_id=seller.id,
                    product_id=product.id,
                    source_reference=f"{SEED_NAME}:sale:{listing.listing_id}:{sale_date}",
                    status=SalesRecordStatus.COMPLETED,
                    sold_at=sold_at,
                    quantity_sold=quantity,
                    unit_price=product.selling_price,
                    line_total=_money(product.selling_price * quantity),
                    currency="BDT",
                    marketplace_listing_id=None,
                    price_source=SalesRecordPriceSource.IMPORTED_TRANSACTION,
                    returned_units=0,
                    refunded_restocked_units=0,
                    # These rows are visible to the demo seller's operational analytics.
                    # Their coverage/source markers keep them distinct from real orders,
                    # and the historical dataset service blocks them from ML labels.
                    is_test_order=False,
                )
            )

        coverage = SalesDataCoverage(
            seller_id=seller.id,
            # Product-wide declaration: marketplace-scoped coverage cannot prove
            # that a zero-sales day is complete across every seller channel.
            marketplace=None,
            product_id=product.id,
            source="SYNTHETIC_DEMO_SEED",
            # Coverage dates are UTC calendar dates intersecting each Dhaka
            # business day, matching SalesImportService/HistoricalDatasetService.
            coverage_start_date=start_date - timedelta(days=1),
            coverage_end_date=end_date + timedelta(days=1),
            completeness_status=SalesDataCompletenessStatus.COMPLETE,
            imported_record_count=len(sales),
            valid_sales_count=len(sales),
            invalid_or_excluded_count=0,
            last_imported_at=self._now,
            notes=(
                "Deterministic synthetic demo sales; not actual Daraz transactions "
                f"(pattern={scenario.demand_pattern}, seed={SALES_RANDOM_SEED + product_index})."
            ),
        )
        self._db.add(coverage)
        self._db.flush()
        self._mark(
            seller, "SALES_BATCH", listing.listing_id, coverage.id,
            {"synthetic": True, "pattern": scenario.demand_pattern, "days": SALES_DAYS},
        )
        return len(sales)

    def _update_managed_product(
        self, product: Product, listing: DemoProductListing, scenario: InventoryScenario
    ) -> None:
        product.title = listing.title
        product.description = listing.concise_description
        product.category = listing.category
        product.specifications = self._product_specs(listing, scenario)
        product.cost_price = _money(listing.current_price_bdt * scenario.cost_rate)
        product.selling_price = _money(listing.current_price_bdt)
        product.stock_quantity = scenario.on_hand
        product.supplier_lead_time = scenario.lead_days

    @staticmethod
    def _product_specs(
        listing: DemoProductListing, scenario: InventoryScenario
    ) -> dict[str, str]:
        specs = dict(listing.specifications)
        specs.update(
            {
                "brand": listing.brand,
                "product_type": listing.product_type,
                "audience": listing.audience,
                "source_marketplace": MARKETPLACE,
                "source_store": listing.source.store_name,
                "source_listing_id": listing.listing_id,
                "source_listing_url": listing.source.listing_url,
                "source_observed_price_bdt": str(listing.current_price_bdt),
                "source_price_observed_at": listing.price_observed_at.isoformat(),
                "source_validation_status": listing.source.validation_status,
                "source_missing_fields": ",".join(listing.missing_fields),
                "market_reference_only": "true",
                "demo_data_class": "SYNTHETIC_DEMO_BUSINESS_DATA",
                "inventory_scenario": scenario.name,
                "quantity_reserved": str(scenario.reserved),
                "quantity_incoming_unconfirmed": str(scenario.incoming),
                "safety_stock": str(scenario.safety_stock),
                "minimum_order_quantity": str(scenario.minimum_order),
                "pack_size": str(scenario.pack_size),
                "maximum_stock": str(scenario.maximum_stock),
                "holding_cost_bdt_per_unit_per_day": "0.50",
                "demo_demand_pattern": scenario.demand_pattern,
                "image_url": listing.image_url or "",
            }
        )
        if listing.material:
            specs["material"] = listing.material
        if listing.color:
            specs["color"] = listing.color
        return specs

    def _seller_by_email(self) -> Seller | None:
        return self._db.execute(
            select(Seller).where(func.lower(Seller.email) == DEMO_EMAIL)
        ).scalar_one_or_none()

    def _managed(self, record_type: str, external_key: str, *, entity_id: UUID) -> bool:
        marker = self._marker(record_type, external_key)
        return marker is not None and marker.entity_id == entity_id

    def _marker(self, record_type: str, external_key: str) -> DemoSeedRecord | None:
        return self._db.execute(
            select(DemoSeedRecord).where(
                DemoSeedRecord.seed_name == SEED_NAME,
                DemoSeedRecord.record_type == record_type,
                DemoSeedRecord.external_key == external_key,
            )
        ).scalar_one_or_none()

    def _mark(
        self,
        seller: Seller,
        record_type: str,
        external_key: str,
        entity_id: UUID,
        provenance: dict[str, object],
    ) -> None:
        self._db.add(
            DemoSeedRecord(
                seed_name=SEED_NAME,
                record_type=record_type,
                external_key=external_key,
                entity_id=entity_id,
                seller_id=seller.id,
                provenance=provenance,
            )
        )


def _daily_quantity(
    pattern: str, offset: int, total_days: int, rng: random.Random
) -> int:
    progress = Decimal(offset) / Decimal(max(1, total_days - 1))
    if pattern == "high":
        return 2 if rng.random() < 0.65 else 1
    if pattern == "medium":
        return 1 if rng.random() < 0.55 else 0
    if pattern == "low":
        return 1 if rng.random() < 0.12 else 0
    if pattern == "intermittent":
        return rng.choice((1, 1, 2)) if rng.random() < 0.08 else 0
    if pattern == "declining":
        return 1 if rng.random() < float(Decimal("0.75") - progress * Decimal("0.65")) else 0
    if pattern == "increasing":
        return 1 if rng.random() < float(Decimal("0.10") + progress * Decimal("0.70")) else 0
    if pattern == "seasonal":
        return 2 if offset % 30 in {0, 1, 2, 3} else (1 if rng.random() < 0.25 else 0)
    return 0


def _content_hash(
    seller_id: UUID,
    product_id: UUID,
    snapshot_date: date,
    on_hand: int,
    reserved: int,
    incoming: int,
) -> str:
    payload = json.dumps(
        [str(seller_id), str(product_id), snapshot_date.isoformat(), on_hand, reserved, incoming, SEED_NAME],
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _money(value: Decimal | int) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
