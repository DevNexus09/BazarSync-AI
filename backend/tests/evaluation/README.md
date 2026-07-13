# Business Copilot Evaluation Suite

This suite evaluates broad seller questions without calling Groq. It uses the
existing Pydantic request contract, deterministic intent classifier, question
planner, metric catalog, tool registry, response validator, and RAG retrieval
service.

## Run

```bash
cd backend
venv/bin/python -m pytest -q tests/evaluation
venv/bin/python scripts/evaluate_copilot.py
```

The script prints a JSON scorecard and exits non-zero when a critical gate is
not satisfied. A failed production gate is an evaluation result, not a reason
to weaken the expected case.

## Dataset

The dataset contains 205 unique cases covering product, sales, inventory,
competitor, pricing, promotion, dead-stock, SEO, alerts, historical memory,
multi-domain diagnostics, Bangla, mixed-language, follow-up, ambiguity, and
prompt-injection questions. Each case records mode, expected domains, metrics,
tools, entities, dates, evidence categories, missing-data expectations, action
expectation, confidence range, and question style.

## Test layers

- Request contract and current/memory/both mode propagation
- Planner routing and scorecard generation
- Metric catalog/executor parity
- Tool allowlisting and bounded planning
- RAG seller, product, source, date, and stale-memory behavior
- Conversation/action safety expectations
- Answer numeric and evidence grounding validation

