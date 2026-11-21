# Task 3 · Durable recommendation generation

## API and idempotency

Enable `RECOMMENDATION_JOBS_ENABLED` on the API and Celery Beat after applying migration `k5e6f7a8b9c0` and deploying workers that register the new tasks. The flag defaults to false. The existing generation and latest endpoints retain their contracts. When enabled, the generation response adds `job_id`, which also serves as the stable `task_id`. Invalid products and failed preflight checks retain their existing error responses and are not admitted as jobs.

`POST /api/v1/recommendations/generate/{product_id}` accepts an optional UUID `Idempotency-Key` header. A product-row lock and partial unique index enforce a single active job per seller and product. Concurrent requests coalesce, including requests with different keys. All explicit keys bind to that job, and replaying a key returns its original job after completion or failure. A fresh key after a terminal result starts a new refresh. Clients without a key coalesce during active work and can refresh after completion.

`GET /api/v1/recommendations/jobs/{job_id}` returns the exact job and its result, including status, attempt count, timestamps and sanitized terminal error code/message. `GET /api/v1/recommendations/products/{product_id}/job` discovers the latest job when the client has no job ID. Both require seller authentication and check current product ownership. The worker checks ownership at claim time and again before committing. Task 1's scrape-run ID is pinned at admission when available. The system recomputes and validates evidence during execution. The request key and active scope define idempotency so a legitimate later refresh may reuse the same scrape run.

The recommendation page stores the request key and returned job ID by seller and product. It polls the exact job every two seconds, stops on both terminal states, and uses the stored job result after reload or navigation. A failed job can be retried with a fresh key. A status transport failure offers status refresh through the generation button without creating another job. Legacy responses still use bounded latest-row polling.

## Recovery and consistency

| State | Meaning |
| --- | --- |
| `PENDING` | Committed to PostgreSQL and awaiting delivery or a transient retry. Redis failure leaves it recoverable. |
| `RUNNING` | A worker claimed the job and holds a 180-second lease. A live lease suppresses duplicate delivery. |
| `COMPLETED` | Recommendation, its RAG outbox entry and the job result committed in one transaction. |
| `FAILED` | A permanent error, exhausted attempts, or the 15-minute deadline ended generation. |

The job row also holds the dispatch reservation. Publishers reserve before sending and can republish after the 30-second reservation expires. Celery Beat sweeps every 30 seconds. An authenticated status read also recovers due jobs and surfaces expiry if Beat is unavailable. Run Beat for recovery while sellers are offline. The worker has a 120-second async execution limit and 150-second Celery hard limit with the production prefork pool. The lease and attempt number fence writes from superseded workers. Transient provider/storage failures may return to pending for up to three attempts. Product and analytics validation failures are terminal. Logs correlate by job and attempt. The public API uses fixed messages and does not serialize provider or database exceptions.

The existing RAG outbox owns asynchronous indexing retries and deduplication. Enable the existing RAG schedule where indexing is required. An indexing failure after commit has no effect on job status. Optional notification delivery is bounded and best effort after commit. Existing Socket.IO event types and seller-room scopes are preserved, with the Phase 5 Redis publisher as a worker fallback.

## Migration and rollback

The additive migration creates the job and request-key tables. Historical recommendation rows and actions are preserved. For rollback, disable new job admission and let active jobs resolve before removing the tables. Job-ID reads can still follow admitted jobs while admission is disabled. Downgrade drops job history and request-key mappings and preserves recommendation and RAG records. The pre-existing fresh-install Alembic blocker remains outside this migration.
