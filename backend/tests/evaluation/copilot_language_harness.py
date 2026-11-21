"""Planner-level multilingual evaluation: detection, reply language, routing and dates.

No model is called. Routing is measured twice: on the raw question (the flag-off
path) and on the normalised planning text (the COPILOT_MULTILINGUAL_ENABLED path),
so the gain from Banglish/Bangla normalisation is visible as a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.copilot.entity_resolver import CopilotEntityResolver
from app.services.copilot.intent_classifier import CopilotIntentClassifier
from app.services.copilot.language import InputLanguage, normalize_query, resolve_language_profile
from app.services.copilot.question_planner import DOMAIN_TOOL_PRIORITIES, CopilotQuestionPlan, CopilotQuestionPlanner
from app.services.copilot.query_constraints import BusinessDomainKey
from app.services.copilot.tool_registry import CopilotToolRegistry

from tests.evaluation.copilot_evaluation_harness import EVALUATION_SELLER_ID, StaticProductSource
from tests.evaluation.copilot_language_dataset import FIXED_NOW, LANGUAGE_CASES, LanguageCase

ACTION_TOOL_PREFIXES = ("apply_", "execute_", "update_", "delete_", "set_")
EXTRA_DOMAIN_TOOLS: dict[str, tuple[str, ...]] = {
    "BUSINESS_OVERVIEW": ("get_business_overview",),
    "RECOMMENDATIONS": ("get_today_actions", "get_recommendation_summary", "get_alert_recommendation_summary"),
    "INVENTORY": ("get_restock_recommendations",),
    "PRICING": ("simulate_price_change", "get_margin_safety"),
    "DEAD_STOCK": ("get_dead_stock_recovery",),
    "SEO_VISIBILITY": ("get_seo_opportunities",),
}


@dataclass(frozen=True, slots=True)
class LanguageCaseResult:
    case: LanguageCase
    detected_input: str
    reply_language: str
    detection_ok: bool
    reply_ok: bool
    routed_raw: bool
    routed_normalized: bool
    date_ok: bool | None
    safe: bool | None


def _domain_tools(domain: str) -> set[str]:
    tools = set(EXTRA_DOMAIN_TOOLS.get(domain, ()))
    try:
        tools |= set(DOMAIN_TOOL_PRIORITIES.get(BusinessDomainKey(domain), ()))
    except ValueError:
        pass
    return tools


def _plan(question: str) -> CopilotQuestionPlan:
    classification = CopilotIntentClassifier(now=FIXED_NOW, seller_timezone="Asia/Dhaka").classify(
        seller_id=EVALUATION_SELLER_ID, question=question
    )
    return CopilotQuestionPlanner(
        entity_resolver=CopilotEntityResolver(product_source=StaticProductSource()),
        now=FIXED_NOW,
    ).plan(
        seller_id=EVALUATION_SELLER_ID,
        question=question,
        language=classification.language,
        conversation_history=[],
        product_id=None,
        from_date=None,
        to_date=None,
        top_k=8,
        include_memory=True,
        business_catalog=None,
        metric_catalog=None,
        tool_registry=CopilotToolRegistry(),
        classification_hint=classification,
        max_tools=10,
    )


def _routed(case: LanguageCase, plan: CopilotQuestionPlan) -> bool:
    tools = {step.tool_name for step in plan.tool_plan}
    if case.safety:
        return not any(name.startswith(ACTION_TOOL_PREFIXES) for name in tools)
    if case.domain in plan.required_domains:
        return True
    return bool(tools & _domain_tools(case.domain))


def _date_ok(case: LanguageCase, plan: CopilotQuestionPlan) -> bool | None:
    if case.date_range is None:
        return None
    date_range = plan.entities.date_range or {}
    return (date_range.get("from_date"), date_range.get("to_date")) == case.date_range


def evaluate_case(case: LanguageCase) -> LanguageCaseResult:
    profile = resolve_language_profile(case.question)
    detected = profile.input_language.value
    if case.input_language == InputLanguage.MIXED.value:
        detection_ok = detected in {InputLanguage.MIXED.value, InputLanguage.BN.value}
    else:
        detection_ok = detected == case.input_language
    raw_plan = _plan(case.question)
    normalized_plan = _plan(normalize_query(case.question).planning_text)
    routed_normalized = _routed(case, normalized_plan)
    return LanguageCaseResult(
        case=case,
        detected_input=detected,
        reply_language=profile.reply_language.value,
        detection_ok=detection_ok,
        reply_ok=profile.reply_language.value == case.reply_language,
        routed_raw=_routed(case, raw_plan),
        routed_normalized=routed_normalized,
        date_ok=_date_ok(case, normalized_plan),
        safe=routed_normalized if case.safety else None,
    )


def evaluate_language_dataset(cases: tuple[LanguageCase, ...] = LANGUAGE_CASES) -> tuple[dict[str, Any], list[LanguageCaseResult]]:
    results = [evaluate_case(case) for case in cases]
    report: dict[str, Any] = {"total_cases": len(results), "by_language": {}}
    for language in ("bn", "banglish", "mixed"):
        group = [result for result in results if result.case.input_language == language]
        if not group:
            continue
        dated = [result for result in group if result.date_ok is not None]
        report["by_language"][language] = {
            "cases": len(group),
            "detection_accuracy": _rate(result.detection_ok for result in group),
            "reply_language_accuracy": _rate(result.reply_ok for result in group),
            "routing_rate_raw": _rate(result.routed_raw for result in group),
            "routing_rate_normalized": _rate(result.routed_normalized for result in group),
            "date_accuracy": _rate(result.date_ok for result in dated) if dated else None,
        }
    safety = [result for result in results if result.safe is not None]
    report["safety_pass_rate"] = _rate(result.safe for result in safety) if safety else None
    report["failures"] = [
        {
            "case_id": result.case.case_id,
            "question": result.case.question,
            "detected": result.detected_input,
            "reply": result.reply_language,
            "routed": result.routed_normalized,
            "date_ok": result.date_ok,
        }
        for result in results
        if not (result.detection_ok and result.reply_ok and result.routed_normalized and result.date_ok is not False)
    ]
    return report, results


def _rate(values: Any) -> float:
    items = list(values)
    return round(sum(1 for item in items if item) / len(items), 4) if items else 0.0
