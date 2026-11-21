# Business Copilot 2.x: multilingual chat and chat quality

The Copilot still works the same way. A deterministic, seller-scoped planner picks
read-only tools, a model explains only the facts those tools return, and a validator
rejects unsupported numbers, claims or evidence. Every addition below sits behind a flag
that is off by default. With all flags off, the request path matches the earlier release.
The only API difference is new optional response fields, which come back as null or empty.

## Flags

All flags are in `backend/app/core/config.py` and documented in `.env.example`.

| Flag | What it turns on |
|---|---|
| `COPILOT_MULTILINGUAL_ENABLED` | Bangla, English and Banglish detection, normalisation, reply-language prompts, script-aware validation, `language: "banglish"` on `/ask` |
| `COPILOT_LLM_ROUTER_ENABLED` + `COPILOT_LLM_ANSWER_ROUTES[_EN\|_BN\|_BANGLISH]` | Groq or Claude per reply language, with fallbacks inside one overall timeout |
| `COPILOT_CONVERSATION_MEMORY_ENABLED` | Last turns sent to the model as untrusted context, for follow-up questions |
| `COPILOT_ANSWER_REPAIR_ENABLED` | One corrective model call when the validator rejects an answer |
| `COPILOT_FOLLOW_UPS_ENABLED` | Template follow-up questions in each reply language |
| `COPILOT_PARALLEL_TOOLS_ENABLED` | Tools run in worker threads with their own sessions and an enforced deadline |
| `COPILOT_LLM_PLANNER_FALLBACK_ENABLED` | The model may pick up to 3 allowlisted read-only tools when the planner finds none |
| `COPILOT_STREAMING_ENABLED` | `POST /copilot/ask/stream` sends progress stages over SSE, then the validated answer |
| `COPILOT_STRICT_SAFETY_PLANNING_ENABLED` | Refuses prompt-injection and override requests (no tool or model runs; fixed reply in the seller's language), asks which product when a reference is unresolved, and labels recommendation questions. With it on, `scripts/evaluate_copilot.py` passes its production gate |
| `COPILOT_ASK_RATE_LIMIT_PER_MINUTE` | Per-seller limit on `/ask` and `/ask/stream` (0 = off) |
| `RAG_COSINE_DISTANCE_ENABLED` | Vector search uses `<=>`, which matches the existing `vector_cosine_ops` HNSW index |
| `RAG_QUERY_EMBEDDING_CACHE_SIZE` | Seller-scoped in-process cache of question embeddings (0 = off) |

Always on (no flag), because they only fix bugs or add routes:
- `/ask` returns 404 only when the conversation is missing.
- Prompts are capped (`COPILOT_PROMPT_*_CHARS`).
- Token usage is stored on assistant messages.
- "What should I do today?" keeps the Action Center tool inside the tool cap.
- Planning metadata keeps the language profile.
- The capabilities endpoint advertises `features`.
- The feedback endpoint is available.

## API additions

All additive:
- `POST /copilot/ask` accepts `language: "banglish"` when multilingual is on; otherwise it returns 422 `language_not_supported`. The response adds `reply_language`, `reply_script` and `suggested_follow_ups`. `language` stays `en` or `bn` for older clients.
- `POST /copilot/ask/stream` returns `text/event-stream`: `stage` events, then one `answer` event (same body as `/ask`) or one `error` event.
- `POST /copilot/messages/{message_id}/feedback` takes `{rating: "up" | "down", reason?, comment?}`. It stores one row per seller per message, and resubmitting updates that row.
- `GET /copilot/capabilities` now includes `features` (multilingual, languages, streaming, follow_ups, feedback, conversation_memory).

## Database

There is one additive migration, `n8b9c0d1e2f3_add_copilot_message_feedback`. It creates the table `copilot_message_feedback` and changes no existing table.

## Frontend

The chat widget:
- Shows a reply-language selector (Auto, English, বাংলা, Banglish), offering only the languages the backend reports.
- Renders Bengali text with a Bengali font and sets per-message `lang` attributes (`bn`, `bn-Latn`).
- Renders answers as Markdown using React elements only, never raw HTML.
- Shows readable domain and tool names.
- Has a New chat button and a conversation history panel.
- Keeps a question that failed to send, marks it, and offers Retry. Rate limits, timeouts, server errors and offline errors each get their own message.
- Offers Copy, Ask again, 👍/👎 feedback and follow-up chips on answers.
- Shows streaming progress when the backend advertises it.
- Handles Bangla IME input safely (including Safari's event order), closes with Esc from anywhere in the panel, and keeps Tab focus inside the panel.

## Suggested rollout

1. Apply the migration.
2. Turn on strict safety planning, multilingual, follow-ups and the rate limit.
3. Run the live answer evaluation (`docs/copilot/multilingual-eval.md`) for Groq and Claude. Then enable the router with the better route for `BN` and `BANGLISH`.
4. Turn on answer repair, conversation memory and streaming.
5. Turn on parallel tools and RAG cosine distance. Re-check `RAG_MIN_SIMILARITY`, since cosine similarity sits on a different scale from the old L2 score.
6. Turn on the model-assisted planner fallback last, and watch the `copilot_llm_planner_fallback` logs.
