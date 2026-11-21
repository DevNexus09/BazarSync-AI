"""Bounded, seller-scoped reads for offline historical dataset generation."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.product import Product, ProductMarketplaceListing
from app.models.sales_data_coverage import SalesDataCoverage
from app.models.sales_record import SalesRecord
from app.models.scrape_run import ScrapeRun


class HistoricalDatasetRepository:
    def __init__(self, db: Session, seller_id: UUID) -> None:
        self.db = db
        self.seller_id = seller_id

    def products(self, product_id: UUID | None) -> list[Product]:
        query = (
            select(Product)
            .where(Product.seller_id == self.seller_id)
            .order_by(Product.id)
        )
        if product_id is not None:
            query = query.where(Product.id == product_id)
        return list(self.db.scalars(query))

    def sales(
        self, product_id: UUID, start: datetime, end: datetime, as_of: datetime
    ) -> list[SalesRecord]:
        return list(
            self.db.scalars(
                select(SalesRecord)
                .where(
                    SalesRecord.seller_id == self.seller_id,
                    SalesRecord.product_id == product_id,
                    SalesRecord.sold_at >= start,
                    SalesRecord.sold_at < end,
                    SalesRecord.created_at <= as_of,
                )
                .order_by(SalesRecord.created_at, SalesRecord.id)
            )
        )

    def coverage(
        self, product_id: UUID, start: date, end: date, as_of: datetime
    ) -> list[SalesDataCoverage]:
        # Marketplace-only batches cannot establish product-wide coverage.
        return list(
            self.db.scalars(
                select(SalesDataCoverage)
                .where(
                    SalesDataCoverage.seller_id == self.seller_id,
                    SalesDataCoverage.product_id == product_id,
                    SalesDataCoverage.marketplace.is_(None),
                    SalesDataCoverage.coverage_start_date <= end,
                    SalesDataCoverage.coverage_end_date >= start,
                    SalesDataCoverage.created_at <= as_of,
                    SalesDataCoverage.updated_at <= as_of,
                    SalesDataCoverage.last_imported_at <= as_of,
                )
                .order_by(
                    SalesDataCoverage.last_imported_at.desc(), SalesDataCoverage.id
                )
            )
        )

    def inventory(
        self, product_id: UUID, start: datetime, end: datetime
    ) -> list[InventoryHistory]:
        return list(
            self.db.scalars(
                select(InventoryHistory)
                .where(
                    InventoryHistory.seller_id == self.seller_id,
                    InventoryHistory.product_id == product_id,
                    InventoryHistory.source != InventorySnapshotSource.BACKFILL,
                    InventoryHistory.captured_at >= start,
                    InventoryHistory.captured_at < end,
                )
                .order_by(InventoryHistory.captured_at, InventoryHistory.id)
            )
        )

    def listings(self, product_id: UUID) -> list[ProductMarketplaceListing]:
        return list(
            self.db.scalars(
                select(ProductMarketplaceListing)
                .where(
                    ProductMarketplaceListing.seller_id == self.seller_id,
                    ProductMarketplaceListing.product_id == product_id,
                    ProductMarketplaceListing.marketplace_listing_id.is_not(None),
                )
                .order_by(ProductMarketplaceListing.id)
            )
        )

    def competitors(
        self, product_id: UUID, earliest_observation: datetime, last_cutoff: datetime
    ) -> list[tuple[CompetitorSnapshot, ScrapeRun]]:
        query = (
            select(CompetitorSnapshot, ScrapeRun)
            .join(ScrapeRun, CompetitorSnapshot.scrape_run_id == ScrapeRun.id)
            .join(
                Competitor,
                and_(
                    CompetitorSnapshot.competitor_id == Competitor.id,
                    Competitor.product_id == ScrapeRun.product_id,
                    Competitor.scrape_run_id == ScrapeRun.id,
                    Competitor.marketplace == ScrapeRun.marketplace,
                ),
            )
            .where(
                ScrapeRun.seller_id == self.seller_id,
                ScrapeRun.product_id == product_id,
                CompetitorSnapshot.product_id == product_id,
                func.upper(ScrapeRun.status) == "COMPLETED",
                ScrapeRun.created_at < last_cutoff,
                ScrapeRun.finished_at < last_cutoff,
                ScrapeRun.updated_at < last_cutoff,
                CompetitorSnapshot.created_at < last_cutoff,
                CompetitorSnapshot.captured_at < last_cutoff,
                CompetitorSnapshot.price_observed_at < last_cutoff,
                CompetitorSnapshot.price_observed_at >= earliest_observation,
            )
            .order_by(
                CompetitorSnapshot.price_observed_at.desc(),
                CompetitorSnapshot.created_at.desc(),
                CompetitorSnapshot.id,
            )
        )
        return [(snapshot, run) for snapshot, run in self.db.execute(query)]
