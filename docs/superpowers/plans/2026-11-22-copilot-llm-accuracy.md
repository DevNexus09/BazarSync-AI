# Copilot LLM Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LLM Copilot answer generic seller questions (Banglish, English) correctly from live data, without template answers, so it stays right when the database changes.

**Architecture:** Fix the pipeline at each point where the trace showed it breaking:
1. A Dhaka-time period resolver gives every tool and the prompt the same explicit period.
2. The LLM chooses a few precise tools first; the deterministic planner becomes the fallback.
3. The generic records tool gains the breakdowns and sorts the LLM was missing.
4. Facts that answer the question are never truncated.
5. Validator rules stop rejecting true answers.
6. The no-model fallback answers from the right facts.

The template "direct answer" layer from the previous session is removed.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2, PostgreSQL (SQLite in unit tests), pydantic v2, existing `app.ai.llm.router` (Gemini / OpenRouter / Groq / OpenAI routes).

**Spec:** The diagnosis below (section "Diagnosis — why answers are wrong"). Evidence: a traced run of 20 questions on the LLM path, with the direct layer off. Only about 6 of 20 were correct.

## Diagnosis — why answers are wrong

| # | Cause | Evidence from the trace |
|---|---|---|
| D1 | Banglish/English relative periods are not parsed: `last 7 din`, `ei shoptahe`, `October`, `prothom 15 din`. With no period, `question_planner._dated_args` defaults revenue, profit and trend tools to **today in UTC**, while metric queries default to all time. The LLM therefore sees facts that contradict each other. | "Last 7 din revenue" → ৳17,200.04 (true ৳93,503). "Ei shoptahe koyta order" → "not recorded, gross ৳2,392,878". |
| D2 | The planner runs 6–10 loosely related tools. Some vocabulary is missing or wrong: `dami` is mapped to "top", so the planner fetches top-by-revenue. | "Total stock koto unit?" ran revenue, trends, competitor, SEO and visibility tools. "Sobcheye dami product" → VENUS ৳674 (true: Power XORISE ৳3,374). |
| D3 | The fact budget (4,000 chars per tool, 20,000 total) cuts the facts that answer the question. | Truncation happened in 20/20 runs. `get_product_profile` was cut for a stock question; `get_revenue_summary` was cut for a returns question, so the reply said "no returns" (there were 4 units returned). |
| D4 | Tools are missing the needed breakdowns: list sorted by a measure, group by weekday/district/customer, cancelled or returned sales, expenses, listings and ratings, store rating. The `current_inventory_value` metric call failed. | "Best day" → 1 Aug ৳31,468 (true: 31 Jul ৳33,676). "Inventory value" → "not recorded". |
| D5 | The validator rejects true answers. A "no sales" claim needs `get_products_with_no_sales`; `get_business_overview` does not count as financial evidence. | "Gotokal kono sales hoyni" (true) was rejected. The business-overview answer was rejected. |
| D6 | Free model routes fail: Gemini Flash-Lite returns 503, the free OpenRouter Gemma is rate-limited. When they do answer, they sometimes pick the wrong number. | 7/20 calls had all routes fail. "October profit ৳595,658" (true ৳144,765). |
| D7 | The fallback lists rows from every tool under a Bangla-script header, plus a false "No sales recorded" line from the today-only default. | Every failed call produced the same unrelated risk list. |
| D8 | The template layer (`direct_answers.py`) matches keywords, so it breaks on new wording. | The user's pasted cases: "listed" was answered as a product count; "per product wise" got the all-time total, in English. |

## Global Constraints

- Follow `AGENTS.md`. Seller identity comes from the authenticated context, never from tool arguments. Migrations are additive only. Use Decimal for money. Distinguish unavailable evidence from an observed zero. Nothing changes live price or stock. Run tests, lint and type checks, and record the outcomes.
- The LLM explains verified facts only. Every number in an answer must exist in the tool facts (the existing `allowed_numbers` rule stays).
- The seller's calendar is `Asia/Dhaka`. The week starts on Monday (the existing `last week` rule). The Bangladesh weekend is Friday and Saturday.
- Keep the bug fixes and demo data from the previous session:
  - `snapshots.latest_per_product`, the dead-stock summary and metric fixes
  - `_source_row_payload` via `inspect(row).mapper`
  - `simulate_price_change` with elasticity and fees
  - migration `o9c0d1e2f3a4`
  - `scripts/seed_copilot_demo_extras.py`
- Do not add dependencies. Add no paid model route without the user's explicit choice (Task 8).
- Existing `/copilot/ask` request and response contracts stay unchanged.

