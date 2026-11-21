# Daraz competitor scraping

The competitor dashboard submits `POST /api/v1/scraper/run/{product_id}` with the seller's bearer token. Poll `GET /api/v1/scraper/runs/{scrape_run_id}` and retrieve competitors with `GET /api/v1/competitors/{product_id}`. The former direct search route, `POST /api/v1/scraper/daraz`, returns `410 Gone` with the queued endpoint as its replacement.

Daraz Bangladesh's site terms restrict automated extraction and its public robots policy disallows `/catalog/`, which the AJAX and browser searches use. `DARAZ_SCRAPING_AUTHORIZED` defaults to `false`. Set it on workers and Beat only if Daraz has explicitly authorized the requested paths and request volumes. With acquisition disabled, queued manual runs report `DARAZ_ACQUISITION_DISABLED` and scheduled tasks skip dispatch. [Daraz site terms](https://www.daraz.com.bd/terms-of-use/) · [Daraz robots policy](https://www.daraz.com.bd/robots.txt)

## Run behavior

- Concurrent submissions for the same seller product share the active run and task ID. The first accepted threshold applies. Once a run is terminal, a new request can start another run.
- Beat continues to run every six hours and at 02:00 UTC when the existing schedule is enabled. Scheduled jobs require `ProductStatus.ACTIVE` at submission and execution. Marketplace listing status describes a seller listing and there is no separate monitoring flag.
- Celery retries transient acquisition and database failures up to three times with exponential backoff and jitter. Daraz `Retry-After` overrides a shorter retry delay. Workers on the same Redis instance share the cooldown. Access denial, malformed search results, model unavailability, and unexpected matching errors terminate the run. See the existing detail endpoints for `failure_code`. Raw exceptions appear in worker logs.
- A completed run can have zero matches. Scores must satisfy the configured or requested threshold and the matching checks. `SIMILARITY_MIN_RESULTS` is obsolete.
- Nullable fields store missing observations as null. An explicit zero is retained. Invalid marketplace values are logged at debug level and treated as missing observations. An incomplete listing refresh preserves last-known competitor values, while the fresh snapshot contains null for missing price, rating, and review count. Missing prices produce no price-history observation. The ranking's price-weighted popularity signal is an estimate used only for ordering listings.

When rolling out, replace old scrape workers before starting the new API and Beat. New admission publishes while holding the product row lock. Updated workers wait on that lock before reading the run. Keep the broker durable and monitor old pending or running jobs. A broker that loses an already published delivery can leave a run active and requires operational recovery.

## Acquisition and worker lifecycle

HTTPX uses the existing `/catalog/?q=…&ajax=true` URL with a per-scrape connection pool. Valid empty lists complete immediately. Temporary HTTPX transport errors and unsupported responses can fall back to the standalone Playwright API. When neither AJAX path yields listings, HTTPX can read structured data and selectors from the existing public search page before Chromium rendering. Access denials, redirects, recognized challenges and active marketplace cooldowns stop the chain. HTTPX streams at most 4 MiB of decoded response data per request.

Details use HTTPX for existing validated product URLs when the flag is enabled. A detail page with no extractable metadata can use Chromium independently of the search strategy. The same parser and ranking logic are used throughout. Search and detail source metadata is available internally and in acquisition logs. Serialization to matching and the public API is unchanged. Duplicate detail URLs that differ only by fragment share one request within a scrape. A seller-scoped cache can also reuse stable detail metadata across jobs when fresh search data includes price, stock and store. Search responses and volatile fields are fetched live.

The Docker worker uses Celery's default prefork pool and recycles children after 50 tasks. The documented CLI also defaults to prefork. Each task uses `run_async`, which creates a new event loop with `asyncio.run()` even in the thread fallback. A worker child can execute several jobs during its lifetime, but those jobs do not share an event loop. HTTPX, Redis and Playwright therefore belong to a single scrape. The standalone Playwright API starts its driver without Chromium. Chromium launches on demand, is shared by page contexts within the scrape, and is closed with the driver at job exit. Each browser page has an isolated context that closes with it.

