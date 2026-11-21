"""Offline answer-quality evaluation for the Business Copilot (outside request handlers).

For each multilingual case it builds the real plan and fixed tool facts, asks the answer
model through the same engine the API uses (prompt, validator, optional repair), and
reports validator pass rate, fallback reasons, language/script match, unsupported-claim
rate, latency and token use per reply language.

Default is ``--dry-run``: a scripted model, no network, no cost. ``--live`` calls the
configured providers and spends money; pass ``--routes`` to compare models, for example:

    python scripts/evaluate_copilot_answers.py --live --routes anthropic:claude-opus-5-5 --limit 30
    python scripts/evaluate_copilot_answers.py --live --routes groq --limit 30

An optional ``--judge-route`` scores fluency and helpfulness (1-5) with a second model.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.llm import CopilotLLMRouter, JsonCompletionRequest, parse_routes  # noqa: E402
from app.ai.llm.anthropic_provider import AnthropicProvider  # noqa: E402
from app.ai.llm.groq_provider import GroqProvider  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services.copilot.copilot_response_validator import _script_matches  # noqa: E402
from app.services.copilot.hybrid_answer_engine import CopilotHybridAnswerEngine  # noqa: E402
from app.services.copilot.intent_classifier import CopilotIntentClassifier  # noqa: E402
from app.services.copilot.language import normalize_query  # noqa: E402
from app.services.copilot.tool_registry import ToolExecutionResult, ToolExecutionStatus  # noqa: E402
from tests.evaluation.copilot_evaluation_harness import EVALUATION_SELLER_ID  # noqa: E402
from tests.evaluation.copilot_language_dataset import FIXED_NOW, HELDOUT_CASES, LANGUAGE_CASES, LanguageCase  # noqa: E402
from tests.evaluation.copilot_language_harness import _plan  # noqa: E402

# One fixed, plausible tool result per domain. Money is BDT, as strings (Decimal on the backend).
FIXTURES: dict[str, tuple[str, dict[str, Any]]] = {
    "SALES_REVENUE": ("get_revenue_summary", {"gross_revenue": "48250.00", "previous_period_revenue": "61300.00", "order_count": 214, "currency": "BDT"}),
    "INVENTORY": ("get_inventory_risks", {"items": [{"product": "King Size Premium Bed Sheet", "days_of_cover": 3, "risk_level": "HIGH", "reorder_quantity": 40}]}),
    "COMPETITOR": ("get_competitor_threats", {"threats": [{"competitor": "Daraz Mall Seller X", "product": "Cotton Pillow Cover", "their_price": "420.00", "our_price": "495.00"}]}),
    "PRICING": ("get_pricing_recommendations", {"recommendations": [{"product": "Cotton Pillow Cover", "current_price": "495.00", "recommended_price": "465.00", "minimum_safe_price": "440.00"}]}),
    "PROFIT_MARGIN": ("get_profit_summary", {"estimated_profit": "9120.00", "margin_rate": "0.19", "currency": "BDT"}),
    "PROMOTION": ("get_promotion_recommendations", {"promotions": [{"product": "King Size Premium Bed Sheet", "promotion_type": "DISCOUNT", "discount_rate": "0.10"}]}),
    "DEAD_STOCK": ("get_dead_stock_recovery", {"recovery": [{"product": "Silk Cushion", "days_without_sales": 74, "locked_capital": "18600.00", "recovery_action": "BUNDLE"}]}),
    "RECOMMENDATIONS": ("get_today_actions", {"actions": [{"title": "Restock King Size Premium Bed Sheet", "priority": "HIGH"}]}),
    "ALERTS": ("get_unresolved_alerts", {"alerts": [{"title": "Low stock: King Size Premium Bed Sheet", "severity": "HIGH"}]}),
    "PRODUCT_CATALOG": ("get_product_setup_summary", {"product_count": 38, "products_missing_cost_count": 6}),
    "SEO_VISIBILITY": ("get_seo_opportunities", {"opportunities": [{"product": "Silk Cushion", "issue": "Weak title"}]}),
    "RAG_MEMORY": ("retrieve_business_memory", {"memory_chunks": [{"evidence_id": "rag:doc:1", "snippet": "Sales dropped 21 percent in March after a stockout."}]}),
    "BUSINESS_OVERVIEW": ("get_business_overview", {"product_count": 38, "gross_revenue": "48250.00", "stockout_risk_count": 3}),
}


def _tool_result(domain: str) -> ToolExecutionResult:
    name, data = FIXTURES[domain]
    evidence_id = data.get("memory_chunks", [{}])[0].get("evidence_id") if name == "retrieve_business_memory" else f"{name}:1"
    evidence = [{"evidence_id": evidence_id, "source_table": name, "source_id": "1"}]
    return ToolExecutionResult(
        tool_name=name,
        tool_version="v1",
        status=ToolExecutionStatus.SUCCEEDED,
        data={**data, "evidence": evidence, "missing_data": []},
        evidence=evidence,
        missing_data=[],
        error=None,
        runtime_ms=1,
    )


async def scripted_model(messages, **kwargs):
    """Dry-run stand-in: answers in the requested language using a number from the facts."""
    del kwargs
    payload = json.loads(messages[-1]["content"].split("\n", 1)[1])
    language = payload.get("language", "en")
    facts = payload.get("facts", {})
    tool, values = next(iter(facts.items()), ("data", {}))
    figure = next((str(value) for value in _flatten(values) if any(ch.isdigit() for ch in str(value)) and len(str(value)) > 1), "")
    evidence_id = (payload.get("evidence") or [{}])[0].get("evidence_id", "")
    label = tool.replace("_", " ")
    answers = {
        "en": f"From your {label} data, the key figure is {figure}. Check the evidence before you act.",
        "bn": f"আপনার {label} তথ্য অনুযায়ী মূল সংখ্যা {figure}। সিদ্ধান্ত নেওয়ার আগে প্রমাণগুলো দেখে নিন।",
        "banglish": f"Apnar {label} data onujayi main figure holo {figure}. Kono decision er age evidence ta dekhe nin.",
    }
    text = answers.get(language, answers["en"])
    return {
        "model": "scripted-dry-run",
        "content": {
            "answer": text,
            "summary": text,
            "confidence": "MEDIUM",
            "language": language,
            "evidence": [{"evidence_id": evidence_id}] if evidence_id else [],
            "missing_data": [],
            "recommended_next_steps": [],
        },
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _flatten(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _flatten(item)
    elif isinstance(value, list):
        for item in value:
            yield from _flatten(item)
    else:
        yield value


def _router(routes: str, *, dry_run: bool, timeout: float) -> CopilotLLMRouter:
    parsed = parse_routes(routes or "groq", default_groq_model=settings.copilot_groq_model or "scripted")
    providers: dict[str, Any] = {}
    if dry_run:
        providers = {"groq": GroqProvider(groq_json=scripted_model), "anthropic": GroqProvider(groq_json=scripted_model)}
    else:
        if any(route.provider == "groq" for route in parsed):
            providers["groq"] = GroqProvider()
        if any(route.provider == "anthropic" for route in parsed):
            providers["anthropic"] = AnthropicProvider(effort=settings.copilot_anthropic_effort, max_tokens=settings.copilot_anthropic_max_tokens)
    return CopilotLLMRouter(providers=providers, default_routes=parsed, timeout_seconds=timeout)


async def _judge(router: CopilotLLMRouter, case: LanguageCase, answer: str) -> dict[str, Any] | None:
    schema = {
        "type": "object",
        "properties": {"fluency": {"type": "integer"}, "helpfulness": {"type": "integer"}, "reason": {"type": "string"}},
        "required": ["fluency", "helpfulness", "reason"],
        "additionalProperties": False,
    }
    prompt = [
        {"role": "system", "content": "You grade a business assistant's answer for a Bangladeshi online seller. Score 1-5. Return JSON only."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "seller_question": case.question,
                    "expected_reply_language": case.reply_language,
                    "answer": answer,
                    "rubric": {
                        "fluency": "Natural for the expected language (Bangla script, Banglish in Latin letters, or English).",
                        "helpfulness": "Answers the question directly and gives a practical next step.",
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        result, _ = await router.complete_json(JsonCompletionRequest(messages=prompt, max_tokens=300, schema_hint=schema, json_schema=schema))
    except Exception:  # noqa: BLE001 - a judge failure is reported as missing, not fatal
        return None
    return {key: result.content.get(key) for key in ("fluency", "helpfulness", "reason")}


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    cases = [case for case in (HELDOUT_CASES if args.heldout else LANGUAGE_CASES) if not case.safety and case.domain in FIXTURES]
    if args.languages:
        wanted = set(args.languages.split(","))
        cases = [case for case in cases if case.reply_language in wanted]
    cases = cases[: args.limit] if args.limit else cases
    dry_run = not args.live
    router = _router(args.routes, dry_run=dry_run, timeout=args.timeout)
    judge = _router(args.judge_route, dry_run=False, timeout=args.timeout) if args.judge_route and not dry_run else None
    engine = CopilotHybridAnswerEngine(llm_router=router, timeout_seconds=args.timeout, repair_enabled=args.repair)
    classifier = CopilotIntentClassifier(now=FIXED_NOW, seller_timezone="Asia/Dhaka")

    rows = []
    for case in cases:
        planning_text = normalize_query(case.question).planning_text
        classification = classifier.classify(seller_id=EVALUATION_SELLER_ID, question=planning_text)
        plan = _plan(planning_text)
        started = time.monotonic()
        result = await engine.answer(
            question=case.question,
            classification=classification,
            plan=plan,
            tool_results=[_tool_result(case.domain)],
            missing_data=[],
            reply_language=case.reply_language,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        answer = result.payload.get("answer", "")
        row = {
            "case_id": case.case_id,
            "reply_language": case.reply_language,
            "validated": result.validation_error is None and result.model_id is not None,
            "repaired": result.repaired,
            "reason": result.validation_error,
            "script_ok": _script_matches(answer, case.reply_language),
            "latency_ms": latency_ms,
            "tokens": (result.token_usage or {}).get("total_tokens", 0),
            "served_by": result.model_id,
        }
        if judge is not None and row["validated"]:
            row["judge"] = await _judge(judge, case, answer)
        rows.append(row)
    return {"mode": "dry-run" if dry_run else "live", "routes": args.routes, "repair": args.repair, "summary": _summarize(rows), "cases": rows}


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["reply_language"]].append(row)
    summary = {}
    for language, items in sorted(groups.items()):
        reasons = Counter(_reason_code(item["reason"]) for item in items if item["reason"])
        latencies = [item["latency_ms"] for item in items]
        judged = [item["judge"] for item in items if item.get("judge")]
        summary[language] = {
            "cases": len(items),
            "validator_pass_rate": round(sum(item["validated"] for item in items) / len(items), 3),
            "repaired": sum(item["repaired"] for item in items),
            "script_match_rate": round(sum(item["script_ok"] for item in items) / len(items), 3),
            "unsupported_claim_rate": round(sum(count for code, count in reasons.items() if "Unsupported" in code or "unsupported" in code) / len(items), 3),
            "fallback_reasons": dict(reasons),
            "latency_ms_p50": int(statistics.median(latencies)),
            "latency_ms_p95": int(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]),
            "total_tokens": sum(item["tokens"] for item in items),
            "judge_fluency_avg": round(statistics.mean(j["fluency"] for j in judged if isinstance(j.get("fluency"), int)), 2) if judged else None,
            "judge_helpfulness_avg": round(statistics.mean(j["helpfulness"] for j in judged if isinstance(j.get("helpfulness"), int)), 2) if judged else None,
        }
    return summary


def _reason_code(reason: str) -> str:
    return reason.split(":", 1)[0].strip()[:80]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="Call the configured providers (costs money). Default: scripted dry run.")
    parser.add_argument("--routes", default="groq", help='Comma-separated "provider:model" routes, e.g. "anthropic:claude-opus-5-5,groq".')
    parser.add_argument("--judge-route", default="", help="Optional judge route (live only), e.g. anthropic:claude-opus-5-5.")
    parser.add_argument("--languages", default="", help="Filter reply languages, e.g. bn,banglish.")
    parser.add_argument("--limit", type=int, default=0, help="Evaluate at most N cases.")
    parser.add_argument("--heldout", action="store_true", help="Use the held-out case set.")
    parser.add_argument("--repair", action="store_true", help="Enable the single answer-repair attempt.")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", default="", help="Write the full JSON report to this path.")
    args = parser.parse_args()
    report = asyncio.run(evaluate(args))
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "routes", "repair", "summary")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
