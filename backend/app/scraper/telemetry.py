from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass
from uuid import UUID

from app.scraper.constants import MARKETPLACE_NAME
from app.scraper.schemas import ScrapeResponse
from app.scraper.schemas.scraped_product import PARSER_VERSION

logger = logging.getLogger(__name__)


@dataclass
class ScrapeTelemetry:
    scrape_run_id: str
    product_id: str
    retry_count: int | None
    marketplace: str = MARKETPLACE_NAME
    parser_version: str = PARSER_VERSION
    acquisition_method: str | None = None
    request_status: str = "not_started"
    parser_status: str = "not_started"
    matching_status: str = "not_started"
    products_found: int | None = None
    products_validated: int | None = None
    candidates_selected: int | None = None
    competitors_matched: int | None = None
    metadata_cache_hits: int = 0
    partial_extractions: int = 0
    mean_completeness: float | None = None
    missing_important: dict[str, int] | None = None
    failure_code: str | None = None
    duration_ms: int = 0

    @classmethod
    def start(cls, run_id: UUID, product_id: UUID, retry_count: int | None) -> ScrapeTelemetry:
        return cls(str(run_id), str(product_id), retry_count)

    def acquired(self, response: ScrapeResponse) -> None:
        self.acquisition_method = response.search_acquisition_method
        self.request_status = "success"
        self.products_found = response.raw_listing_count
        self.products_validated = response.validated_listing_count
        self.candidates_selected = len(response.products)
        quality = [item.extraction_quality for item in response.products if item.extraction_quality is not None]
        self.partial_extractions = sum(item.status == "PARTIAL" for item in quality)
        rejected = (
            self.products_found is not None and self.products_validated is not None
            and self.products_found > self.products_validated
        )
        self.parser_status = "partial" if self.partial_extractions or rejected else "success"
        self.metadata_cache_hits = sum(
            item.provenance is not None and item.provenance.metadata_cached_at is not None for item in response.products
        )
        if quality:
            self.mean_completeness = round(sum(item.score for item in quality) / len(quality), 3)
            self.missing_important = dict(Counter(field for item in quality for field in item.missing_important))

    def emit(self, duration: float) -> None:
        self.duration_ms = round(duration * 1000)
        logger.log(
            logging.WARNING if self.failure_code else logging.INFO,
            "%s", json.dumps({"event": "daraz_scrape_attempt", **asdict(self)}, separators=(",", ":")),
        )