## Review Focus

1. **A question with no period** ("Amar average order value koto?"): every tool uses the same stated default period, and the answer names it. → test in Task 2.
2. **A month name without a year:** "December" asked in November 2026 means December 2025; "October" means October 2026. → test in Task 2.
3. **Seller isolation for the new breakdowns:** customer, district and expense groups never include another seller's rows. → test in Task 3.
4. **Every LLM route down:** the reply still answers from the question's own tool, in Latin-script Banglish, with no unrelated rows. → test in Task 7.
5. **Mixed Banglish/English** ("per product wise sales unit ar sales record dao"): the period, the tools and the reply stay correct whichever language is detected. → held-out case in Task 9.

---

### Task 1: Remove the template direct-answer layer

**Files:**
- Delete: `backend/app/services/copilot/direct_answers.py`, `backend/tests/test_copilot_direct_answers.py`
- Modify: `backend/app/services/copilot/orchestrator.py`: remove the `_direct_answer`, `_direct_answer_payload` and `direct_answers_enabled` wiring, and restore the original blocked/clarification branch
- Modify: `backend/app/core/config.py`, `.env.example`, `backend/.env`: remove `COPILOT_DIRECT_ANSWERS_ENABLED`
- Create: `backend/tests/test_copilot_previous_fixes.py`: move the three bug-fix tests (`test_dead_stock_summary_uses_only_each_products_latest_run`, `test_price_simulation_applies_elasticity_and_fees`, `test_competitor_event_metadata_column_serializes`) out of the deleted test file, unchanged.

- [ ] **Step 1:** Move the three tests into the new file.
- [ ] **Step 2:** Delete the layer and its wiring. Check: `grep -rn "direct_answer\|DIRECT_ANSWERS" backend .env.example` returns nothing.
- [ ] **Step 3:** Run `venv/bin/python -m pytest tests -q`. Expected: all pass (count = previous total − 11 deleted direct-answer tests).
- [ ] **Step 4:** Commit with the message `Copilot: remove template direct-answer layer; keep tool bug fixes`.

### Task 2: One Dhaka period resolver, used everywhere and shown to the LLM

**Files:**
- Modify: `backend/app/services/copilot/date_range_parser.py`
- Modify: `backend/app/services/copilot/question_planner.py:1262-1268` (`_dated_args`), `:1458` (`_today_utc`)
- Modify: `backend/app/services/copilot/context_builder.py` (`CopilotAnswerContext`, `to_prompt_payload`)
- Test: `backend/tests/test_copilot_date_range_parser.py` (create)

**Interfaces:**
- Produces: `CopilotDateRangeParser.parse(question) -> DateRangeParseResult`, now recognising the following. Matching works on the raw question and on `normalize_query(...).planning_text`.
  - `ajke`, `aj`, `today`
  - `gotokal`, `yesterday`
  - `last|goto|shesh|past N din|day|days|dine`
  - `ei shoptah*`, `this week` (Monday to today)
  - `goto shoptah*`, `last week`
  - `ei mash*`, `this month`
  - `gotomash`, `last month`
  - `ei bochor`, `this year`
  - English month names, with an optional `prothom|first N din|days`. A month name means the most recent such month that is not in the future, clamped to today.
- Produces: `default_period(today: date) -> ParsedDateRange`: from `today - 3650 days` to `today`, with `source_text="all recorded history (no period given)"`.
- Produces: `CopilotAnswerContext.resolved_period: dict | None` with keys `from_date`, `to_date`, `label`, `defaulted: bool`. It is emitted in `to_prompt_payload()` as `"period"`.
- Change: "today" is computed in `Asia/Dhaka`; `_today_utc` is no longer used for periods.

- [ ] **Step 1: Write the failing tests.** Fix `now = 2026-11-22 21:00 +06` and check these cases:
  - `"Last 7 din e amar revenue koto?"` → 2026-11-16..2026-11-22
  - `"Ei shoptahe koyta order paisi?"` → 2026-11-16..2026-11-22
  - `"October e amar estimated profit koto?"` → 2026-10-01..2026-10-31
  - `"December er sales"` → 2025-12-01..2025-12-31
  - `"November er prothom 15 dine"` → 2026-11-01..2026-11-15
  - `"Gotokal koto taka bikri hoise?"` → 2026-11-21..2026-11-21
  - `"Ei bochor e total revenue"` → 2026-01-01..2026-11-22
  - The existing ISO-pair behaviour is unchanged.
  - Planner test `test_no_period_uses_stated_default_for_every_dated_tool`: plan `"Amar average order value koto?"`. Every planned tool with `from_date` gets 2016-11-24..2026-11-22, and `plan.entities.date_range["source_text"]` contains "no period given".
