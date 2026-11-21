from datetime import date, datetime, timedelta
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.competitor import Competitor
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.product import Product, ProductMarketplaceListing
from app.models.product_price_history import (
    ProductPriceHistory,
    ProductPriceHistorySource,
)
from app.models.sales_data_coverage import (
    SalesDataCompletenessStatus,
    SalesDataCoverage,
)
from app.models.sales_record import (
    SalesRecord,
    SalesRecordPriceSource,
    SalesRecordStatus,
)
from app.models.scrape_run import ScrapeRun
from app.models.seller import Seller
from app.schemas.forecast_features import ForecastSourceSnapshot
from app.schemas.sales_import import SalesImportRecord, SalesImportRequest
from app.services.forecast_feature_builder import ForecastFeatureBuilder
from app.services.forecast_snapshot_service import ForecastSnapshotService
from app.services.historical_dataset_service import HistoricalDatasetService
from app.services.sales_import_service import SalesImportService

START = date(2025, 1, 2)
END = date(2025, 1, 4)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value + "+00:00")


PAST = at("2024-12-30T01:00")
SALE = at("2025-01-01T18:00")
IMPORTED = at("2025-01-05T01:00")
AS_OF = at("2025-01-07T00:00")
TABLES = [
    model.__table__
    for model in (
        Seller,
        Product,
        ProductMarketplaceListing,
        SalesRecord,
        SalesDataCoverage,
        InventoryHistory,
        ScrapeRun,
        Competitor,
        CompetitorSnapshot,
    )
]


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(*_args, **_kwargs) -> str:
    return "JSON"


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session
    engine.dispose()


def product(db: Session, email: str = "a@example.com") -> Product:
    seller = Seller(email=email, password_hash="test", created_at=PAST)
    db.add(seller)
    db.flush()
    item = Product(
        seller_id=seller.id,
        title="Item",
        category="Home",
        specifications={"Brand": "Example"},
        selling_price=100,
        stock_quantity=50,
        cost_price=50,
        minimum_margin=10,
        supplier_lead_time=1,
        created_at=PAST,
        updated_at=PAST,
    )
    db.add(item)
    db.flush()
    return item


def sale(db: Session, item: Product, ref: str | None, **overrides) -> SalesRecord:
    values = dict(
        seller_id=item.seller_id,
        product_id=item.id,
        sold_at=SALE,
        created_at=IMPORTED,
        status=SalesRecordStatus.COMPLETED,
        quantity_sold=1,
        source_reference=ref,
        price_source=SalesRecordPriceSource.IMPORTED_TRANSACTION,
        unit_price=Decimal("10.25"),
        currency="BDT",
    )
    record = SalesRecord(**(values | overrides))
    db.add(record)
    return record


def coverage(db: Session, item: Product, **overrides) -> None:
    values = dict(
        seller_id=item.seller_id,
        product_id=item.id,
        source="seller_import",
        coverage_start_date=date(2025, 1, 1),
        coverage_end_date=date(2025, 1, 3),
        completeness_status=SalesDataCompletenessStatus.COMPLETE,
        last_imported_at=IMPORTED,
        created_at=IMPORTED,
        updated_at=IMPORTED,
    )
    db.add(SalesDataCoverage(**(values | overrides)))


def stock(db: Session, item: Product, day: date, on_hand: int, **overrides) -> None:
    captured = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    values = dict(
        seller_id=item.seller_id,
        product_id=item.id,
        snapshot_date=day,
        quantity_on_hand=on_hand,
        quantity_available=on_hand,
        source=InventorySnapshotSource.DAILY_SNAPSHOT,
        content_hash="test",
        captured_at=captured,
        created_at=captured,
    )
    db.add(InventoryHistory(**(values | overrides)))


