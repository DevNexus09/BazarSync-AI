# RAG Retrieval Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve which business-memory chunks the Copilot retrieves (Bangla/Banglish keyword matching, reranking, indexed keyword search) without changing any current behavior while the new flags are off.

**Architecture:** Every change lives inside the existing retrieval path: `CopilotToolRegistry` → `RagRetrievalService.retrieve_context` → `RagMemoryRepository`. Each improvement is behind its own default-off flag. With all flags off, retrieval output must be byte-for-byte what it is today. A measurement harness comes first, and each later flag is turned on only if the harness shows it helps.

**Tech Stack:** Python 3.14.4, FastAPI, SQLAlchemy 2.0, PostgreSQL + pgvector, Alembic, sentence-transformers 5.5.1 (already installed; `CrossEncoder` imports on the venv), pytest, ruff, mypy.

**Spec:** The comparison in this session against `Edtech/docs/RAG_IMPLEMENTATION_ANALYSIS.md`. In short:
1. Memory chunks are English, but Bangla/Banglish questions only send Bangla/romanised words to keyword search, so they never match.
2. Retrieval quality is not measured.
3. There is no reranker.
4. Keyword search is unindexed `ILIKE` and returns the *most recent* matching rows, not the most relevant.
5. Top results may be crowded by one product (unverified).

## Global Constraints

- **Do not commit, stage or switch branches.** The user commits manually. Each task ends by leaving its changes uncommitted, with a summary.
- The working tree already has uncommitted Copilot language work (`language/normalizer.py`, `lexicon.py`, `question_planner.py`, …). Build on it and do not revert it.
- New behavior must sit behind explicit default-off flags. With all new flags off, every existing test passes unchanged and `retrieve_context` returns the same chunks in the same order.
- Seller identity comes only from `CopilotToolContext.seller_id` / the authenticated seller. Every new query or filter must be seller-scoped, and the existing `_filter_*_for_seller` checks stay after every search.
- No new pip dependencies. Python 3.14.4 compatibility is required (Dockerfiles pin `python:3.14.4-slim-bookworm`).
- Migrations are additive only: create an index, never drop or rewrite data. Downgrade only drops what this plan created.
- `app/services/rag_retrieval_service.py` must **not** import `app.services.copilot.*`, because `app/services/copilot/__init__.py` imports `orchestrator` → `tool_registry` → `rag_retrieval_service` (circular). Language handling stays in the Copilot layer.
- `retrieve_business_memory` has `max_runtime_ms=4000`, checked *after* the tool returns (`tool_registry.py:639`). Going over discards all memory results as `TOOL_TIMEOUT`, so every new step needs its own smaller time budget.
- The `/rag/ask` endpoint (`RagAnswerService`) keeps today's behavior. Only the Copilot tool passes the new keyword terms.
- Test command: `cd backend && venv/bin/python -m pytest <paths> -q`. Lint: `venv/bin/ruff check <paths>`. Types: `venv/bin/mypy <paths>`.

## Review Focus

