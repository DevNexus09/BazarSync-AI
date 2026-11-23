# RAG retrieval evaluation

Measures whether `RagRetrievalService.retrieve_context` returns the right business-memory chunks.
Plan: [2026-11-23 RAG retrieval improvements](../superpowers/plans/2026-11-23-rag-retrieval-improvements.md).

```bash
cd backend
venv/bin/python scripts/evaluate_rag_retrieval.py --seller-id <seller uuid> --configs baseline,translation
```

- Golden set: `backend/tests/fixtures/rag_retrieval_golden.json`. It has 53 cases: 30 English, 10 Bangla, 10 Banglish and 3 English questions with no answer in memory. They were written against the demo seller `demo1@gmail.com`. A hit is matched by source type and product SKU, not chunk ID, so re-indexing keeps the set valid. Every expectation was checked to exist among that seller's `EMBEDDED` chunks on 2026-11-24.
- The harness is read-only and writes its report to `backend/artifacts/rag_eval/`.
- Only `EMBEDDED` chunks are searchable. About half of this seller's chunks were still `PENDING` when measured; the numbers reflect the embedded half.

## Baseline (2026-11-24)

Environment: `RAG_RRF_ENABLED=true`, `RAG_COSINE_DISTANCE_ENABLED=true`, `COPILOT_MULTILINGUAL_ENABLED=true`, `RAG_MIN_SIMILARITY=0.45`, top_k 12, CPU, bge-m3.

| Set | Recall@5 | Recall@12 | MRR | Top-group share@12 | p50 ms | p95 ms |
|---|---|---|---|---|---|---|
| All (50 answerable) | 0.78 | 0.84 | 0.63 | 0.51 | 124 | 181 |
| English (30) | 0.83 | 0.90 | 0.68 | 0.53 | 136 | 222 |
| Bangla (10) | 0.90 | 1.00 | 0.71 | 0.44 | 112 | 152 |
| Banglish (10) | 0.50 | 0.50 | 0.40 | 0.50 | 111 | 130 |

Observations:
- **Banglish is the weakest set.** Bangla script does well because bge-m3 embeds across languages. Romanised Bangla does not.
- **All 3 unanswerable questions still returned chunks** (no-context rate 0.00). This is outside the plan's scope; it is noted for a later threshold review.
- Top-group share is 0.51, just over the plan's 0.5 crowding threshold. Task 5 also needs at least 3 misses caused by crowding before it starts.

## Task 2: English keyword terms (`RAG_KEYWORD_TRANSLATION_ENABLED`)

Same environment and fixture as the baseline.

| Set | Recall@5 | Recall@12 | MRR | p95 ms |
|---|---|---|---|---|
| All | 0.78 → 0.80 | 0.84 → 0.86 | 0.63 → 0.67 | 166 → 143 |
| English | 0.83 → 0.83 | 0.90 → 0.90 | 0.68 → 0.68 | unchanged |
| Bangla | 0.90 → 0.90 | 1.00 → 1.00 | 0.71 → 0.86 | |
| Banglish | 0.50 → 0.60 | 0.50 → 0.60 | 0.40 → 0.43 | |

**Gate: passed.** Bangla + Banglish recall@12 rose (0.75 → 0.80) and English did not fall. Recommended: `RAG_KEYWORD_TRANSLATION_ENABLED=true`.

What still misses, and which later task targets it:
- `DEMO-BATA-122185090 sales` returns a different product's sales. `ILIKE` returns the 48 *most recent* rows containing any keyword, so the common word "sales" crowds out the exact SKU row (Task 4).
- Right product but wrong record type (inventory lifecycle instead of inventory snapshot; pricing instead of price recommendation) (Task 3).
- Old Copilot chat messages (`COPILOT_HISTORY`), often written in Banglish, outrank business records for Banglish questions. Not addressed by this plan.

## Task 4: ranked full-text keyword search (`RAG_FULLTEXT_KEYWORD_ENABLED`)

Needs migration `q1a2b3c4d5e6`, a GIN index on `to_tsvector('simple', chunk_text)`. Apply it with `alembic upgrade q1a2b3c4d5e6`: two existing files share revision `o9c0d1e2f3a4`, so `alembic upgrade head` reports multiple heads. On the local DB it was applied, rolled back and re-applied cleanly. Measured with translation on in both columns.

| Set | Recall@5 | Recall@12 | MRR |
|---|---|---|---|
| All | 0.80 → 0.82 | 0.86 → 0.90 | 0.67 → 0.83 |
| English | 0.83 → 0.83 | 0.90 → 0.93 | 0.68 → 0.85 |
| Bangla | 0.90 → 1.00 | 1.00 → 1.00 | 0.86 → 1.00 |
| Banglish | 0.60 → 0.60 | 0.60 → 0.70 | 0.43 → 0.61 |

Keyword query alone (`demo-bata-122185090 sales`, 15 runs): ILIKE p50 40 ms / p95 168 ms (sequential scan); full-text p50 79 ms / p95 100 ms (bitmap scan on the new index). End-to-end retrieval p95 stayed at about 190 ms.

**Gate: passed.** Recall@12 did not fall in any language, and keyword p95 is lower. Recommended: `RAG_FULLTEXT_KEYWORD_ENABLED=true` after applying the migration. Trade-off: typical (p50) keyword latency rises by about 40 ms, because every match is now scored for relevance instead of taking the newest rows. At this seller's size (about 8k chunks) a sequential scan is still cheap; the index matters as memory grows.

## Task 5: group cap (`RAG_MAX_CHUNKS_PER_GROUP=3`)

