# Task 18 · Evidence-grounded Bangla explanations

Set `RECOMMENDATION_EXPLANATION_ENABLED=true` on the API and workers to use this path. The flag defaults to false. The orchestrator remains authoritative when active. The legacy delivery path uses the existing evidence validator and deterministic business signals when Task 18 is enabled. The same recommendation action and confidence enums and `reasoning_bn` field serve both modes.

`ExplanationEvidence` contains the approved decision, selected supporting actions, known data times, reason codes, the MarginGuard verdict, and the forecast version and uncertainty status when available. It records verified values separately from estimates, and represents missing evidence explicitly. The application renders prices and order quantities directly. Seller text, product descriptions, and retrieved documents are excluded from the prompt.

The application commits the recommendation, its deterministic Bangla explanation, the job outcome where applicable, and the RAG outbox entry before attempting optional provider work. A provider failure leaves that completed recommendation available. Templates cover each action, insufficient evidence, unavailable forecasts, and MarginGuard rejection. They frame actions as advice and preserve validated supporting recommendations.

Set `RECOMMENDATION_EXPLANATION_GROQ_ENABLED=true` to allow optional Groq selection. The provider selects an approved Bangla sentence and references to supplied metrics. The response contains no free-text reasoning, decisions, confidence changes, or numerical values. Pydantic checks JSON and field types, and the renderer checks that the sentence belongs to the approved decision and that every referenced metric exists. The application then renders those values with Bangla digits and labels estimates. The validated wording and a new RAG outbox entry commit together. An early reader can see the verified template while Groq runs. The index builder reads the saved explanation and omits the legacy opportunity placeholder for Task 18 records.

The default explanation model is `openai/gpt-oss-20b`, which supports strict JSON Schema. `RECOMMENDATION_EXPLANATION_MODEL` and `RECOMMENDATION_EXPLANATION_TEMPERATURE` control the model and temperature. `RECOMMENDATION_EXPLANATION_TIMEOUT_SECONDS` defaults to four seconds for the entire call, including retries. `RECOMMENDATION_EXPLANATION_MAX_RETRIES` defaults to zero and allows up to two retries inside that deadline. The request limits completion output to 768 tokens. Logs record the explanation source, prompt version, and error type on failure. Provider access uses the existing backend Groq credential. [Groq structured outputs](https://console.groq.com/docs/structured-outputs)

Disable only the Groq flag to retain deterministic explanations with no provider calls. Disable the main flag to restore the previous generation path. Task 18 requires no migration.

## Verification

All 11 Task 18 cases passed within the 135-test focused regression. The tests covered strict schema, Bangla rendering, invalid JSON, Groq timeout and missing credentials, contradictory wording, unsupported metrics, missing evidence, MarginGuard rejection, injected product text, job replay, and indexing the validated explanation.

The full backend suite passed 1,032 tests and 809 subtests with disposable PostgreSQL and Redis. It reproduced the 24 existing Copilot failures and skipped three optional StatsForecast cases. Scoped Ruff and explanation-module mypy checks passed. A wider mypy check identified one existing dashboard summary typing issue. Provider requests used fixtures, so live Groq response quality and latency remain unverified.