1. **A Bangla question the lexicon cannot translate.** Expect `english_search_terms` to return `()` and retrieval to behave exactly like today. An empty string must never reach `ILIKE` (`'%%'` matches every row). Test: Task 2, step 1 (`test_untranslatable_bangla_question_adds_no_terms`).
2. **First request after deploy, before the reranker model is loaded (about 2.3 GB).** Expect the request to skip reranking and return the hybrid order; it must never block on loading or hit `TOOL_TIMEOUT`. Test: Task 3, step 1 (`test_reranker_skips_while_model_loading`).
3. **A question made only of stopwords or punctuation** (for example `"???"` or `"what is the"`). Expect no keyword query at all, under both ILIKE and full-text. Test: Task 4, step 1 (`test_fulltext_skips_query_without_terms`).
4. **A keyword or rerank candidate that belongs to another seller.** Expect it to be dropped before ranking, reranking and evidence. Tests: Task 3 (`test_reranker_only_sees_seller_chunks`) and Task 4 (`test_fulltext_sql_is_seller_scoped`).
5. **All new flags off.** Expect identical output to today. Test: Task 2 (`test_no_keyword_terms_keeps_existing_keywords`) and the unchanged existing suites in every task.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `backend/app/services/rag_retrieval_metrics.py` | Create | Pure scoring functions (recall@k, reciprocal rank, concentration) |
| `backend/scripts/evaluate_rag_retrieval.py` | Create | Offline harness: runs `retrieve_context` per flag set and writes a report |
| `backend/tests/fixtures/rag_retrieval_golden.json` | Create | Labelled questions, matched by stable criteria rather than chunk IDs |
| `backend/app/services/copilot/language/normalizer.py` | Modify | `english_search_terms()` |
| `backend/app/services/copilot/tool_registry.py:2478` | Modify | Pass `keyword_terms` to retrieval when the flag is on |
| `backend/app/services/rag_retrieval_service.py` | Modify | `keyword_terms` parameter; reranker hook; full-text switch; optional group cap |
| `backend/app/services/rag_reranker_service.py` | Create | Lazy, time-budgeted cross-encoder scoring |
| `backend/app/repositories/rag_memory_repository.py:280` | Modify | Ranked full-text branch in `keyword_search` |
| `backend/alembic/versions/q1a2b3c4d5e6_add_rag_chunk_fulltext_index.py` | Create | GIN index on `to_tsvector('simple', chunk_text)` |
| `backend/app/core/config.py` (~line 251 and ~596) | Modify | New settings and env parsing, next to `rag_rrf_enabled` |
| `.env.example` (~line 168) | Modify | Document new flags, all `false` |
| `docs/copilot/rag-retrieval-eval.md` | Create | Measured results and the rollout decision for each flag |

New settings (field in `Settings`, env var, default):

| Setting | Env | Default |
|---|---|---|
| `rag_keyword_translation_enabled: bool` | `RAG_KEYWORD_TRANSLATION_ENABLED` | `False` |
| `rag_reranker_enabled: bool` | `RAG_RERANKER_ENABLED` | `False` |
| `rag_reranker_model: str` | `RAG_RERANKER_MODEL` | `"BAAI/bge-reranker-v2-m3"` |
| `rag_reranker_candidates: int` | `RAG_RERANKER_CANDIDATES` | `20` |
| `rag_reranker_budget_ms: int` | `RAG_RERANKER_BUDGET_MS` | `1500` |
| `rag_reranker_max_length: int` | `RAG_RERANKER_MAX_LENGTH` | `512` |
| `rag_fulltext_keyword_enabled: bool` | `RAG_FULLTEXT_KEYWORD_ENABLED` | `False` |
| `rag_max_chunks_per_group: int` | `RAG_MAX_CHUNKS_PER_GROUP` | `0` (off) |

Each task adds only its own settings.

---

### Task 1: Retrieval measurement harness (do first; no runtime change)

**Files:**
- Create: `backend/app/services/rag_retrieval_metrics.py`
- Create: `backend/scripts/evaluate_rag_retrieval.py`
- Create: `backend/tests/fixtures/rag_retrieval_golden.json`
- Test: `backend/tests/test_rag_retrieval_metrics.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ExpectedHit: source_type: str; product_sku: str | None = None; contains: tuple[str, ...] = ()`
  - `def hit_matches(chunk: Mapping[str, Any], expected: ExpectedHit) -> bool`. A chunk mapping has `source_type`, `product_sku`, `chunk_text`. It matches when `source_type` is equal, `product_sku` is equal (if given), and `chunk_text.casefold()` contains every `contains` string casefolded.
  - `def recall_at_k(chunks: Sequence[Mapping[str, Any]], expected: Sequence[ExpectedHit], k: int) -> float`: the share of `expected` matched by any of the first `k` chunks. Empty `expected` → `1.0`.
  - `def reciprocal_rank(chunks: Sequence[Mapping[str, Any]], expected: Sequence[ExpectedHit]) -> float`: `1/(i+1)` for the first chunk matching any expected hit, else `0.0`.
  - `def top_group_share(chunks: Sequence[Mapping[str, Any]], k: int) -> float`: the largest share of the first `k` chunks with the same `(source_type, product_sku)`; `0.0` when there are no chunks.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_rag_retrieval_metrics.py`

```python
SALES = {"source_type": "SALES_HISTORY", "product_sku": "SKU-1", "chunk_text": "Sales fell 12% in week 46"}
PRICE = {"source_type": "PRICE_HISTORY", "product_sku": "SKU-1", "chunk_text": "Price raised to BDT 950"}
def test_hit_matches_needs_type_sku_and_all_text():
    assert hit_matches(SALES, ExpectedHit("SALES_HISTORY", "SKU-1", ("sales fell",)))
    assert not hit_matches(SALES, ExpectedHit("SALES_HISTORY", "SKU-2"))
    assert not hit_matches(SALES, ExpectedHit("SALES_HISTORY", None, ("sales fell", "refund")))
