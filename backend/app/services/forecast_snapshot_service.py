"""Capture the live, seller-scoped inputs used by future forecast origins."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Context, localcontext
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.product_price_history import (
    ProductPriceHistory,
    ProductPriceHistorySource,
)
from app.schemas.forecast_features import (
    CatalogSnapshot,
    CompetitorPriceObservation,
    ForecastSourceSnapshot,
)
from app.services.historical_dataset_service import (
    COMPETITOR_LOOKBACK,
    HistoricalDatasetService,
    _explicit_brand,
    _utc,
    verified_competitor_prices,
)


@contextmanager
def forecast_read_session(db: Session) -> Iterator[Session]:
    """Keep forecast reads and failures outside the recommendation transaction."""
    bind = db.get_bind()
    if not isinstance(bind, Engine) or bind.dialect.name != "postgresql":
        raise ValueError("Forecast capture requires a separate PostgreSQL transaction.")
    with bind.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin(), Session(connection) as read:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '1500ms'"))
            yield read


class ForecastSnapshotService:
    def __init__(self, db: Session, *, authorized_seller_id: UUID) -> None:
        self._db = db
        self._history = HistoricalDatasetService(
            db, authorized_seller_id=authorized_seller_id
        )
        self._seller_id = authorized_seller_id

    def capture(
        self,
        *,
        product_id: UUID,
        start_date: date,
        end_date: date,
        as_of: datetime,
    ) -> ForecastSourceSnapshot:
        """Read inside the caller's read-only, repeatable-read PostgreSQL transaction."""
        if self._db.get_bind().dialect.name != "postgresql":
            raise ValueError("Forecast capture requires PostgreSQL.")
        isolation, read_only = self._db.execute(
            select(
                func.current_setting("transaction_isolation"),
                func.current_setting("transaction_read_only"),
            )
        ).one()
        if isolation not in {"repeatable read", "serializable"} or read_only != "on":
            raise ValueError(
                "Forecast capture requires a read-only, repeatable-read transaction."
            )

        history = self._history.build(
            product_id=product_id,
            start_date=start_date,
            end_date=end_date,
            as_of=as_of,
        )
        cutoff = history.as_of_timestamp
        (product,) = self._history.repo.products(product_id)
        if not _utc(product.created_at) <= _utc(product.updated_at) < cutoff:
            raise ValueError(
                "The current catalog version must predate the data cutoff."
            )

        # ProductService records base-price edits in BDT. Listing and baseline
        # prices have separate scopes and cannot establish a base-price change.
        price = self._db.scalars(
            select(ProductPriceHistory)
            .where(
                ProductPriceHistory.seller_id == self._seller_id,
                ProductPriceHistory.product_id == product_id,
                ProductPriceHistory.listing_id.is_(None),
                ProductPriceHistory.marketplace.is_(None),
                ProductPriceHistory.currency == "BDT",
                ProductPriceHistory.source == ProductPriceHistorySource.PRODUCT_EDIT,
                ProductPriceHistory.changed_at < cutoff,
                ProductPriceHistory.created_at < cutoff,
            )
            .order_by(ProductPriceHistory.changed_at.desc(), ProductPriceHistory.id)
            .limit(1)
        ).first()
        known_change = (
            price is not None
            and price.old_price is not None
            and price.old_price.is_finite()
            and price.old_price >= 0
            and price.new_price == product.selling_price
        )
        if not known_change:
            price = None
        with localcontext(Context(prec=38)):
            catalog = CatalogSnapshot(
                seller_id=self._seller_id,
                product_id=product_id,
                created_at=_utc(product.created_at),
                updated_at=_utc(product.updated_at),
                category=(product.category or "").strip() or None,
                brand=_explicit_brand(product),
                base_price=product.selling_price,
                last_price_change=price.new_price - price.old_price
                if price and price.old_price is not None
                else None,
                price_change_at=_utc(price.changed_at) if price else None,
                price_change_recorded_at=_utc(price.created_at) if price else None,
                price_history_id=price.id if price else None,
            )
        competitors = self._history.repo.competitors(
            product_id,
            cutoff - COMPETITOR_LOOKBACK,
            cutoff,
        )
        observations = tuple(
            CompetitorPriceObservation(
                seller_id=self._seller_id,
                product_id=product_id,
                marketplace=item.marketplace,
                listing=item.listing,
                currency=item.currency,
                price=item.price,
                snapshot_id=item.snapshot_id,
                observed_at=item.observed_at,
                available_at=item.available_at,
            )
            for item in verified_competitor_prices(competitors)
        )
        # Database wall time measured after all input reads. A caller-selected
        # historical as_of cannot make mutable rows safe for an older origin.
        captured_at: datetime = self._db.execute(
            select(func.clock_timestamp())
        ).scalar_one()
        if captured_at < cutoff:
            raise ValueError("Data cutoff cannot follow the database capture time.")
        return ForecastSourceSnapshot(
            seller_id=self._seller_id,
            product_id=product_id,
            history=history,
            captured_at=captured_at,
            catalog=catalog,
            competitors=observations,
        )