All scraper workers must use the same Redis database and rate settings to share pacing. The coordinator applies both a minimum interval between starts and an in-flight cap, including Chromium subrequests. It stops admission while `Retry-After` is active and fails closed if Redis is unavailable. Request slots are released on completion and expire after 90 seconds if a worker dies. Chromium declines redirects, skips images, fonts and media, and allows at most 48 subresource requests per page. This also limits the impact of pages with large asset bundles. The browser path still needs an installed Playwright driver and Chromium.

| Worker configuration | Default |
| --- | --- |
| `SCRAPER_HTTPX_ENABLED` | `true`. Restart workers with `false` to start at the Playwright API. |
| `SCRAPER_HTTPX_CONNECT_TIMEOUT`, `SCRAPER_HTTPX_READ_TIMEOUT`, `SCRAPER_HTTPX_WRITE_TIMEOUT`, `SCRAPER_HTTPX_POOL_TIMEOUT` | 10, 30, 10, 10 seconds |
| `SCRAPER_HTTPX_TOTAL_TIMEOUT` | 45 seconds, with a maximum of 60 |
| `SCRAPER_HTTPX_MAX_CONNECTIONS`, `SCRAPER_HTTPX_MAX_KEEPALIVE_CONNECTIONS` | 10 and 5 per scrape |
| `SCRAPER_DETAIL_CONCURRENCY` | Three per scrape, subject to the shared limits |
| `SCRAPER_DARAZ_MIN_INTERVAL_SECONDS`, `SCRAPER_DARAZ_MAX_IN_FLIGHT`, `SCRAPER_DARAZ_SLOT_WAIT_SECONDS` | 0.5 seconds between starts, three in flight, and a 20-second slot wait |

Set the Redis limits within the authorized quota before enabling live acquisition. The defaults are starting values pending authorized marketplace measurements.

## Extraction and field mapping

Parser version `2.1` uses one Pydantic model for AJAX, page JSON and HTML. Both AJAX transports normalize the same payload identically. Page parsing checks JSON-LD Product and ItemList records, then JSON scripts containing the existing `mods.listItems` structure, then HTML selectors. A lower-priority source can fill missing fields for the same URL. JSON scripts are parsed as data. Detail offers require a matching listing URL, including query parameters, and aggregate offers are excluded. The saved fixtures are synthetic regression examples.

| Normalized field | Existing destination |
| --- | --- |
| `title` | `competitors.competitor_title` |
| `product_url` | `competitors.product_url`, `competitor_snapshots.source_url` and `external_listing_id` |
| `current_price` | `competitors.competitor_price`, `competitor_snapshots.price`, `price_history.observed_price` |
| `original_price`, `discount_percentage` | `competitors.original_price`, `competitors.discount_percentage` |
| `currency` | `competitor_snapshots.currency` uses the existing BDT contract. Foreign prices are excluded. |
| `seller_name` | `competitors.competitor_store` |
| `rating`, `review_count` | `competitors.competitor_rating`, `competitors.rating_count`, `competitor_snapshots.rating`, `competitor_snapshots.review_count` |
| `sold_count`, `sold_label` | Numeric count feeds preliminary ranking. The existing `competitors.competitor_sold` string stores the normalized label. |
| `stock_status`, `stock_text` | `competitors.stock_status` retains recognized raw text, and snapshots store normalized status and raw text. |
| `image_url`, `search_position` | `competitors.image_url`, `competitors.search_position` |
| `description`, `category`, `brand`, `specifications` | `competitors.competitor_description`, `competitors.competitor_category`, `competitors.competitor_brand`, `competitors.competitor_attributes` |
| Preliminary ranking score | `competitors.ranking_score` |
| Source, extraction quality and timestamps | Internal acquisition metadata. The selected price observation timestamp is written to `price_history.observed_at`. Snapshots keep the run capture time. |

