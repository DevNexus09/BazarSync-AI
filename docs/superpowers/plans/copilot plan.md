# Business Copilot Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Business Copilot answer any seller question about their own data accurately, with an OpenAI → Gemini → Groq fallback chain, a stronger RAG engine, no user-facing filters, and a premium chat UI.

**Architecture:** Keep the existing pipeline (orchestrator → tools → hybrid answer engine → validator) and its contracts. Replace keyword-only tool routing with a bounded LLM tool loop over the existing 52 allowlisted read-only tools plus one new generic seller-scoped records tool. Fix RAG scoring bugs, widen index coverage, and always retrieve memory. All new behavior sits behind default-off flags.

**Tech Stack:** FastAPI, SQLAlchemy, pgvector (HNSW cosine), Celery, `httpx` (already installed, no new deps), React 19, Tailwind 3, framer-motion, lucide-react.

**Spec:** this document (user request, 2026-11-22) + `AGENTS.md` + `docs/recommendation-engine-v2/compatibility-contract.md`.

## Inspection findings (why answers are inaccurate)

The model is **not** the main problem. `backend/.env` already runs `openai/gpt-oss-120b` on Groq (OpenAI's open-weight GPT model). The pipeline loses accuracy before the model sees anything:

1. **Keyword routing decides what data the model gets.** `CopilotIntentClassifier` + `CopilotQuestionPlanner` (1,500 lines of keyword rules) pick tools. A question phrased outside the keyword lists gets the wrong or no tools, and the LLM is told "use only supplied facts", so it answers "data unavailable" or answers from the wrong tool. The LLM fallback planner (`copilot_llm_planner_fallback_enabled`) is off and only fires when zero tools matched.
2. **One shot, no follow-up lookups.** The model can't ask for more data after seeing the first results. `copilot_max_iterations=3` exists in config but nothing uses it.
3. **Model may not calculate, and tools only return fixed summaries.** Questions like "average order value per day last week for category X" have no tool that computes them, so they fail. List tools cap at 25 rows.
4. **RAG uses the wrong distance.** The HNSW index is `vector_cosine_ops`, but `RAG_COSINE_DISTANCE_ENABLED=false` makes queries use L2 `<->` (`rag_memory_repository.py:229`). The index is skipped (slow scan) and `1/(1+d)` maps even unrelated chunks (cosine 0 → L2 1.41 → score 0.41) above `RAG_MIN_SIMILARITY=0.35`. Irrelevant memory reaches the prompt.
5. **RAG keyword search is dead weight.** Keyword-only hits get `similarity_score=0.0` plus at most `0.12` (`rag_retrieval_service.py:326,339`), then are dropped by the 0.35 floor (line 182). Exact matches on SKUs/product names never surface unless vector search already found them.
6. **Substring source-type filtering narrows search wrongly.** `_source_types_for_question` filters (not boosts) by substrings: "rank" matches "frankly", "action" matches "transaction", "order" routes to sales only. Relevant memory of other types is excluded.
7. **Memory is optional.** Retrieval runs only if the planner chose `retrieve_business_memory`, and the UI's source-mode filter can turn it off.
8. **No invoice/receipt tables exist.** The closest data: `sales_records` (orders), `inventory_stock_in` + `inventory_history` (purchase receipts), `product_price_history`, `promotions`, `alerts`, `recommendations`. "Invoices" can only mean those until real invoice data is imported (open question below).
9. **No accuracy measurement.** There is no golden question set, so "not perfectly accurate" can't be tracked or proven fixed.

## Global Constraints

- Seller identity comes only from the authenticated request; every tool, query, cache key and RAG call is seller-scoped in code, never by the LLM.
- No new Python dependencies; providers use `httpx` against OpenAI-compatible endpoints. Python 3.14.
- New behavior behind default-off flags: `COPILOT_AGENT_LOOP_ENABLED`, `COPILOT_ALWAYS_RETRIEVE_MEMORY`, `RAG_RRF_ENABLED`. Existing route `POST /copilot/ask` request/response shape unchanged; filter fields stay accepted (ignored by the new UI).
- LLM never sees raw SQL and never writes. No text-to-SQL. Recommendations/acknowledgment never change live price or stock.
- Money stays `Decimal` in tools; the LLM restates numbers, it doesn't compute them.
- Additive migrations only; no DB resets.
- API keys only in `backend/.env`; never logged.

## Review Focus

1. Free-tier 429 / quota exhaustion mid-loop → router falls to next provider with the remaining deadline; user still gets an answer or the deterministic fallback, never a 500.
2. Prompt injection inside product titles / RAG chunks asking the loop to call a tool with another seller's `product_id` → `verify_product_owned` blocks it; test asserts BLOCKED and no data.
3. LLM loop requests an unknown tool or invalid args → step skipped, loop continues, logged; no crash.
4. Question about data that truly doesn't exist (e.g. "invoices") → answer says it's not recorded and names the closest data, instead of inventing numbers.
5. Empty seller (new account, no rows) → every tool returns observed-zero vs unavailable distinctly; answer says "no sales recorded yet", not "0 revenue".

---

### Task 0: Baseline and golden eval set

**Files:**
- Create: `backend/scripts/copilot_eval.py`, `backend/tests/fixtures/copilot_golden_questions.json`

- [ ] Commit or stash the current uncommitted copilot WIP on `develop` first; branch `feature/copilot-robustness`.
- [ ] Write 40 golden questions against the comprehensive demo seed (`comprehensive_demo_seed_service.py`), each with `{question, language, expected_tools_any, expected_facts: [{"label", "value"}]}`. Cover: revenue by period/product/category, top/bottom products, stock levels, stock-ins ("what did I receive last week"), price history, competitors, promotions, dead stock, alerts, a Bangla and a Banglish question, an unanswerable one, an injection one.
- [ ] `copilot_eval.py --seller-id <uuid>` runs each question through `CopilotOrchestrator.ask` and prints per-question pass/fail (all expected values appear in the answer, normalized) and a total score. Write results to `backend/artifacts/copilot_eval/<timestamp>.json`.
- [ ] Run it on the current code; record the baseline score in `docs/recommendation-engine-v2/implementation-progress.md`.

### Task 1: OpenAI-compatible providers and fallback chain

**Files:**
- Create: `backend/app/ai/llm/openai_compat_provider.py`
- Modify: `backend/app/ai/llm/router.py` (`parse_route`, `build_router_from_settings`), `backend/app/core/config.py`, `.env.example`
- Test: `backend/tests/test_copilot_llm_router.py` (extend existing or create)

**Interfaces:**
- Produces: `OpenAICompatProvider(name: str, base_url: str, api_key: str)` implementing `LLMProvider.complete_json(request, *, model, timeout_s) -> LLMResult`. Raises `LLMProviderError(code="RATE_LIMITED"|"TIMEOUT"|"AUTH"|"INVALID_JSON"|"HTTP_<status>")`.
- Route strings: `openai:<model>`, `gemini:<model>`, `groq:<model>`, `anthropic:<model>`.

- [ ] Tests: `test_parse_routes_accepts_openai_and_gemini`, `test_router_falls_back_on_rate_limit` (fake openai raises RATE_LIMITED → gemini succeeds → attempts list has 2 entries), `test_router_skips_provider_without_api_key`, `test_openai_compat_parses_json_content` (mock `httpx.MockTransport` returning `choices[0].message.content='{"a":1}'`), `test_openai_compat_maps_429_to_rate_limited`.
- [ ] Implement: POST `{base_url}/chat/completions` with `response_format={"type":"json_object"}`, `httpx.AsyncClient(timeout=timeout_s)`, no internal retries (the router owns fallback). Base URLs from settings:
  - `OPENAI_BASE_URL` default `https://api.openai.com/v1`, key `OPENAI_API_KEY`. For a **free** GPT tier set `OPENAI_BASE_URL=https://models.github.ai/inference` with a GitHub token (GitHub Models). The OpenAI API itself has no free tier.
  - `GEMINI_BASE_URL` default `https://generativelanguage.googleapis.com/v1beta/openai`, key `GEMINI_API_KEY`.
  - Groq keeps the existing `GroqProvider`.
- [ ] Providers are registered only when their key is set. Recommended `.env`: `COPILOT_LLM_ROUTER_ENABLED=true`, `COPILOT_LLM_ANSWER_ROUTES=openai:openai/gpt-4.1,gemini:gemini-2.5-flash,groq:openai/gpt-oss-120b` (confirm current free model ids at setup; they change).
- [ ] Run tests, ruff, mypy; commit.

### Task 2: Fix RAG retrieval scoring

**Files:**
- Modify: `backend/app/services/rag_retrieval_service.py`, `backend/app/core/config.py`, `.env.example`
- Test: `backend/tests/test_rag_retrieval_service.py`

- [ ] Tests: `test_keyword_only_exact_sku_hit_is_returned` (chunk found only by keyword appears in results with `RAG_RRF_ENABLED=true`), `test_source_types_boost_not_filter` (question containing "order" still returns a relevant INVENTORY_HISTORY chunk), `test_cosine_threshold_drops_unrelated_chunk` (distance 0.9 → score 0.1 → dropped), `test_cross_seller_chunk_never_returned` (keep existing).
- [ ] Set `RAG_COSINE_DISTANCE_ENABLED=true` in `.env.example` and `backend/.env` (index already uses `vector_cosine_ops`; no migration). Set `RAG_MIN_SIMILARITY=0.45` for bge-m3 cosine, then tune with Task 0 eval.
- [ ] Behind `RAG_RRF_ENABLED`: in `hybrid_rank`, score = reciprocal rank fusion `1/(60+vector_rank) + 1/(60+keyword_rank)` plus existing boosts; apply the similarity floor only to vector-only items. Keyword-only items survive.
- [ ] Change `_source_types_for_question` callers so the result feeds `apply_source_type_weights` (boost 1.15×) instead of the SQL `source_types` filter. Explicit `source_types` passed by a caller still filter.
- [ ] Raise `RAG_RETRIEVAL_TOP_K` default to 12. Run tests + eval; commit.

### Task 3: Index all business records into RAG memory

**Files:**
- Modify: `backend/app/services/rag_memory_document_builder.py`, `rag_memory_source_registry.py`, `rag_memory_backfill_service.py`
- Test: `backend/tests/test_rag_memory_document_builder.py`

- [ ] Audit each `RagMemorySourceType` in the registry: for each, confirm a builder exists and the backfill covers it. Write the gap list into the PR description.
- [ ] Add a stock-in/purchase-receipt document (source `INVENTORY_LIFECYCLE` with `metadata_json.kind="stock_in"`): product title, SKU, quantity, unit cost (Decimal string + currency), supplier/note if present, received date. Add per-day sales digest docs (`SALES_HISTORY`) if not already per-day.
- [ ] Every document text starts with product title + SKU so keyword search hits them.
- [ ] Test: `test_stock_in_document_contains_sku_qty_cost_currency`, `test_document_ids_are_deterministic` (replay-safe, re-running backfill creates no duplicates).
- [ ] Run backfill for the demo seller via the existing Celery task; confirm `EMBEDDED` counts per source type. Commit.

### Task 4: Generic seller-scoped records query tool

**Files:**
- Modify: `backend/app/services/copilot/tool_registry.py` (register next to `run_seller_metric_query`)
- Test: `backend/tests/test_copilot_records_query_tool.py`

**Interfaces:**
- Produces tool `query_business_records` with args model `RecordsQueryArgs`:
  `entity: Literal["sales","stock_ins","inventory_history","price_history","promotions","alerts","recommendations","competitor_snapshots","products"]`, `product_id: UUID | None`, `category: str | None`, `marketplace: str | None`, `from_date/to_date: date | None`, `aggregate: Literal["list","count","sum","avg","min","max"] = "list"`, `measure: str | None` (allowlisted column per entity), `group_by: Literal["none","day","week","month","product","category","marketplace"] = "none"`, `sort: Literal["desc","asc"] = "desc"`, `limit: int = Field(50, ge=1, le=200)`.
- Returns `{rows, row_count, truncated, measure_unit, currency, source, freshness, calculation_version: "records_query_v1"}`.

- [ ] Tests: `test_sum_revenue_by_day_matches_sales_records` (Decimal exact), `test_other_seller_rows_excluded`, `test_unknown_measure_rejected_as_invalid_arguments`, `test_empty_range_returns_observed_zero_with_row_count_0`, `test_limit_truncation_flagged`.
- [ ] Implement with SQLAlchemy Core per entity: a dict `entity → (model, seller_column, date_column, allowed_measures, allowed_groups)`; seller filter always applied first. Read-only, `allowed_in_read_only_mode=True`.
- [ ] Commit.

### Task 5: Bounded LLM tool loop (agent mode)

**Files:**
- Create: `backend/app/services/copilot/agent_loop.py`
- Modify: `backend/app/services/copilot/orchestrator.py` (`ask`, after the safety/clarification block), `config.py`
- Test: `backend/tests/test_copilot_agent_loop.py`

**Interfaces:**
- Consumes: `CopilotLLMRouter.complete_json`, `tool_registry.list_tools()/validate_arguments()`, existing `_run_tools`/`_run_tools_concurrently`.
- Produces: `async def run_agent_loop(*, question, seeded_results: list[ToolExecutionResult], router, registry, execute: Callable[[list[PlannedToolCall]], Awaitable[list[ToolExecutionResult]]], max_iterations: int, max_tool_calls: int, deadline_s: float) -> list[ToolExecutionResult]`.

- [ ] Tests: `test_loop_requests_extra_tool_then_stops` (fake router turn 1 → `{"tool_calls":[{"name":"query_business_records",...}]}`, turn 2 → `{"done":true}`; result contains both seeded and new results), `test_loop_ignores_unknown_tool`, `test_loop_respects_max_tool_calls`, `test_loop_never_passes_seller_id_from_model` (model-supplied `seller_id` is stripped), `test_loop_stops_at_deadline_and_returns_seeded_results`, `test_flag_off_uses_existing_path` (orchestrator regression).
- [ ] Loop: deterministic planner's tools run first (seed). Then up to `copilot_max_iterations` turns: send question + tool catalogue (name, description, JSON schema) + compact summaries of results so far; model returns `{"tool_calls":[...]}` or `{"done":true}`. Uses JSON mode so it works the same across OpenAI/Gemini/Groq. Then the existing hybrid answer engine writes the answer from all results.
- [ ] With `COPILOT_ALWAYS_RETRIEVE_MEMORY=true`, add `retrieve_business_memory` to the seed for every non-blocked question.
- [ ] Update the answer system prompt: when facts are missing, say exactly what isn't recorded and name the closest available data.
- [ ] Run copilot test suites, eval; commit.

### Task 6: Remove filters (frontend + request)

**Files:**
- Delete: `frontend/src/components/copilot/CopilotFilterControls.tsx`, `CopilotProductFilter.tsx`, `copilot-filter-utils.ts`
- Modify: `frontend/src/components/copilot/CopilotWidget.tsx` (state at ~L513-518, render at ~L771-790), `frontend/src/services/copilot-service.ts:154-161`, tests `CopilotWidget.test.tsx`, `CopilotChatExperience.test.tsx`
- [ ] Widget sends only `question`, `conversation_id`, `requested_language`; service defaults `include_current_data=true`, `include_memory=true`, no domain/source filters. Backend contract unchanged.
- [ ] Update tests asserting filter UI; add `test sends no filters`. `npm run test`, `npm run lint`, `npm run build`. Commit.

### Task 7: Premium chat redesign

**Files:** `frontend/src/components/copilot/*` (Shell, Panel, MessageList, AssistantMessage, QuestionInput, EmptyState, SuggestedQuestions, copilot.css)

- [ ] Run the `impeccable:impeccable` skill to set the direction before coding; keep the app's existing tokens/fonts.
- [ ] Target: expandable side panel + full-page mode; streaming answers (`COPILOT_STREAMING_ENABLED=true`, stage chips "Understanding → Looking up sales → Writing"); answer card with headline number, short explanation, collapsible "Sources" (tools + RAG items with freshness); copy/regenerate/thumbs (existing `copilot_feedback` model); suggested follow-ups; markdown tables for lists; Bangla font fallback; keyboard (Enter send, Shift+Enter newline, Esc close); mobile full-screen sheet; dark mode; `prefers-reduced-motion`.
- [ ] Component tests for streaming states, error state, feedback click. Browser check in the preview at desktop + 375px. Commit.

### Task 8: Rollout

- [ ] Enable flags in `backend/.env`: router, `COPILOT_AGENT_LOOP_ENABLED`, `COPILOT_ALWAYS_RETRIEVE_MEMORY`, `RAG_RRF_ENABLED`, `RAG_COSINE_DISTANCE_ENABLED`, `COPILOT_CONVERSATION_MEMORY_ENABLED`, `COPILOT_STREAMING_ENABLED`.
- [ ] Re-run Task 0 eval; target ≥ 90% and no regression on any baseline-passing question. Record before/after in implementation-progress.md.
- [ ] Full backend + frontend suites, ruff, mypy, `tsc`. Review the complete diff.

## Open questions for the user

1. Invoices/receipts: there are no invoice tables. Are invoices stored elsewhere (Daraz exports, PDFs, another DB)? If so, an import path is a separate task.
2. Free GPT: GitHub Models (free, low rate limits) or a paid OpenAI key? Groq's `gpt-oss-120b` is already a free GPT model and could stay primary.
