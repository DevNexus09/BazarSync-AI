"""Export one authorized seller's daily dataset from a read-only database snapshot."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from sqlalchemy import text

from app.schemas.forecast_features import ForecastSourceSnapshot

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.forecast_snapshot_service import ForecastSnapshotService
from app.services.historical_dataset_service import (
    HistoricalDataset,
    HistoricalDatasetService,
)


def _write_atomic(path: Path, payload: str) -> None:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            encoding="utf-8",
            newline="\n",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seller-id",
        type=UUID,
        required=True,
        help="Seller authorized for this export",
    )
    parser.add_argument(
        "--product-id", type=UUID, help="Limit export to one owned product"
    )
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--as-of", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--forecast-snapshot",
        action="store_true",
        help="Capture a live, single-product Task 9 input snapshot",
    )
    args = parser.parse_args()
    if not settings.historical_dataset_export_enabled:
        parser.error(
            "Set HISTORICAL_DATASET_EXPORT_ENABLED=true to enable offline exports."
        )
    if args.as_of.utcoffset() is None or args.as_of > datetime.now(timezone.utc):
        parser.error("--as-of must be offset-aware and at or before the current time.")

    if args.forecast_snapshot and args.product_id is None:
        parser.error("--forecast-snapshot requires --product-id.")

    try:
        with SessionLocal() as db, db.begin():
            db.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            snapshot: HistoricalDataset | ForecastSourceSnapshot
            if args.forecast_snapshot:
                snapshot = ForecastSnapshotService(
                    db, authorized_seller_id=args.seller_id
                ).capture(
                    start_date=args.start_date,
                    end_date=args.end_date,
                    as_of=args.as_of,
                    product_id=args.product_id,
                )
            else:
                snapshot = HistoricalDatasetService(
                    db, authorized_seller_id=args.seller_id
                ).build(
                    start_date=args.start_date,
                    end_date=args.end_date,
                    as_of=args.as_of,
                    product_id=args.product_id,
                )
        _write_atomic(args.output, snapshot.model_dump_json())
    except (ValueError, LookupError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
