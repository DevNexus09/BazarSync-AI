"""Read-only comparison of reorder advice against its shadow (Phase 5.3 rollout check).

Usage: venv/bin/python -m scripts.reorder_shadow_report --seller-id <uuid> [--days 14]
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from uuid import UUID

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models.reorder_recommendation import ReorderRecommendation
from app.services.reorder_recommendation_service import summarize_shadow


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-id", type=UUID, required=True)
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    since = date.today() - timedelta(days=args.days)
    session = SessionLocal()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        rows = list(
            session.execute(
                select(ReorderRecommendation).where(
                    ReorderRecommendation.seller_id == args.seller_id,
                    ReorderRecommendation.as_of_date >= since,
                )
            ).scalars()
        )
        print(json.dumps({"seller_id": str(args.seller_id), "since": since.isoformat(), **summarize_shadow(rows)}, indent=2))
    finally:
        session.rollback()
        session.close()


if __name__ == "__main__":
    main()
