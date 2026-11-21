"""Acquire public Bata Daraz candidates for manual manifest review.

This command never writes application database records and never promotes raw
search results into the validated seed manifest automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
import sys

from app.core.config import settings
from app.scraper.services.competitor_service import scrape_daraz_competitors

DEFAULT_QUERIES = (
    "Bata shoes",
    "Bata women shoes",
    "Bata kids shoes",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirm-public-acquisition",
        action="store_true",
        help="Confirm that public Daraz acquisition is authorized for this run.",
    )
    return parser


async def _acquire() -> dict[str, object]:
    candidates: dict[str, dict[str, object]] = {}
    observations: list[dict[str, object]] = []
    for query in DEFAULT_QUERIES:
        response = await scrape_daraz_competitors(product_title=query)
        observations.append(
            {
                "query": query,
                "observed_at": response.scraped_at.isoformat(),
                "result_count": len(response.products),
            }
        )
        for product in response.products:
            if product.store_name.strip().casefold() != "bata":
                continue
            match = re.search(r"-i(\d+)\.html(?:$|[?#])", product.daraz_product_url)
            if match is None:
                continue
            listing_id = match.group(1)
            candidates.setdefault(
                listing_id,
                {
                    "listing_id": listing_id,
                    "title": product.product_title,
                    "brand": product.product_brand or None,
                    "current_price_bdt": str(product.product_price),
                    "original_price_bdt": (
                        str(product.original_price) if product.original_price is not None else None
                    ),
                    "discount_percent": product.discount_percentage,
                    "store_name": product.store_name,
                    "listing_url": product.daraz_product_url,
                    "image_url": product.product_image_url or None,
                    "availability_status": product.stock_status,
                    "validation_status": "CANDIDATE_REQUIRES_MANUAL_REVIEW",
                    "missing_fields": [
                        field for field, value in (
                            ("category", product.product_category),
                            ("description", product.product_description),
                            ("material", None),
                            ("color", None),
                            ("available_sizes", None),
                        ) if not value
                    ],
                },
            )
    return {
        "source_store_url": "https://www.daraz.com.bd/shop/bata/",
        "observations": observations,
        "candidate_count": len(candidates),
        "candidates": list(candidates.values()),
        "notice": (
            "Raw public search observations only. Manually verify seller identity, product "
            "identity, category and missing fields before updating the deterministic manifest."
        ),
    }


def main() -> int:
    args = _parser().parse_args()
    if not args.confirm_public_acquisition or not settings.daraz_scraping_authorized:
        print(
            "acquisition_refused reason=explicit_confirmation_and_DARAZ_SCRAPING_AUTHORIZED_required",
            file=sys.stderr,
        )
        return 2
    payload = asyncio.run(_acquire())
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_count": payload["candidate_count"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
