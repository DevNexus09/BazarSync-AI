from __future__ import annotations

import argparse
import logging
from datetime import timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.models.competitor import Competitor
from app.models.product import Product
from app.repositories.competitor_snapshot_repository import ScrapeRunRepository
from app.scraper.constants import MARKETPLACE_NAME
from app.services.competitor_snapshot_service import CompetitorSnapshotService


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill immutable competitor snapshots.")
    parser.add_argument("--seller-id", type=UUID, default=None)
    parser.add_argument("--product-id", type=UUID, default=None)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    created = 0
    skipped = 0
    failed = 0

    session = SessionLocal()
    try:
        groups = _iter_groups(session, seller_id=args.seller_id, product_id=args.product_id)
        for seller_id, product_id, marketplace in groups:
            run_key = f"phase5_snapshot_backfill:{seller_id}:{product_id}:{marketplace}:v1"
            existing = ScrapeRunRepository(session).get_by_run_key(
                seller_id=seller_id,
                product_id=product_id,
                marketplace=marketplace,
                run_key=run_key,
            )
            if existing and existing.status == "COMPLETED":
                skipped += 1
                logger.info("Skipped existing backfill seller=%s product=%s marketplace=%s", seller_id, product_id, marketplace)
                continue

            competitors = _load_competitors(session, product_id=product_id, marketplace=marketplace, limit=args.batch_size)
            if not competitors:
                skipped += 1
                continue
            if args.dry_run:
                created += 1
                logger.info(
                    "Dry run would backfill seller=%s product=%s marketplace=%s competitors=%s",
                    seller_id,
                    product_id,
                    marketplace,
                    len(competitors),
                )
                continue

            service = CompetitorSnapshotService(session)
            try:
                result = service.start_scrape_run(
                    seller_id=seller_id,
                    product_id=product_id,
                    marketplace=marketplace,
                    run_key=run_key,
                )
                if result.already_completed:
                    session.commit()
                    skipped += 1
                    continue
                captured_at = max(
                    (item.updated_at or item.created_at for item in competitors),
                    default=None,
                )
                if captured_at is not None and captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=timezone.utc)
                service.record_successful_scrape(
                    scrape_run=result.scrape_run,
                    competitors=competitors,
                    captured_at=captured_at,
                    discovered_count=len(competitors),
                    matched_count=len(competitors),
                )
                session.commit()
                created += 1
                logger.info(
                    "Backfilled seller=%s product=%s marketplace=%s competitors=%s",
                    seller_id,
                    product_id,
                    marketplace,
                    len(competitors),
                )
            except (SQLAlchemyError, ValueError) as exc:
                session.rollback()
                failed += 1
                logger.exception(
                    "Backfill failed seller=%s product=%s marketplace=%s error=%s",
                    seller_id,
                    product_id,
                    marketplace,
                    exc,
                )
    finally:
        session.close()

    logger.info("Backfill complete created=%s skipped=%s failed=%s", created, skipped, failed)
    return 1 if failed else 0


def _iter_groups(session, *, seller_id: UUID | None, product_id: UUID | None):
    statement = (
        select(Product.seller_id, Competitor.product_id, Competitor.marketplace)
        .join(Product, Competitor.product_id == Product.id)
        .where(Competitor.marketplace.is_not(None))
        .distinct()
        .order_by(Product.seller_id, Competitor.product_id, Competitor.marketplace)
    )
    if seller_id:
        statement = statement.where(Product.seller_id == seller_id)
    if product_id:
        statement = statement.where(Competitor.product_id == product_id)
    return session.execute(statement).all()


def _load_competitors(session, *, product_id: UUID, marketplace: str, limit: int) -> list[Competitor]:
    statement = (
        select(Competitor)
        .where(
            Competitor.product_id == product_id,
            Competitor.marketplace == (marketplace or MARKETPLACE_NAME),
        )
        .order_by(Competitor.created_at.asc(), Competitor.id.asc())
        .limit(limit)
    )
    return list(session.execute(statement).scalars().all())


if __name__ == "__main__":
    raise SystemExit(main())