def scrape(
    db: Session, item: Product, available: datetime, **overrides
) -> CompetitorSnapshot:
    observed = at("2025-01-01T12:00")
    run = ScrapeRun(
        seller_id=overrides.pop("seller_id", item.seller_id),
        product_id=item.id,
        marketplace="Daraz",
        status="COMPLETED",
        run_key=str(uuid4()),
        created_at=observed,
        finished_at=available,
        updated_at=overrides.pop("run_updated_at", available),
    )
    db.add(run)
    db.flush()
    competitor = Competitor(
        scrape_run_id=run.id,
        product_id=item.id,
        competitor_title="Item",
        marketplace=overrides.pop("competitor_marketplace", "Daraz"),
    )
    db.add(competitor)
    db.flush()
    values = dict(
        scrape_run_id=run.id,
        product_id=item.id,
        competitor_id=competitor.id,
        price=Decimal("21.83"),
        currency="BDT",
        stock_status="UNKNOWN",
        external_listing_id="example-listing",
        match_score=0.9,
        created_at=available,
        captured_at=observed,
        price_observed_at=observed,
    )
    result = CompetitorSnapshot(**(values | overrides))
    db.add(result)
    db.flush()
    return result


def generate(db: Session, item: Product, **overrides):
    db.flush()
    args = dict(start_date=START, end_date=END, as_of=AS_OF)
    return HistoricalDatasetService(db, authorized_seller_id=item.seller_id).build(
        **(args | overrides)
    )


def test_duplicate_import_is_idempotent_and_unkeyed_replays_are_quarantined(
    db, monkeypatch
):
    item = product(db)
    monkeypatch.setattr(
        "app.services.rag_index_outbox_service.RagIndexOutboxService.enqueue_upsert",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "app.tasks.dead_stock_workflow_tasks.enqueue_dead_stock_recalculation",
        lambda **kw: None,
    )
    payload = SalesImportRequest(
        records=[
            SalesImportRecord(
                product_id=item.id,
                quantity=3,
                sold_at=SALE,
                status=SalesRecordStatus.COMPLETED,
                source_reference="line-1",
            ),
        ]
    )
    importer = SalesImportService(db)
    assert (
        importer.import_records(
            seller_id=item.seller_id, payload=payload
        ).imported_count
        == 1
    )
    assert (
        importer.import_records(
            seller_id=item.seller_id, payload=payload
        ).skipped_duplicate_count
        == 1
    )
    sale(db, item, None)
    sale(db, item, None)
    dataset = generate(db, item, as_of=datetime.now(SALE.tzinfo))
    assert dataset.rows[0].observed_units_sold == 3
    assert dataset.rows[0].source_ids["sales_records"] != ()
    assert dataset.quality.unkeyed_sales_records == 2
    assert dataset.rows[0].valid_order_count is None


def test_returns_cancellations_prices_and_coverage(db):
    item = product(db)
    sale(
        db,
        item,
        "line-1",
        quantity_sold=5,
        returned_units=2,
        refunded_restocked_units=1,
    )
    sale(
        db,
        item,
        "line-2",
        status=SalesRecordStatus.FULFILLED,
        unit_price=Decimal("11.75"),
    )
    sale(
        db,
        item,
        "cancel",
        status=SalesRecordStatus.CANCELLED,
        quantity_sold=4,
        returned_units=1,
    )
    sale(db, item, "failed", status=SalesRecordStatus.FAILED_PAYMENT, quantity_sold=5)
    sale(db, item, "test", is_test_order=True, quantity_sold=10)
    coverage(db, item)
    stock(db, item, START, 10)
    dataset = generate(db, item)
    first, zero, missing = dataset.rows
    assert first.observed_units_sold == 3
    assert first.returned_or_cancelled_units == 7
    assert first.effective_selling_price == Decimal("10.75")
    assert first.currency == "BDT"
    assert first.forecast_label_eligible
    assert first.category == "Home" and first.brand == "Example"
    assert (
        zero.observed_units_sold
        == zero.valid_order_count
        == zero.returned_or_cancelled_units
        == 0
    )
    assert missing.observed_units_sold is missing.valid_order_count is None
    assert dataset.quality.longest_eligible_run_by_product[str(item.id)] == 1
    assert dataset.quality.observed_days_by_product[str(item.id)] == 2


def test_missing_and_mixed_prices(db):
    item = product(db)
    sale(db, item, "priced")
    sale(
        db,
        item,
        "estimate",
        price_source=SalesRecordPriceSource.CURRENT_PRODUCT_PRICE_ESTIMATE,
    )
    sale(db, item, "bdt", sold_at=SALE + timedelta(days=1))
    sale(db, item, "usd", sold_at=SALE + timedelta(days=1), currency="USD")
    sale(db, item, "known-currency", sold_at=SALE + timedelta(days=2))
    sale(db, item, "unknown-currency", sold_at=SALE + timedelta(days=2), currency=None)
    result = generate(db, item)
    assert result.rows[0].observed_units_sold == 2
    assert result.rows[0].effective_selling_price is None
    assert "MISSING_TRANSACTION_PRICE" in result.rows[0].data_quality_flags
    assert result.rows[1].effective_selling_price is result.rows[1].currency is None
    assert "MIXED_SALES_CURRENCY" in result.rows[1].data_quality_flags
    assert result.rows[2].effective_selling_price is result.rows[2].currency is None


