from __future__ import annotations

import argparse
from uuid import UUID

from app.db.session import SessionLocal
from app.services.inventory_history_service import InventoryHistoryService


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill current product inventory into daily history.")
    parser.add_argument("--seller-id", type=UUID, default=None)
    parser.add_argument("--product-id", type=UUID, default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        result = InventoryHistoryService(session).backfill_current_inventory(
            batch_size=args.batch_size,
            seller_id=args.seller_id,
            product_id=args.product_id,
            dry_run=args.dry_run,
        )
    finally:
        session.close()

    print(
        "inventory_backfill "
        f"created={result.created_count} "
        f"skipped={result.skipped_count} "
        f"failed={result.failed_count} "
        f"dry_run={result.dry_run_count}"
    )


if __name__ == "__main__":
    main()
