# Daraz refresh operations

## Scheduling

Beat keeps its six-hour entries and its 02:00 UTC nightly refresh by default. They select active products and skip existing pending or running jobs. The database uniqueness constraint scopes run keys by seller, product and marketplace. Admission locks the product row, and a PostgreSQL advisory lock prevents concurrent execution of the same Celery delivery. Redis continues to serve as the Celery broker and result backend.

The current seller and product models have no scraper monitoring switch or seller-supplied product priority. Eligibility uses the existing active status and seller ownership. Price-change activity is used as an urgency signal. The planner does not infer importance from inventory, price or marketplace listing status.

Set `SCRAPER_ADAPTIVE_ENABLED=true` on Beat and workers to run the due policy on the original ticks and on an additional hourly tick at minute 15. The existing schedule flag and Daraz authorization gate still apply. The planner uses the most recent completed run, the most recent terminal attempt, seller-scoped competitor price-change events and priced snapshots. New products come first, followed by overdue products in deadline order. Recent price changes break ties. Adaptive ticks coordinate through a PostgreSQL advisory lock. Admission rechecks the last terminal attempt under the product lock to avoid racing a just-completed manual scrape.

| Policy field | Default |
| --- | --- |
| `normal_hours`, `volatile_hours`, `stable_hours` | 6, 3 and 12 hours |
| `failure_hours`, `repeated_failures` | 12 hours after 2 consecutive failed or partial terminal attempts |
| `change_window_days`, `volatile_changes` | Three distinct runs with price-change events over seven days |
| `stable_observations` | Four completed runs with observed prices and no detected changes in the window |
| `max_per_tick`, `max_in_flight` | 25 new jobs per tick and up to 50 pending or running jobs at planning time, including manual jobs |

Override fields using a JSON object in `SCRAPER_REFRESH_POLICY`. A first failure waits the normal interval. Manual requests still use their existing admission rules and can fill capacity after the planner takes its workload snapshot. Stale database runs continue to count toward capacity and need the existing operational recovery procedure. Absence of detected events is a stability heuristic. Products without priced snapshots stay on the normal interval.

## Metadata reuse and request limits

Search results are always fetched live. Caching search results could hide changed prices, availability or newly discovered listings. Once a fresh listing supplies price, stock and store, cached descriptions, brand, category, image URL and specifications may replace a detail request. Cache entries contain no price, rating, stock or seller name. They use the marketplace, parser version, seller scope and listing URL with its variant query. URL fragments are ignored. Entries expire after `SCRAPER_METADATA_CACHE_TTL` seconds, default six hours and capped at 24 hours. Set it to zero to disable reuse. A parser-version change invalidates prior keys. Ownership tokens and a 180-second lock TTL coordinate cache misses. A competing run waits briefly and can proceed with its live search fields. Cache errors fall back to live detail acquisition, subject to the global limiter.

Workers sharing the Redis database share Daraz's existing minimum start spacing and concurrent-request cap. A rolling `SCRAPER_DARAZ_BUDGET_PER_MINUTE` adds a default limit of 120 starts in any minute. Set every worker to the same limits and keep them within authorized traffic. The limiter fails closed if Redis is unavailable. Leases expire after worker loss.

Five temporary top-level failures within 60 seconds open the shared circuit for 120 seconds by default. Override with `SCRAPER_DARAZ_CIRCUIT_FAILURES`, `SCRAPER_DARAZ_CIRCUIT_WINDOW_SECONDS` and `SCRAPER_DARAZ_CIRCUIT_COOLDOWN_SECONDS`. After the cooldown one top-level request probes recovery. HTTP 429 keeps the shared Retry-After behavior. Explicit HTTP 401, 403 and 451 stop the current scrape and slow other workers for at least 60 seconds. Permanent restrictions never trigger an alternate acquisition path.

## Telemetry and validation

`daraz_scrape_attempt` is a JSON event correlated by run and product UUID. It reports retry count, stage outcomes, parser version, acquisition path, extracted and validated counts, shortlisted count, match count, duration, metadata cache hits and completeness. For mixed HTML sources where the raw candidate count is ambiguous, `products_found` is null. The event contains no seller identifiers, listing titles, search queries, raw exception messages or headers. A completed scrape with zero matches still has a successful matching status. The cache provenance records the original metadata observation time separately from the current search observation.

Use fixture-backed runs with disposable PostgreSQL and Redis. From `backend/` run `venv/bin/python -m pytest -q tests/test_daraz_efficiency.py tests/test_daraz_scraping.py tests/test_daraz_acquisition.py` with `BAZARSYNC_TEST_POSTGRES_URL` and `BAZARSYNC_TEST_REDIS_URL` configured. Check a recent product, an overdue product and a product in failure cooldown on the same adaptive tick. Repeat a scrape with a live price and confirm a metadata hit skips the detail request while the price observation still comes from that run.