def test_marketplace_point_in_time_and_scoped_coverage(db):
    item = product(db)
    db.add(
        ProductMarketplaceListing(
            seller_id=item.seller_id,
            product_id=item.id,
            marketplace="Daraz",
            marketplace_listing_id="daraz-1",
            created_at=PAST,
            updated_at=PAST,
        )
    )
    sale(db, item, "market-line", marketplace_listing_id="daraz-1")
    coverage(db, item, marketplace="Daraz")
    coverage(db, item, product_id=None)
    first, missing, _ = generate(db, item).rows
    assert (
        first.marketplace == "Daraz"
        and first.source_ids["product_marketplace_listings"]
    )
    assert first.observed_units_sold == 1 and not first.sales_coverage_complete
    assert missing.observed_units_sold is None


def test_unknown_stock_and_same_day_stockout(db):
    item = product(db)
    coverage(db, item)
    stock(db, item, START, 5, quantity_reserved=5, quantity_available=0)
    stock(db, item, date(2025, 1, 3), 9, source=InventorySnapshotSource.BACKFILL)
    stock(db, item, END, 0, created_at=at("2025-01-05T00:00"))
    first, backfill, late = generate(db, item).rows
    assert first.on_hand_stock == 5
    assert first.stockout_indicator is True and not first.forecast_label_eligible
    assert backfill.stockout_indicator is late.stockout_indicator is None
    assert "STOCKOUT_UNKNOWN" in backfill.data_quality_flags


def test_dhaka_midnight_and_label_availability(db):
    item = product(db)
    sale(db, item, "before", sold_at=SALE - timedelta(microseconds=1), quantity_sold=99)
    sale(db, item, "at-midnight", quantity_sold=2)
    sale(db, item, "late", created_at=AS_OF + timedelta(seconds=1), quantity_sold=18)
    result = generate(db, item)
    assert result.rows[0].prediction_cutoff == SALE
    assert result.rows[0].observed_units_sold == 2
    assert (
        generate(db, item, as_of=at("2025-01-04T18:00")).rows[0].observed_units_sold
        is None
    )


def test_competitor_cutoffs_dedupe_and_cross_seller_scrapes(db):
    item = product(db)
    other = product(db, "b@example.com")
    good = scrape(db, item, at("2025-01-01T13:00"))
    scrape(db, item, SALE, price=Decimal("90"))
    scrape(
        db,
        item,
        at("2025-01-01T13:00"),
        created_at=SALE + timedelta(seconds=1),
        external_listing_id="late-store",
    )
    scrape(
        db,
        item,
        at("2025-01-01T13:00"),
        price_observed_at=None,
        external_listing_id="no-time",
    )
    scrape(
        db, item, at("2025-01-01T13:00"), match_score=0.15, external_listing_id="weak"
    )
    scrape(
        db,
        item,
        at("2025-01-01T13:00"),
        run_updated_at=AS_OF,
        external_listing_id="unpublished",
    )
    scrape(
        db,
        item,
        at("2025-01-01T13:00"),
        seller_id=other.seller_id,
        external_listing_id="foreign",
    )
    first, following, _ = generate(db, item).rows
    assert first.source_ids["competitor_snapshots"] == (good.id,)
    assert first.competitor_prices[0].mean == Decimal("21.83")
    assert following.competitor_prices[0].count == 2


def test_foreign_products_and_mismatched_source_owners_are_excluded(db):
    item = product(db)
    other = product(db, "b@example.com")
    sale(db, other, "other")
    sale(db, item, "wrong-owner", seller_id=other.seller_id)
    stock(db, item, START, 90, seller_id=other.seller_id)
    coverage(db, item, seller_id=other.seller_id)
    with pytest.raises(LookupError, match="Product not found"):
        generate(db, item, product_id=other.id)
    dataset = generate(db, item)
    assert {row.product_id for row in dataset.rows} == {item.id}
    assert all(
        row.observed_units_sold is row.on_hand_stock is None for row in dataset.rows
    )