def test_recall_and_rank():
    exp = [ExpectedHit("PRICE_HISTORY")]
    assert recall_at_k([SALES, PRICE], exp, 1) == 0.0
    assert recall_at_k([SALES, PRICE], exp, 2) == 1.0
    assert reciprocal_rank([SALES, PRICE], exp) == 0.5
    assert reciprocal_rank([], exp) == 0.0
    assert recall_at_k([SALES], [], 5) == 1.0
def test_top_group_share():
    assert top_group_share([SALES, SALES, PRICE, SALES], 4) == 0.75
    assert top_group_share([], 12) == 0.0
```

- [ ] **Step 2: Run them to confirm they fail.** Run `venv/bin/python -m pytest tests/test_rag_retrieval_metrics.py -q`. Expected: FAIL with `ModuleNotFoundError: app.services.rag_retrieval_metrics`.

- [ ] **Step 3: Implement the four functions and `ExpectedHit`** in `rag_retrieval_metrics.py`, with stdlib only.

- [ ] **Step 4: Run the tests to confirm they pass.** Same command. Expected: 3 passed.

- [ ] **Step 5: Write the harness** `scripts/evaluate_rag_retrieval.py`, following `scripts/copilot_eval.py`: `BACKEND` sys.path insert, argparse, and output to `artifacts/rag_eval/<UTC timestamp>.json`.
  - CLI: `--seller-id UUID` (required), `--fixture PATH` (default `tests/fixtures/rag_retrieval_golden.json`), `--top-k 12`, `--configs baseline,translation,reranker,fulltext` (comma list).
  - Each config is a dict of `settings` attribute overrides: `baseline` = all new flags off, plus `rag_rrf_enabled` and `rag_cosine_distance_enabled` at their current env values. Each named config turns on its one flag on top of `baseline`. Set the overrides before the run and restore them afterwards in `finally`.
  - For each case, call `RagRetrievalService(db).retrieve_context(seller_id=..., question=case["question"], top_k=top_k, keyword_terms=...)`. Pass `keyword_terms=english_search_terms(question)` only when the config enables translation (Task 2 adds the parameter; until then the harness runs `baseline` only). Map each `RagEvidence` to `{source_type, product_sku, chunk_text}`, resolving `product_sku` from `Product` scoped by `seller_id`.
  - Report per config, overall and per `language` (`en`/`bn`/`banglish`): mean recall@5, mean recall@12, MRR, no-context rate, mean `top_group_share@12`, retrieval latency p50/p95 in ms, and per-case misses (case id plus the top-3 returned `source_type`/text first 80 chars). Read only, with no writes to business tables.

- [ ] **Step 6: Author the fixture** `tests/fixtures/rag_retrieval_golden.json`: a list of `{"id", "language", "question", "expected": [{"source_type", "product_sku"?, "contains"?}]}`.
  - At least 30 `en`, 10 `bn` and 10 `banglish` cases, written against the demo seller from `scripts/seed_comprehensive_demo.py` after `rag_backfill_memory` and `rag_embed_pending_chunks` have run.
  - Take the `contains` strings from real `rag_memory_chunks.chunk_text` rows of that seller, with no numbers that change daily.
  - Reuse topics from `tests/evaluation/copilot_language_dataset.py` (its memory cases) for the bn/banglish questions.
  - Include 3 cases with no answer (`"expected": []`) whose right result is no relevant chunk; these are excluded from recall and reported as no-context rate.

- [ ] **Step 7: Run the baseline and record it.** Run `venv/bin/python scripts/evaluate_rag_retrieval.py --seller-id <demo seller> --configs baseline`. Expected: a JSON report is written. Copy the overall and per-language numbers into a new `docs/copilot/rag-retrieval-eval.md` under "Baseline (2026-11-xx)". **This baseline is the bar every later task is judged against.**

- [ ] **Step 8: Lint and types.** Run `venv/bin/ruff check app/services/rag_retrieval_metrics.py scripts/evaluate_rag_retrieval.py tests/test_rag_retrieval_metrics.py && venv/bin/mypy app/services/rag_retrieval_metrics.py`. Expected: clean. Leave the changes uncommitted.

---

### Task 2: English keyword terms for Bangla/Banglish questions

**Files:**
- Modify: `backend/app/services/copilot/language/normalizer.py` (add a function after `normalize_query`, line 83)
- Modify: `backend/app/services/copilot/language/__init__.py` (export it)
- Modify: `backend/app/services/rag_retrieval_service.py` (`retrieve_context` :114, `keyword_search_optional` :294, `hybrid_rank` :321, `_keywords` :602)
- Modify: `backend/app/services/copilot/tool_registry.py:2478` (`retrieve_business_memory` data method)
- Modify: `backend/app/core/config.py`, `.env.example` (`rag_keyword_translation_enabled`)
- Test: `backend/tests/test_copilot_multilingual.py`, `backend/tests/test_rag_retrieval_service.py`, `backend/tests/test_copilot_tool_registry.py`

**Interfaces:**
- Consumes: `normalize_query(question) -> NormalizedQuery` (`canonical_terms`, `translated`).
- Produces:
  - `def english_search_terms(question: str) -> tuple[str, ...]`: `canonical_terms` followed by the words of `translated`. Lowercased and de-duplicated in first-seen order; drops terms shorter than 3 characters, terms already in the casefolded question, and empty strings. Returns `()` when nothing was translated.
  - `RagRetrievalService.retrieve_context(..., keyword_terms: Sequence[str] | None = None)`, a new keyword-only parameter after `use_source_type_weights`.
  - `_keywords(question: str, extra_terms: Sequence[str] = ()) -> list[str]`. With no `extra_terms`, the result is exactly today's list (alphabetical, cap 8). Otherwise the cleaned `extra_terms` not already present are appended, up to 4 more (cap 12). Cleaning uses the same stopword set and lowercasing.

- [ ] **Step 1: Write the failing normalizer tests** in `tests/test_copilot_multilingual.py`

```python
def test_english_search_terms_translates_banglish():
    terms = english_search_terms("last week bikri keno komlo")
    assert "sales" in terms and all(t == t.lower() and len(t) >= 3 for t in terms)