- [ ] **Step 2:** Run `venv/bin/python -m pytest tests/test_copilot_date_range_parser.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the parser additions and `default_period`. Use `default_period` in `_dated_args` and for metric queries, so revenue tools and metric queries share one window. Set `resolved_period` in `CopilotContextBuilder.build` from `plan.entities.date_range`.
- [ ] **Step 4:** Run the new tests plus `tests/test_copilot_question_planner.py tests/test_copilot_multilingual.py`. Expected: PASS. Where an existing test asserted the old today-UTC default, update it and note why in the commit message.
- [ ] **Step 5:** Commit with the message `Copilot: Dhaka period resolver for Banglish/English periods; one stated default period`.

### Task 3: Records tool covers the breakdowns the LLM needs

**Files:**
- Modify: `backend/app/services/copilot/records_query.py`
- Modify: the `query_business_records` description in `backend/app/services/copilot/tool_registry.py`. List the entities, measures, groups and `order_by` so the model can choose correctly.
- Test: `backend/tests/test_copilot_records_query_tool.py`, `backend/tests/test_copilot_records_query_isolation.py`

**Interfaces:**
- Produces: these additions to `RecordsQueryArgs`:
  - `GroupBy` gains `"weekday"` (labels Monday–Sunday, plus `is_weekend` for Fri/Sat), `"district"` and `"customer"` (sales only).
  - `order_by: Literal["date", "measure"] = "date"`. With `aggregate="list"` and a `measure`, rows are sorted by that measure. With a group aggregate, groups are sorted by value.
  - `sales_status: Literal["valid", "cancelled", "all"] = "valid"` (sales only).
- Produces: new sales measures `returned_units` and `returned_value` (unit_price × returned + refunded-restocked units).
- Produces: new entities, each seller-scoped by its own `seller_id`:
  - `expenses` (`business_expenses`): measure `amount`, groups `expense_type` and `payment_status`, list fields including `due_date` and `counterparty`
  - `listings` (`product_marketplace_listings`): measures `rating` and `review_count`, list fields including `listing_status`
  - `store_metrics` (`marketplace_store_metrics`): list
  - `visibility` (`product_visibility_metrics`): measures `search_rank`, `impressions`, `conversion_rate`
- Produces: `products` gains the measure `inventory_value_at_cost` (cost × stock).

- [ ] **Step 1: Write the failing tests.**
  - `test_products_list_sorted_by_selling_price_desc_returns_most_expensive_first`
  - `test_sales_group_by_weekday_marks_friday_saturday_weekend`
  - `test_sales_group_by_day_sum_revenue_order_by_measure_desc_gives_best_day`
  - `test_cancelled_sales_status_counts_only_cancelled`
  - `test_returned_units_sum_this_month`
  - `test_expenses_due_supplier_sum`
  - `test_listings_min_rating`
  - Isolation: `test_customer_and_district_groups_exclude_other_seller` and `test_expenses_entity_is_seller_scoped`.
- [ ] **Step 2:** Run both test files. Expected: FAIL.
- [ ] **Step 3:** Implement using the existing `EntitySpec` and `Measure` pattern. Weekday and district keys follow `_group_key`; for `customer`, return counts per customer (the model computes repeat share from `count` groups).
- [ ] **Step 4:** Run both files. Expected: PASS.
- [ ] **Step 5:** Commit with the message `Copilot records tool: weekday/district/customer groups, measure ordering, returns/cancellations, expenses, listings, visibility`.

### Task 4: LLM chooses the tools first; the planner is the fallback

**Files:**
- Modify: `backend/app/services/copilot/orchestrator.py` (`ask`, `_select_tools`, `_run_agent_loop`)
- Modify: `backend/app/services/copilot/agent_loop.py` (`run_agent_loop` prompt)
- Modify: `backend/app/services/copilot/question_planner.py` (`_build_tool_steps` cap)
- Modify: `backend/app/core/config.py`: `copilot_fallback_max_tools: int = 4` (`COPILOT_FALLBACK_MAX_TOOLS`)
- Test: `backend/tests/test_copilot_agent_loop.py`, `backend/tests/test_copilot_orchestrator.py`

**Interfaces:**
- Consumes: `resolved_period` (Task 2) and the records-tool capabilities (Task 3).
- Changes:
  - With `COPILOT_AGENT_LOOP_ENABLED` on and a router configured, the seed is only the named-product profile (existing `_with_named_product_profile`) and the loop picks the tools.
  - If the loop returns no successful tool result (model unavailable or invalid), the orchestrator runs the planner's `tool_plan`, capped at `copilot_fallback_max_tools`, in planner order.
  - Results the model chose are marked primary: `ToolExecutionResult` stays unchanged, and the orchestrator passes `primary_tools: set[str]` to the answer engine.
- Changes to the loop prompt:
  - state the resolved period
  - "pick the fewest tools that answer exactly"
  - "use query_business_records for rankings, breakdowns, sorting and counts"
  - "never estimate a figure a tool can return"

- [ ] **Step 1: Write the failing tests.**
  - `test_loop_choices_run_without_planner_seed`: with a fake router choosing `query_business_records`, only that tool and the memory step run.
  - `test_planner_fallback_when_loop_model_unavailable_is_capped_at_four`.
  - `test_primary_tools_are_the_loop_choices`.
- [ ] **Step 2:** Run the agent loop and orchestrator test files. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the two files plus the whole `tests/test_copilot_*`. Expected: PASS.
- [ ] **Step 5:** Commit with the message `Copilot: model selects tools first; capped planner fallback`.

### Task 5: Fact budget keeps the answering facts whole

**Files:**
- Modify: `backend/app/services/copilot/context_builder.py:319` (`budget_facts`), `CopilotContextBuilder.build`
- Modify: `backend/app/services/copilot/hybrid_answer_engine.py` (`answer`): accept `primary_tools`
- Test: `backend/tests/test_copilot_hybrid_answer_engine.py` or the context-builder tests already present

**Interfaces:**
- Produces: `budget_facts(facts, *, tool_chars, total_chars, primary: set[str] = frozenset()) -> tuple[dict, list[str]]`.
  - Primary tools are placed first and each gets up to `max(tool_chars, total_chars // 2)`.
  - Non-primary tools fill what is left. Memory is still last.
  - A primary tool is never replaced by `_omitted`.

- [ ] **Step 1: Write the failing test** `test_primary_tool_never_omitted_when_secondary_tools_fill_budget`. Give a 9,000-char primary fact, three 8,000-char secondaries, `tool_chars=4000` and `total_chars=20000`. The primary is present and not `_omitted`; at least one secondary is truncated.
- [ ] **Step 2:** Run the test. Expected: FAIL.
- [ ] **Step 3:** Implement it, and thread `primary_tools` from the orchestrator into `CopilotHybridAnswerEngine.answer(..., primary_tools=...)`.
- [ ] **Step 4:** Run the test plus `tests/test_copilot_hybrid_answer_engine.py`. Expected: PASS.
- [ ] **Step 5:** Commit with the message `Copilot: prompt budget never drops the facts that answer the question`.

### Task 6: Validator accepts true claims backed by facts

**Files:**
- Modify: `backend/app/services/copilot/context_builder.py:157-159`
- Test: `backend/tests/test_copilot_hybrid_answer_engine.py` (validator cases)

**Interfaces:**
- `has_reliable_no_sales_evidence` becomes true when either of these succeeded for the resolved period:
  - `get_products_with_no_sales`, or
  - a sales lookup (`get_revenue_summary`, `get_sales_trends`, or `query_business_records` with `entity="sales"`) that returned `order_count == 0` or `row_count == 0`.

  Its facts must carry the latest recorded sale date. If that date is missing, the flag stays false.
- `has_financial_evidence` adds:
  - `get_business_overview`
  - `get_top_products_by_revenue`
  - `get_profit_summary`
  - `run_seller_metric_query` with a revenue/order/unit metric key
  - `query_business_records` with `entity="sales"`
- The numeric rule (`allowed_numbers`) is unchanged.

- [ ] **Step 1: Write the failing tests.**
  - `test_no_sales_claim_accepted_when_revenue_summary_for_period_is_zero`
  - `test_no_sales_claim_still_rejected_without_any_sales_lookup`
  - `test_overview_revenue_claim_accepted`
- [ ] **Step 2:** Run the tests. Expected: FAIL (the second one passes already).
- [ ] **Step 3:** Implement. Add `latest_recorded_sale_date` to `get_revenue_summary` and to `query_business_records` sales facts: the seller-scoped max `sold_at` in Dhaka time.
- [ ] **Step 4:** Run the validator tests plus `tests/test_copilot_strict_safety.py`. Expected: PASS.
- [ ] **Step 5:** Commit with the message `Copilot validator: accept zero-sales and overview claims backed by facts`.

### Task 7: The no-model fallback answers from the right facts

**Files:**
- Modify: `backend/app/services/copilot/answer_builder.py` (`CopilotAnswerBuilder.build`, `_answer_lines`, `_financial_lines`)
- Modify: `backend/app/services/copilot/hybrid_answer_engine.py` (`_fallback_payload`): pass `primary_tools` and `resolved_period`
- Test: `backend/tests/test_copilot_answer_builder.py`

**Interfaces:**
- `CopilotAnswerBuilder.build(..., primary_tools: set[str] = frozenset(), period: dict | None = None)`:
  - Lines come only from primary tools (all tools when the set is empty).
  - The header follows the reply language: Banglish uses Latin script (`"Apnar data theke:"`), Bangla uses Bengali script, English is `"From your data:"`.
  - The period label is included.
  - "No sales recorded" appears only under the Task 6 condition, followed by the latest recorded sale date.

- [ ] **Step 1: Write the failing tests.**
  - `test_banglish_fallback_uses_latin_header_and_only_primary_tool_rows`
  - `test_fallback_no_sales_line_names_last_recorded_sale_date`
  - `test_fallback_omits_inventory_risk_rows_for_a_sales_question`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `tests/test_copilot_answer_builder.py tests/test_copilot_hybrid_answer_engine.py`. Expected: PASS.
- [ ] **Step 5:** Commit with the message `Copilot fallback: answer from the question's own facts in the reply language`.

### Task 8: Reliable model route — decision needed

The current routes are `gemini:gemini-3.5-flash-lite,openrouter:google/gemma-4-31b-it:free`; all routes failed in 7 of 20 trace calls. The router already supports `groq:<model>`, `openai:<model>` and `anthropic:<model>`, and keys for Groq and OpenAI exist in `backend/.env`. No code is required, only a `COPILOT_LLM_ANSWER_ROUTES` change. **The user picks one before this task runs:**
- (a) Add `groq:<model>` as the third route. It's a free tier but has a token-per-minute limit, so set `COPILOT_PROMPT_TOTAL_CHARS` to fit it.
- (b) Put `openai:<model>` first. Paid; the most reliable option.
- (c) Keep the free routes only. Expect about a third of answers to come from the Task 7 fallback.

- [ ] **Step 1:** Set the chosen routes in `backend/.env`, and add a commented example line in `.env.example`.
- [ ] **Step 2:** Run `venv/bin/python -m pytest tests/test_copilot_llm_router.py -q`. Expected: PASS.

### Task 9: Evaluation that measures understanding, not phrasing

**Files:**
- Modify: `backend/tests/fixtures/copilot_banglish_100.json`. Expected facts become phrase-neutral: numbers, product, category and store names, with `any_of` covering Banglish and English wording ("no sales" / "bikri hoy nai" / "kono order nai").
- Create: `backend/tests/fixtures/copilot_banglish_heldout.json`: the user's 5 pasted questions plus 30 rephrasings never used during development (different word order, mixed English/Banglish, typos such as "bebsar", "kotogula"). Each has expected facts computed with SQL against the demo seller as of 2026-11-22.
- Modify: `backend/scripts/copilot_eval.py`: add `--as-of YYYY-MM-DD`, which builds the orchestrator with `CopilotQuestionPlanner(entity_resolver=..., now=<as-of 21:00 Asia/Dhaka>)`, so relative periods are reproducible.
- Modify: `docs/recommendation-engine-v2/implementation-progress.md`: record the runs.

- [ ] **Step 1:** Rewrite the 100 fixture facts. Check the facts against SQL. Do not take them from Copilot output.
- [ ] **Step 2:** Write the held-out fixture the same way.
- [ ] **Step 3:** Run `venv/bin/python scripts/copilot_eval.py --seller-id 6bbb309a-1795-498d-88d1-d546bd5b1ebc --fixture <each fixture> --as-of 2026-11-22 --pause 4 --verbose` for the 100, held-out and golden sets.
  - Target: ≥95% on each set, and every failure explained.
  - Any failure caused by a pipeline bug goes back to the owning task. A failure caused only by a route outage counts against Task 8.
- [ ] **Step 4:** Run `venv/bin/python -m pytest tests -q`, then `venv/bin/ruff check app tests scripts`, then `venv/bin/mypy` on the changed files. Record the outcomes and the error counts before and after in the progress doc.
- [ ] **Step 5:** Commit with the message `Copilot eval: phrase-neutral facts, held-out set, reproducible as-of date; record results`.
