"""Fill the demo seller's data gaps the Copilot needs: listings + ratings, buyer/district on sales,
search visibility, expenses and supplier bills, and the store scorecard.

Only demo1@gmail.com is touched. Re-running is safe: every created row is tracked in
demo_seed_records (seed "demo-copilot-extras-v1") and skipped when it already exists; sales rows
only get customer/district filled where those columns are still NULL. Values are deterministic.

    python scripts/seed_copilot_demo_extras.py            # dry run: report what would change
    python scripts/seed_copilot_demo_extras.py --apply
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.business_finance import BusinessExpense, BusinessExpenseStatus, BusinessExpenseType, MarketplaceStoreMetric  # noqa: E402
from app.models.demo_seed_record import DemoSeedRecord  # noqa: E402
from app.models.inventory_stock_in import InventoryStockIn  # noqa: E402
from app.models.product import Product, ProductMarketplaceListing, ProductMarketplaceListingStatus  # noqa: E402
from app.models.product_visibility_metric import ProductVisibilityMetric  # noqa: E402
from app.models.sales_record import SalesRecord  # noqa: E402
from app.models.seller import Seller  # noqa: E402

SEED = "demo-copilot-extras-v1"
EMAIL = "demo1@gmail.com"
MARKETPLACE = "Daraz Bangladesh"
DHAKA = ZoneInfo("Asia/Dhaka")
SUPPLIER = "Bata Bangladesh Distributor (demo)"
# Delivery districts weighted roughly like a Dhaka-based footwear shop.
DISTRICTS = (("Dhaka", 38), ("Chattogram", 14), ("Gazipur", 10), ("Narayanganj", 8), ("Sylhet", 7), ("Khulna", 6), ("Rajshahi", 6), ("Cumilla", 5), ("Rangpur", 3), ("Barishal", 3))
CUSTOMER_POOL = 520
# Ratings by SKU suffix; three listings are deliberately weak so "low rating" questions have an answer.
LOW_RATED = {"DEMO-BATA-351440540": (Decimal("3.40"), 12), "DEMO-BATA-557618536": (Decimal("3.60"), 5), "DEMO-BATA-1575185161": (Decimal("3.80"), 21)}


def _unit(*parts: object) -> float:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16) / float(16**12)


def _weighted(pick: float, table: tuple[tuple[str, int], ...]) -> str:
    total = sum(weight for _, weight in table)
    running = 0.0
    for value, weight in table:
        running += weight / total
        if pick < running:
            return value
    return table[-1][0]


class Seeder:
    def __init__(self, session, seller: Seller, *, apply: bool, as_of: date) -> None:
        self.db, self.seller, self.apply, self.as_of = session, seller, apply, as_of
        self.report: dict[str, int] = defaultdict(int)
        existing = self.db.execute(select(DemoSeedRecord.record_type, DemoSeedRecord.external_key).where(DemoSeedRecord.seed_name == SEED)).all()
        self.seen = {(row[0], row[1]) for row in existing}

    def _create(self, record_type: str, key: str, row) -> None:
        if (record_type, key) in self.seen:
            self.report[f"{record_type}_kept"] += 1
            return
        self.report[f"{record_type}_created"] += 1
        if not self.apply:
            return
        self.db.add(row)
        self.db.flush()
        self.db.add(DemoSeedRecord(seed_name=SEED, record_type=record_type, external_key=key, entity_id=row.id, seller_id=self.seller.id, provenance={"script": "seed_copilot_demo_extras.py", "synthetic": True}))
        self.seen.add((record_type, key))

    def run(self) -> dict[str, int]:
        products = self.db.execute(select(Product).where(Product.seller_id == self.seller.id).order_by(Product.sku)).scalars().all()
        self.listings(products)
        self.visibility(products)
        self.sales_buyers()
        self.expenses()
        self.store_metric()
        if self.apply:
            self.db.commit()
        return dict(self.report)

    def listings(self, products: list[Product]) -> None:
        for product in products:
            sku = product.sku or str(product.id)
            rating, reviews = LOW_RATED.get(sku, (Decimal(str(round(4.1 + 0.8 * _unit(sku, "rating"), 1))), 18 + int(160 * _unit(sku, "reviews"))))
            self._create("LISTING", sku, ProductMarketplaceListing(
                seller_id=self.seller.id, product_id=product.id, marketplace=MARKETPLACE,
                marketplace_listing_id=f"DRZ-{sku}", listing_url=f"https://www.daraz.com.bd/products/demo-{sku.lower()}.html",
                listing_status=ProductMarketplaceListingStatus.OUT_OF_STOCK if (product.stock_quantity or 0) == 0 else ProductMarketplaceListingStatus.ACTIVE,
                currency="BDT", selling_price=product.selling_price, category_on_marketplace=product.category, title_on_marketplace=product.title,
                is_primary=True, rating=rating, review_count=reviews,
                published_at=datetime(2026, 6, 15, 12, tzinfo=DHAKA), last_synced_at=datetime.combine(self.as_of, time(9), tzinfo=DHAKA),
            ))

    def visibility(self, products: list[Product]) -> None:
        for offset in (7, 0):
            metric_date = self.as_of - timedelta(days=offset + 1)
            for product in products:
                pick = _unit(product.sku, metric_date)
                impressions = 800 + int(4200 * pick)
                views = int(impressions * (0.06 + 0.06 * _unit(product.sku, "ctr")))
                self._create("VISIBILITY", f"{product.sku}:{metric_date}", ProductVisibilityMetric(
                    seller_id=self.seller.id, product_id=product.id, marketplace=MARKETPLACE, metric_date=metric_date,
                    impressions=impressions, views=views, clicks=int(views * 0.4), search_rank=1 + int(45 * _unit(product.sku, "rank", offset)),
                    listing_quality_score=Decimal(str(round(62 + 33 * _unit(product.sku, "quality"), 2))),
                    conversion_rate=Decimal(str(round(0.015 + 0.03 * _unit(product.sku, "cvr", offset), 6))), source=SEED,
                ))

    def sales_buyers(self) -> None:
        rows = self.db.execute(select(SalesRecord).where(SalesRecord.seller_id == self.seller.id, SalesRecord.customer_reference.is_(None))).scalars().all()
        for row in rows:
            # Squaring the pick skews buyers toward low ids, so some customers order repeatedly.
            customer = int(CUSTOMER_POOL * _unit(row.id, "buyer") ** 2)
            self.report["SALES_BUYER_filled"] += 1
            if self.apply:
                row.customer_reference = f"DRZ-BUYER-{customer:04d}"
                row.delivery_district = row.delivery_district or _weighted(_unit(row.id, "district"), DISTRICTS)

    def expenses(self) -> None:
        month = date(2026, 7, 1)
        while month <= self.as_of:
            month_end = min((month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), self.as_of)
            for kind, base, counterparty in ((BusinessExpenseType.ADVERTISING, 9000, "Daraz Sponsored Solutions"), (BusinessExpenseType.SHIPPING, 14000, "Daraz Logistics"), (BusinessExpenseType.PACKAGING, 3500, "Local packaging supplier")):
                amount = Decimal(base + int(base * 0.3 * _unit(kind.value, month))).quantize(Decimal("1"))
                paid = month_end < self.as_of.replace(day=1)
                self._create("EXPENSE", f"{kind.value}:{month:%Y-%m}", BusinessExpense(
                    seller_id=self.seller.id, expense_type=kind, amount=amount, currency="BDT",
                    incurred_at=datetime.combine(month_end, time(18), tzinfo=DHAKA),
                    payment_status=BusinessExpenseStatus.PAID if paid else BusinessExpenseStatus.DUE,
                    due_date=None if paid else month_end + timedelta(days=10), counterparty=counterparty,
                    notes="Monthly total (synthetic demo data)", source=SEED,
                ))
            month = month_end + timedelta(days=1)
        stock_ins = self.db.execute(select(InventoryStockIn).where(InventoryStockIn.seller_id == self.seller.id)).scalars().all()
        for stock_in in stock_ins:
            if stock_in.unit_cost is None:
                continue
            received = stock_in.received_at.astimezone(DHAKA).date()
            # Supplier terms: 30 days; bills for stock received in the last 30 days are still owed.
            due = received + timedelta(days=30)
            paid = due < self.as_of
            self._create("EXPENSE", f"SUPPLIER:{stock_in.id}", BusinessExpense(
                seller_id=self.seller.id, expense_type=BusinessExpenseType.SUPPLIER_PURCHASE,
                amount=(Decimal(stock_in.quantity) * Decimal(stock_in.unit_cost)).quantize(Decimal("0.01")), currency=stock_in.currency or "BDT",
                incurred_at=stock_in.received_at, payment_status=BusinessExpenseStatus.PAID if paid else BusinessExpenseStatus.DUE,
                due_date=due, counterparty=SUPPLIER, notes=f"Stock-in {stock_in.quantity} units", source=SEED,
            ))

    def store_metric(self) -> None:
        self._create("STORE_METRIC", f"{MARKETPLACE}:{self.as_of}", MarketplaceStoreMetric(
            seller_id=self.seller.id, marketplace=MARKETPLACE, seller_rating=Decimal("4.60"), rating_count=1284,
            positive_rating_rate=Decimal("0.9200"), ship_on_time_rate=Decimal("0.9600"), chat_response_rate=Decimal("0.8900"),
            captured_at=datetime.combine(self.as_of, time(9), tzinfo=DHAKA), source=SEED,
        ))


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--apply", action="store_true")
    cli.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(DHAKA).date())
    args = cli.parse_args()
    with SessionLocal() as session:
        seller = session.execute(select(Seller).where(Seller.email == EMAIL)).scalar_one_or_none()
        if seller is None:
            print(f"seed_failed reason=no seller {EMAIL}", file=sys.stderr)
            return 2
        report = Seeder(session, seller, apply=args.apply, as_of=args.as_of).run()
    print(("applied" if args.apply else "dry run"), dict(sorted(report.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
