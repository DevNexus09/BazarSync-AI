# Copilot multilingual evaluation

Measured on 2026-11-21 against the code in this branch. Planner numbers come from
`tests/evaluation/test_copilot_language_evaluation.py` and need no model. Answer-quality
numbers need a live model and have **not been measured yet** (see the last section).

## Datasets

`backend/tests/evaluation/copilot_language_dataset.py` holds 150 cases plus 24 held-out cases.
The 205-case planner suite in `copilot_evaluation_dataset.py` is unchanged.

| Set | Cases | Notes |
|---|---|---|
| Bangla (Bengali script) | 60 | Sales, stock, competitors, pricing, profit, promotions, dead stock, today's actions, catalogue, visibility, memory, overview, 3 prompt injections |
| Banglish (romanised Bangla) | 60 | Same coverage, spelling variants (`kno`/`keno`, `bikroi`), code-switched nouns |
| Code-switched | 30 | Bangla and English in one question |
| Held-out | 12 Bangla + 12 Banglish | Written after the lexicon was tuned; never used to tune it |

## Planner results

"Raw" is the flag-off path: the question goes to the planner as typed. "Normalised" is
`COPILOT_MULTILINGUAL_ENABLED=true`: Banglish and Bangla business words also add their
canonical English planning terms.

| Set | Detection | Reply language | Routing raw | Routing normalised | Dates |
|---|---|---|---|---|---|
| Bangla | 100% | 100% | 70.0% | 100% | 100% |
| Banglish | 100% | 100% | 63.3% | 100% | 100% |
| Code-switched | 93.3% | 93.3% | 100% | 100% | 100% |
| Held-out Bangla | 100% | 100% | 66.7% | 83.3% | n/a |
| Held-out Banglish | 100% | 100% | 50.0% | 83.3% | n/a |

Prompt injections in every language planned no action tool (100%).

**Read the held-out rows as the real-world estimate.** The 100% routing on the main sets
is after tuning the lexicon on them. Held-out misses are idioms the lexicon does not
cover, for example "পড়ে থাকা মাল" (slow-moving goods) and "dokan er sob miliye
obostha" (overall shop status). The optional model-assisted planner fallback
(`COPILOT_LLM_PLANNER_FALLBACK_ENABLED`) is the intended safety net for such phrasing.

The two code-switched misses ("Show promotion result এর ROI.", "business summary দাও
today") are mostly English and get an English reply. This is a deliberate threshold:
under 15% Bengali-script letters counts as English.

The regression gates in the test file are: detection and reply language at or above 95%
(90% for code-switched), routing at or above 95% on the main sets, at or above 75% and
above raw on held-out, dates at or above 95%, and safety at 100%.

## Answer quality (not yet measured)

`backend/scripts/evaluate_copilot_answers.py` runs the real prompt, router, validator and
optional repair over the cases with fixed tool facts. It reports, per reply language:
validator pass rate, fallback reasons, script match rate, unsupported-claim rate, p50/p95
latency, tokens, and optionally an LLM judge's fluency and helpfulness scores (1-5).

The default dry run uses a scripted model. It checks the pipeline, not model quality, and
passes 143/143 cases. Live runs call paid APIs, so they are opt-in:

```bash
cd backend
python scripts/evaluate_copilot_answers.py --live --routes groq --limit 40 --output /tmp/groq.json
python scripts/evaluate_copilot_answers.py --live --routes anthropic:claude-opus-5-5 --limit 40 --output /tmp/claude.json
python scripts/evaluate_copilot_answers.py --live --routes anthropic:claude-opus-5-5 --repair --judge-route anthropic:claude-opus-5-5 --heldout
```

Use the per-language validator pass rate and the judge scores to set
`COPILOT_LLM_ANSWER_ROUTES_BN` / `_BANGLISH`, and record the results in this file.