Start gate met: top-group share was 0.60, and 3 misses (en_06, banglish_02, banglish_03) were cases where one (record type, product) group filled the results and pushed out the expected record type for that same product. Measured on top of translation + full-text.

| Set | Recall@5 | Recall@12 | MRR | Top-group share@12 |
|---|---|---|---|---|
| All | 0.82 → 0.86 | 0.90 → 0.96 | 0.83 → 0.84 | 0.60 → 0.31 |
| English | 0.83 → 0.87 | 0.93 → 0.97 | 0.85 → 0.86 | |
| Bangla | 1.00 → 1.00 | 1.00 → 1.00 | 1.00 → 1.00 | |
| Banglish | 0.60 → 0.70 | 0.70 → 0.90 | 0.61 → 0.64 | |

**Gate: passed** (recall@12 up, MRR not down). Recommended: `RAG_MAX_CHUNKS_PER_GROUP=3`. Results over the cap are moved to the end rather than dropped, so a question about one product still gets up to top_k results.

## Task 3: cross-encoder reranker (`RAG_RERANKER_ENABLED`)

Model `BAAI/bge-reranker-v2-m3` (2.27 GB, Hugging Face cache), CPU. Measured on top of translation + full-text + group cap, after loading the model.

| Config | Recall@5 | Recall@12 | MRR | p50 ms | p95 ms |
|---|---|---|---|---|---|
| Without reranker | 0.86 | 0.96 | 0.84 | 145 | 231 |
| Reranker, 20 candidates (default) | 0.94 | 0.96 | 0.88 | 1565 | 2169 (English 2639) |
| Reranker, 10 candidates | 0.90 | 0.96 | 0.86 | 891 | 1204 |

Raw scoring of full-length (1500-character) chunks takes 1.2 s for 10 candidates and 2.4 s for 20, on both CPU and MPS. Twenty long candidates therefore exceed the 1500 ms budget: the reranker is skipped for that request, and the time is still spent.

**Gate: technically passed** at 20 candidates (recall@5 +8 points, English recall@12 unchanged, overall p95 2169 ms ≤ 2500). **Recommendation: keep `RAG_RERANKER_ENABLED=false` for now.**
- It adds about 1.4 s to every memory lookup.
- English p95 (2.6 s) already exceeds the plan's 2.5 s limit.
- The memory tool discards all results past 4 s, so under concurrent load it risks losing memory entirely.
- Bangla MRR dipped from 1.00 to 0.93.

Revisit on faster inference hardware, or with a smaller reranker model. Ten candidates halves the cost but gains only +4 points of recall@5, below the gate.

Deployment note: if enabled, pre-download the model on the API host (`huggingface_hub.snapshot_download("BAAI/bge-reranker-v2-m3")`), which needs about 2.3 GB of disk. Until the model is loaded, requests skip reranking rather than wait.

## Rollout summary

| Flag | Recall@12 change | Latency cost | Gate | Recommended value |
|---|---|---|---|---|
| `RAG_KEYWORD_TRANSLATION_ENABLED` | 0.84 → 0.86 (Banglish 0.50 → 0.60) | none | passed | `true` |
| `RAG_FULLTEXT_KEYWORD_ENABLED` | 0.86 → 0.90, MRR 0.67 → 0.83 | keyword p50 +40 ms, p95 −68 ms | passed | `true` (after `alembic upgrade q1a2b3c4d5e6`) |
| `RAG_MAX_CHUNKS_PER_GROUP` | 0.90 → 0.96 (Banglish 0.70 → 0.90) | none | passed | `3` |
| `RAG_RERANKER_ENABLED` | 0.96 → 0.96, recall@5 0.86 → 0.94 | +1.4 s p50 | passed on numbers, not recommended | `false` |

With the three recommended flags, the whole golden set goes from **recall@12 0.84 → 0.96** and **MRR 0.63 → 0.84**, and Banglish from 0.50 → 0.90, with no added latency at p95.

Rollout order: translation → full-text (migration first) → group cap, each turned on separately in staging, with this harness re-run after each.

Full regression on 2026-11-24: `pytest tests` with all flags off gave 1341 passed, 85 skipped. `pytest tests -k "rag or copilot"` with the three recommended flags on gave 596 passed, 2 skipped.

Not addressed by this plan, found while measuring:
- All 3 unanswerable questions still return chunks (no-context rate 0.00), so the similarity floor never yields "no memory".
- Old Copilot chat messages (`COPILOT_HISTORY`) outrank business records for some Banglish questions.
- About half of the demo seller's chunks are still `PENDING` embedding.

## Notes from the final review

- **`/rag/ask` follows the same flags.** Full-text search, the group cap and the reranker live inside `RagRetrievalService`, so the standalone `/rag/ask` endpoint also changes when they are on. Translation is Copilot-only. All flags default off, and every measured change is an improvement, so this is accepted rather than plumbed per caller.
- **Reranker hardening.** One request scores at a time; a concurrent request skips reranking instead of slowing both. A batch that would likely end past the budget is not started. The model is never downloaded at runtime (`local_files_only=True`), so **pre-downloading it on the host is required** before enabling the flag.
- **Full-text matches whole words.** `price` does not match `prices`, and `sku77` does not match `SKU-77`, where ILIKE matched substrings. The eval still improved overall; keep this in mind when reading misses.
- **Migration runbook.** If `CREATE INDEX CONCURRENTLY` fails it leaves an INVALID index, and `IF NOT EXISTS` would then skip it. Check `select indisvalid from pg_index where indexrelid = 'ix_rag_memory_chunks_chunk_text_fts'::regclass;`, drop the index if it is false, and re-run.