def test_english_search_terms_skips_words_already_in_question():
    assert "sales" not in english_search_terms("why did sales drop")
def test_untranslatable_bangla_question_adds_no_terms():
    assert english_search_terms("ঝিলমিল") == ()
    assert "" not in english_search_terms("   ")
```

(If the current lexicon maps `bikri` to a different English word, use that word in the assertion. Check `BANGLISH_TERMS` in `lexicon.py` first.)

- [ ] **Step 2: Write the failing retrieval tests** in `tests/test_rag_retrieval_service.py`, using the existing `FakeRepository` and `chunk()`:
  - `test_no_keyword_terms_keeps_existing_keywords`: the same question with `keyword_terms=None` and with `keyword_terms=()` sends identical `keywords` to `repo.calls` `keyword_search`, equal to `_keywords(question)`.
  - `test_keyword_terms_reach_keyword_search`: `retrieve_context(question="গত সপ্তাহে বিক্রি কেন কমেছে?", keyword_terms=("sales",))` → the `keyword_search` call's `keywords` contains `"sales"`.
  - `test_translated_term_ranks_english_chunk`: with `settings.rag_rrf_enabled=True` (patched), a seller keyword row `chunk(text="sales fell 12 percent for SKU-77", …)` plus `keyword_terms=("sales", "sku-77")` → the chunk is returned and its explanation shows `keyword_score > 0`. Without `keyword_terms` and with a Banglish question, it is not returned.
  - `test_keyword_terms_cannot_widen_seller_scope`: a keyword row for another seller stays out even with matching `keyword_terms`.

- [ ] **Step 3: Write the failing tool-layer test** in `tests/test_copilot_tool_registry.py`. Patch `RagRetrievalService.retrieve_context` and record its kwargs:
  - flag off → `keyword_terms` is `None`;
  - flag on with question `"last week bikri keno komlo"` → `keyword_terms` contains the lexicon's word for sales;
  - in both cases `seller_id` equals the context seller.

- [ ] **Step 4: Run all three to confirm they fail.** Run `venv/bin/python -m pytest tests/test_copilot_multilingual.py tests/test_rag_retrieval_service.py tests/test_copilot_tool_registry.py -q -k "search_terms or keyword_terms or keyword_term"`. Expected: FAIL (`ImportError` / unexpected keyword `keyword_terms`).

- [ ] **Step 5: Implement.**
  - Add the setting and env parsing (next to `rag_rrf_enabled`) and the `.env.example` line `RAG_KEYWORD_TRANSLATION_ENABLED=false`.
  - Add `english_search_terms` and export it.
  - In `rag_retrieval_service.py`, thread `keyword_terms` into both `_keywords(...)` call sites (`keyword_search_optional` and `hybrid_rank` take a new `keyword_terms: Sequence[str] = ()` argument). Also pass `" ".join([normalized_question, *keyword_terms])` to `_source_types_for_question` so translated words boost the right source type.
  - In the tool data method, compute `keyword_terms = english_search_terms(question) if settings.rag_keyword_translation_enabled else None` and pass it. Do not import anything from `app.services.copilot` inside `rag_retrieval_service.py`.

- [ ] **Step 6: Run the new tests and the full existing suites.** Run `venv/bin/python -m pytest tests/test_copilot_multilingual.py tests/test_rag_retrieval_service.py tests/test_copilot_tool_registry.py tests/test_copilot_cross_language_routing.py tests/test_rag_prompt_and_answer_service.py tests/test_copilot_orchestrator.py -q`. Expected: all pass, with no existing test edited.

- [ ] **Step 7: Measure.** Run the harness with `--configs baseline,translation`. Record it in `docs/copilot/rag-retrieval-eval.md`. **Gate:** `bn` + `banglish` recall@12 must rise and `en` recall@12 must not fall. If either fails, leave the flag off and write down why.

- [ ] **Step 8: Lint and types.** Run `venv/bin/ruff check` and `venv/bin/mypy` on the changed files. Expected: clean. Leave the changes uncommitted.

---

### Task 3: Time-budgeted cross-encoder reranker

Start only after Task 2's measurement. Turn the flag on only if this task's gate passes.

**Files:**
- Create: `backend/app/services/rag_reranker_service.py`
- Modify: `backend/app/services/rag_retrieval_service.py` (constructor :98; `retrieve_context` between `hybrid_rank` (:184) and the min-similarity filter (:194); `_RankedChunk` :63)
- Modify: `backend/app/core/config.py`, `.env.example` (the five `rag_reranker_*` settings)
- Test: `backend/tests/test_rag_reranker_service.py`, `backend/tests/test_rag_retrieval_service.py`

**Interfaces:**
- Produces:
  - `class RagRerankerService: def __init__(self, *, model_name: str | None = None, device: str | None = None, max_length: int | None = None, loader: Callable[[], Any] | None = None)`. Defaults come from settings; `device` defaults to `settings.rag_embedding_device`.
  - `def score(self, question: str, texts: Sequence[str], *, budget_ms: int) -> list[float] | None`. Returns one score per text, or `None` when the model is not loaded yet, loading failed, `texts` is empty, or the budget ran out before all batches finished. It never raises.
  - Loading: the first call starts a single background thread that runs `CrossEncoder(model_name, device=device, max_length=max_length)`, cached process-wide by `(model_name, device, max_length)` like `RagEmbeddingService.load_model`. Calls before loading finishes return `None`. **A request never waits for the model to load.**
  - Scoring runs in batches of 4 and checks elapsed time after each batch. Once `budget_ms` is exceeded, it stops and returns `None`.
  - `RagRetrievalService.__init__(..., reranker: RagRerankerService | None = None)`. `_RankedChunk` gains `rerank_score: float | None = None`.
- Retrieval rule (decided here): when `settings.rag_reranker_enabled` and scores come back, reorder only the first `rag_reranker_candidates` items of `ranked` by `rerank_score` descending. Ties keep their prior order, and the rest stay in their existing order after them. The min-similarity / `keyword_specific` filter then runs **unchanged**, so the reranker can reorder chunks but never let in one that today's rules reject. Log `rag_rerank` with `applied`, `candidates`, `duration_ms`.

- [ ] **Step 1: Write the failing reranker unit tests** in `tests/test_rag_reranker_service.py`, using a fake `loader` returning an object with `predict(pairs) -> list[float]`:
  - `test_reranker_skips_while_model_loading`: the loader blocks on a `threading.Event`, so `score(...)` returns `None` at once (in under 50 ms). After the event is set and the thread joins, it returns scores.
  - `test_reranker_returns_none_over_budget`: `predict` sleeps 30 ms per batch, 12 texts, `budget_ms=40` → `None`.
  - `test_reranker_returns_none_when_load_fails`: the loader raises → `None`, and later calls do not retry in a loop (the loader is called once).
  - `test_reranker_scores_align_with_texts`: `predict` returns `len(text)` for each pair → the scores equal the text lengths in input order.

- [ ] **Step 2: Write the failing retrieval tests** in `tests/test_rag_retrieval_service.py`, with a fake reranker exposing `score`:
  - `test_reranker_reorders_top_candidates`: three seller vector rows above the similarity floor; the fake scores them in reverse → returned order is reversed.
  - `test_reranker_none_keeps_hybrid_order`: the fake returns `None` → order equals the flag-off run.
  - `test_reranker_flag_off_is_never_called`.
  - `test_reranker_cannot_admit_below_floor`: a row below `rag_min_similarity` given the top rerank score is still excluded.
  - `test_reranker_only_sees_seller_chunks`: another seller's rows in the fake repo never appear in the texts passed to `score`.

- [ ] **Step 3: Run them to confirm they fail.** Run `venv/bin/python -m pytest tests/test_rag_reranker_service.py tests/test_rag_retrieval_service.py -q -k rerank`. Expected: FAIL.

- [ ] **Step 4: Implement** the service, the settings plus `.env.example` lines (all off, defaults from the table) and the retrieval hook. Pass `settings.rag_reranker_budget_ms` as the budget.

- [ ] **Step 5: Run the tests to confirm they pass, plus the existing suites.** Run `venv/bin/python -m pytest tests/test_rag_reranker_service.py tests/test_rag_retrieval_service.py tests/test_rag_prompt_and_answer_service.py tests/test_copilot_tool_registry.py -q`. Expected: all pass.

- [ ] **Step 6: Measure, with the real model on the target CPU.** Warm the model first: one throwaway harness call, then wait for loading. Run `--configs baseline,translation,reranker`, where `reranker` includes translation if Task 2 passed its gate. **Gate:** overall recall@5 up by at least 5 points, `en` recall@12 not down, and retrieval p95 at or below 2500 ms. Otherwise leave it off and record the numbers.

- [ ] **Step 7: Deployment check before enabling anywhere.** Confirm the API host or image has disk for the model (about 2.3 GB in the Hugging Face cache) and that `scripts/check_local_setup.py` or the deploy notes mention pre-downloading it. Add a line to `docs/copilot/rag-retrieval-eval.md`. No code change if nothing is missing.

- [ ] **Step 8: Lint and types** on the changed files. Expected: clean. Leave the changes uncommitted.

---

### Task 4: Ranked full-text keyword search

**Precondition (user decision, blocks this task):** `alembic heads` currently reports two heads: `o9c0d1e2f3a4` and `p0d1e2f3a4b5`. Two existing files share revision `o9c0d1e2f3a4` (`…add_pooled_category_estimation_method.py`, `…add_business_finance_and_store_metrics.py`). Ask the user how to resolve this; do not edit existing migrations without approval. Set the new migration's `down_revision` to the single head that results.

**Files:**
- Create: `backend/alembic/versions/q1a2b3c4d5e6_add_rag_chunk_fulltext_index.py`
- Modify: `backend/app/repositories/rag_memory_repository.py:280` (`keyword_search`)
- Modify: `backend/app/services/rag_retrieval_service.py:294` (`keyword_search_optional` passes `ranked=`)
- Modify: `backend/app/core/config.py`, `.env.example` (`rag_fulltext_keyword_enabled`)
- Modify: `backend/tests/test_rag_retrieval_service.py` (`FakeRepository.keyword_search` already takes `**kwargs`, so no change is needed there)
- Test: `backend/tests/test_rag_retrieval_service.py` (SQL compiled through the existing `CaptureSession`)

**Interfaces:**
- Produces: `RagMemoryRepository.keyword_search(..., ranked: bool = False)`. With `ranked=False`, the SQL is exactly today's ILIKE query.
  - With `ranked=True`, the predicate is `func.to_tsvector('simple', RagMemoryChunk.chunk_text).op('@@')(tsq)`. `tsq` combines `func.plainto_tsquery('simple', term)` for each term with the `||` operator, so terms are always bound parameters and never parsed as tsquery syntax.
  - Ordering is `func.ts_rank_cd(tsv, tsq).desc()`, then `event_time desc nullslast`, then `id`. Every existing seller, status, product, source-type and time filter stays identical.
- Migration: create the index with `op.get_context().autocommit_block()`. The SQL is `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_rag_memory_chunks_chunk_text_fts ON rag_memory_chunks USING gin (to_tsvector('simple', chunk_text))`. Downgrade runs `DROP INDEX CONCURRENTLY IF EXISTS` on the same name. The `'simple'` config means no stemming and handles Bengali-script tokens.

- [ ] **Step 1: Write the failing tests** (compile with `postgresql.dialect()` and `literal_binds=False`):
  - `test_fulltext_sql_uses_index_expression_and_rank`: the SQL contains `to_tsvector`, `plainto_tsquery`, `ts_rank_cd`, and the user terms appear only in params.
  - `test_fulltext_sql_is_seller_scoped`: the compiled WHERE contains the `seller_id` predicate and `deleted_at IS NULL` for both chunk and document.
  - `test_fulltext_skips_query_without_terms`: `keywords=["", "  "]` → `[]` with no `execute` call.
  - `test_ilike_path_unchanged_when_flag_off`: the existing `test_keyword_search_uses_bound_parameters_for_user_terms` still passes, and the service passes `ranked=False` by default.

- [ ] **Step 2: Run them to confirm they fail.** Run `venv/bin/python -m pytest tests/test_rag_retrieval_service.py -q -k fulltext`. Expected: FAIL (unexpected keyword `ranked`).

- [ ] **Step 3: Implement** the repository branch, the service flag passthrough (`ranked=settings.rag_fulltext_keyword_enabled`), the settings and `.env.example` line, and the migration.

- [ ] **Step 4: Run the tests to confirm they pass, plus the existing suites.** Run `venv/bin/python -m pytest tests/test_rag_retrieval_service.py tests/test_rag_memory_foundation.py tests/test_copilot_tool_registry.py -q`. Expected: all pass.

- [ ] **Step 5: Apply the migration to the local DB and check it.** Run `venv/bin/alembic upgrade head`, then `venv/bin/alembic downgrade -1 && venv/bin/alembic upgrade head`. Expected: no errors, and `\d rag_memory_chunks` shows `ix_rag_memory_chunks_chunk_text_fts`. **Only on the local dev database; never reset it.**

- [ ] **Step 6: Measure.** Run `--configs baseline,…,fulltext`, with full-text on top of whichever earlier flags passed. **Gate:** recall@12 not down in any language, and the keyword query p95 lower than with ILIKE. Use `EXPLAIN ANALYZE` on one representative query and record whether the GIN index is used.

- [ ] **Step 7: Lint and types** on the changed files. Expected: clean. Leave the changes uncommitted.

---

### Task 5: Group diversity cap (only if Task 1 shows crowding)

**Gate to start:** in the Task 1 or latest report, the mean `top_group_share@12` is above 0.5 **and** at least 3 missed cases have their expected chunk crowded out by one `(source_type, product)` group. Otherwise record "not needed" in the eval doc and skip this task.

**Files:**
- Modify: `backend/app/services/rag_retrieval_service.py` (after the min-similarity filter :194, before `selected = filtered[:top_k]` :199)
- Modify: `backend/app/core/config.py`, `.env.example` (`rag_max_chunks_per_group`, default `0`)
- Test: `backend/tests/test_rag_retrieval_service.py`

**Interfaces:**
- Produces: `def _cap_per_group(items: list[_RankedChunk], max_per_group: int) -> list[_RankedChunk]`. Group key is `(chunk.source_type, chunk.product_id)`. It keeps order and the first `max_per_group` items per key, then appends the skipped items in order, so they still fill `top_k` if nothing else qualifies. `max_per_group <= 0` returns `items` unchanged.

- [ ] **Step 1: Write the failing tests:** `test_group_cap_zero_is_identity`; `test_group_cap_promotes_other_groups` (5 items in group A ranked above 1 in group B, cap 2 → B is third); `test_group_cap_backfills_when_only_one_group` (only group A, cap 2, `top_k` 4 → 4 returned).
- [ ] **Step 2: Run them to confirm they fail.** Run `venv/bin/python -m pytest tests/test_rag_retrieval_service.py -q -k group_cap`. Expected: FAIL.
- [ ] **Step 3: Implement** the function and the setting; apply it only when `settings.rag_max_chunks_per_group > 0`.
- [ ] **Step 4: Run the tests to confirm they pass, plus the existing RAG suites.** Expected: all pass.
- [ ] **Step 5: Measure** with `RAG_MAX_CHUNKS_PER_GROUP=3`. **Gate:** recall@12 up, MRR not down. Record the result. Leave the changes uncommitted.

---

### Task 6: Rollout record and full verification

**Files:**
- Modify: `docs/copilot/rag-retrieval-eval.md`
- Modify: `docs/current-chat-implementation-summary.md` (one short section listing the new flags and what each does)

- [ ] **Step 1:** In `rag-retrieval-eval.md`, write a table with one row per flag: measured gain, latency, gate pass/fail and recommended env value. Note the rollout order: translation → reranker → full-text → group cap, each enabled separately in staging with the harness re-run after each.
- [ ] **Step 2: Full regression.** Run `venv/bin/python -m pytest tests/ -q -k "rag or copilot"` with **all new flags off**, then again with every flag that passed its gate set on through env. Expected: both runs green; record the actual counts and any failures in the doc.
- [ ] **Step 3: Lint and types over every changed file.** Run `venv/bin/ruff check` and `venv/bin/mypy`. Expected: clean; record the outcome.
- [ ] **Step 4: Review the complete diff** (`git diff` plus the new files) against the Global Constraints. Leave everything uncommitted and give the user a short summary of the files changed and the flag recommendations.

---

## What this plan deliberately does not do

- No multi-query LLM rewrites, concept graph, chunk compression or figure handling from the Edtech project. They add model calls and latency without fitting short structured business records.
- No re-embedding or re-chunking of existing memory, and no change to `/rag/ask`, the answer prompt, the validator or the orchestrator flow.
- No switch of the embedding model or vector metric (`rag_cosine_distance_enabled` stays the user's existing choice).