def test_replay_empty_sales_and_date_partitions(db):
    item = product(db)
    before = db.scalar(select(func.count()).select_from(SalesRecord))
    dataset = generate(db, item)
    assert dataset.model_dump_json() == generate(db, item).model_dump_json()
    first = generate(db, item, end_date=START)
    tail = generate(db, item, start_date=START + timedelta(days=1))
    assert first.rows + tail.rows == dataset.rows
    assert (
        dataset.quality.row_count == 3
        and dataset.quality.products_with_observed_sales == 0
    )
    assert dataset.quality.missing_values["observed_units_sold"] == 3
    assert db.scalar(select(func.count()).select_from(SalesRecord)) == before == 0


def test_invalid_quantities_and_unresolved_sales_block_zero(db):
    item = product(db)
    coverage(db, item)
    sale(db, item, "over-return", returned_units=2)
    sale(
        db,
        item,
        "pending",
        status=SalesRecordStatus.PENDING,
        sold_at=SALE + timedelta(days=1),
    )
    db.execute(text("PRAGMA ignore_check_constraints = ON"))
    sale(db, item, "negative", quantity_sold=-1)
    result = generate(db, item)
    assert result.quality.invalid_sales_records == 2
    assert result.quality.negative_quantity_records == 1
    assert (
        result.rows[0].observed_units_sold is result.rows[1].observed_units_sold is None
    )
    assert "UNRESOLVED_SALES" in result.rows[1].data_quality_flags


def test_coverage_correction_supersedes_older_import(db):
    item = product(db)
    coverage(db, item)
    coverage(
        db,
        item,
        completeness_status=SalesDataCompletenessStatus.PARTIAL,
        last_imported_at=IMPORTED - timedelta(days=1),
        created_at=IMPORTED - timedelta(days=1),
        updated_at=IMPORTED + timedelta(days=1),
    )
    first = generate(db, item).rows[0]
    assert not first.sales_coverage_complete and first.observed_units_sold is None


def test_conflicting_tied_declarations_cannot_prove_zero(db):
    item = product(db)
    coverage(db, item)
    coverage(db, item, completeness_status=SalesDataCompletenessStatus.PARTIAL)
    first = generate(db, item).rows[0]
    assert not first.sales_coverage_complete and first.observed_units_sold is None


def test_line_totals_are_weighted_without_round_trip_rounding(db):
    item = product(db)
    sale(
        db,
        item,
        "total-price",
        quantity_sold=3,
        unit_price=None,
        line_total=Decimal("1.00"),
    )
    sale(db, item, "free-unit", unit_price=Decimal("0"))
    assert generate(db, item).rows[0].effective_selling_price == Decimal("0.25")


def test_marketplace_mismatch_is_not_competitor_evidence(db):
    item = product(db)
    matching = scrape(db, item, at("2025-01-01T13:00"))
    scrape(
        db,
        item,
        at("2025-01-01T13:00"),
        competitor_marketplace="Foreign marketplace",
        external_listing_id="mismatch",
    )
    assert generate(db, item).rows[0].source_ids["competitor_snapshots"] == (
        matching.id,
    )


def test_newer_incomplete_coverage_and_product_metadata_after_cutoff(db):
    item = product(db)
    coverage(db, item)
    newer = IMPORTED + timedelta(days=1)
    coverage(
        db,
        item,
        completeness_status=SalesDataCompletenessStatus.PARTIAL,
        last_imported_at=newer,
        created_at=newer,
        updated_at=newer,
    )
    item.updated_at = SALE
    first, following, _ = generate(db, item).rows
    assert first.category is first.brand is first.observed_units_sold is None
    assert following.category == "Home"