A missing title or a missing or invalid Daraz product URL makes a listing `FAILED`. A valid identity with missing price, store, or recognized stock is `PARTIAL`; an identity with all three is `SUCCESS`. Neither classification replaces scrape-run state. The coverage score is the sum of weights for observed fields divided by configured weights. Defaults weight price at three, store and stock at two, and other scored fields at one. Set `SCRAPER_EXTRACTION_WEIGHTS` to a JSON map of known fields and positive weights to override the score. A zero observation counts as present.

The existing preliminary ranking runs before a title-only relevance check for clear accessory, recognized brand, and explicit identifier conflicts. The first `SCRAPER_MAX_RESULTS` remaining candidates are enriched, with 25 as the default. Sparse metadata does not exclude a candidate from enrichment. The existing final verifier still determines competitor matches. Detail fetches only fill gaps in current-run fields, and no cached listing is treated as a new observation.

## Validate locally

1. Run the fixture tests from `backend/` with `venv/bin/python -m pytest -q tests/test_daraz_parser.py tests/test_daraz_acquisition.py tests/test_daraz_scraping.py`.
2. For concurrency and persistence checks, set `BAZARSYNC_TEST_POSTGRES_URL` to a disposable PostgreSQL database or one where the test user can create and drop private schemas. Set `BAZARSYNC_TEST_REDIS_URL` to a disposable Redis database for the shared-limit test. The marketplace, broker and model calls are stubbed.
3. In a fixture-backed worker, authenticate as the product owner and submit two simultaneous requests. Check both responses return the same task and run IDs, then submit again after completion and check that a new run is created. Poll as another seller and check for `404`.
4. Compare a valid search with no verified matches against a model failure. The first completes with zero successful matches and dispatches Phase 5. The second reports `FAILED` with a sanitized message and no Phase 5 dispatch.
5. Scrape a priced listing, then refresh it with price extraction missing. Check the stored competitor keeps its previous price, the latest snapshot price is null, and no new price-history row was written.

## Loopback benchmark

From `backend/`, run `PYTHONPATH=. venv/bin/python scripts/benchmark_daraz_acquisition.py --runs 12` with Playwright and Chromium installed. The script measures real transports against a loopback fixture, verifies the rendered fallback and checks cleanup. It uses a fixed 20 ms browser settle delay and immediate request admission to isolate acquisition costs. The fixture verifies five listing prices and five detail descriptions in every successful mode and checks that an HTTP 403 stops after one request.

The Phase 2 loopback measurements below include a fresh scrape loop for each sample. The eager baseline launches Chromium before the Playwright API call, as the previous implementation did. Chromium startup is the wait for the first browser, including driver startup when the driver is cold. Total time includes search, five details and resource cleanup.

| Path | Search mean / p95 (ms) | Total mean / p95 (ms) | First browser mean (ms) | Mean requests / TCP connections |
| --- | ---: | ---: | ---: | ---: |
| Previous eager Playwright API | 391 / 645 | 655 / 958 | 367 | 6 / 2.9 |
| Lazy Playwright API | 269 / 329 | 612 / 695 | 100 | 6 / 3 |
| HTTPX search and details | 15 / 18 | 60 / 95 | 0 | 6 / 3 |
| Chromium fallback after Playwright API | 467 / 527 | 705 / 839 | 96 | 7 / 3 |
| Hybrid forced through both fallbacks | 485 / 553 | 546 / 615 | 100 | 8 / 4 |

All successful runs extracted the expected five prices and five descriptions. The blocked case made one request and started neither fallback. The harness verified closed HTTPX clients, empty browser context lists and disconnected Chromium instances. The local run used `PLAYWRIGHT_NODEJS_PATH` with the system Node executable because the development virtual environment lacked Playwright's bundled Node. These measurements exclude production pacing and Daraz network latency.

For verification rules, model staging and offline model comparison, see [Daraz competitor matching](daraz-matching.md).

See [Daraz refresh operations](daraz-operations.md) for adaptive scheduling, caching, request limits and telemetry.