@pytest.mark.skipif(
    not os.getenv("BAZARSYNC_HISTORICAL_TEST_POSTGRES_URL"),
    reason="Disposable PostgreSQL URL required",
)
def test_postgres_read_only_export_replays(monkeypatch, tmp_path):
    dsn = os.environ["BAZARSYNC_HISTORICAL_TEST_POSTGRES_URL"]
    engine = create_engine(dsn)
    try:
        Base.metadata.create_all(
            engine, tables=[*TABLES, ProductPriceHistory.__table__]
        )
        with Session(engine) as session:
            item = product(session)
            sale(session, item, "seed-line")
            scrape(session, item, at("2025-01-01T13:00"))
            seller_id = item.seller_id
            product_id = item.id
            session.add(
                ProductPriceHistory(
                    seller_id=seller_id,
                    product_id=product_id,
                    currency="BDT",
                    old_price=Decimal("82.50"),
                    new_price=Decimal("100.00"),
                    source=ProductPriceHistorySource.PRODUCT_EDIT,
                    changed_at=PAST,
                    created_at=PAST,
                )
            )
            session.commit()
        with Session(engine) as session, session.begin():
            session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            service = HistoricalDatasetService(session, authorized_seller_id=seller_id)
            result = service.build(start_date=START, end_date=END, as_of=AS_OF)
            rerun = service.build(start_date=START, end_date=END, as_of=AS_OF)
            assert result.model_dump_json() == rerun.model_dump_json()
            assert result.rows[0].observed_units_sold == 1
            assert len(result.rows[0].competitor_prices) == 1
            assert session.scalar(select(func.count()).select_from(SalesRecord)) == 1

        with Session(engine) as session, session.begin():
            with pytest.raises(ValueError, match="read-only, repeatable-read"):
                ForecastSnapshotService(
                    session, authorized_seller_id=seller_id
                ).capture(
                    product_id=product_id,
                    start_date=START,
                    end_date=END,
                    as_of=AS_OF,
                )

        from scripts import export_historical_dataset

        output = tmp_path / "dataset.json"
        monkeypatch.setattr(
            export_historical_dataset, "SessionLocal", lambda: Session(engine)
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "export",
                "--seller-id",
                str(seller_id),
                "--start-date",
                str(START),
                "--end-date",
                str(END),
                "--as-of",
                AS_OF.isoformat(),
                "--output",
                str(output),
            ],
        )
        monkeypatch.setattr(
            export_historical_dataset.settings,
            "historical_dataset_export_enabled",
            False,
        )
        with pytest.raises(SystemExit, match="2"):
            export_historical_dataset.main()
        assert not output.exists()
        monkeypatch.setattr(
            export_historical_dataset.settings,
            "historical_dataset_export_enabled",
            True,
        )
        export_historical_dataset.main()
        assert output.read_text() == result.model_dump_json() + "\n"
        first_export = output.read_bytes()
        export_historical_dataset.main()
        assert output.read_bytes() == first_export

        import sys

        monkeypatch.setattr(
            "sys.argv",
            [*sys.argv, "--forecast-snapshot", "--product-id", str(product_id)],
        )
        export_historical_dataset.main()
        snapshot = ForecastSourceSnapshot.model_validate_json(output.read_text())
        assert snapshot.history.model_dump_json() == result.model_dump_json()
        assert snapshot.captured_at > AS_OF
        builder = ForecastFeatureBuilder(authorized_seller_id=seller_id)
        with pytest.raises(ValueError, match="captured before"):
            builder.build(snapshot, forecast_origin=AS_OF, horizon_days=7)
        live = builder.build(
            snapshot,
            forecast_origin=snapshot.captured_at + timedelta(seconds=1),
            horizon_days=7,
        )
        assert live.features.known_base_price == Decimal("100.00")
        assert live.features.latest_base_price_change == Decimal("17.50")
        assert live.features.competitor_markets == ()

        archived = output.read_bytes()
        origin = snapshot.captured_at + timedelta(microseconds=1)
        features = builder.build(snapshot, forecast_origin=origin, horizon_days=7)
        with Session(engine) as session, session.begin():
            record = session.scalars(
                select(SalesRecord).where(
                    SalesRecord.seller_id == seller_id,
                    SalesRecord.product_id == product_id,
                )
            ).one()
            record.returned_units = 1
        export_historical_dataset.main()
        fresh = ForecastSourceSnapshot.model_validate_json(output.read_bytes())
        assert fresh.history.rows[0].observed_units_sold == 0
        with pytest.raises(ValueError, match="captured before"):
            builder.build(fresh, forecast_origin=origin, horizon_days=7)
        replay = ForecastSourceSnapshot.model_validate_json(archived)
        assert replay.history.rows[0].observed_units_sold == 1
        assert builder.build(replay, forecast_origin=origin, horizon_days=7) == features

    finally:
        engine.dispose()
