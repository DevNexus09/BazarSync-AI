"""Deterministic strict-safety rules for Copilot planning (COPILOT_STRICT_SAFETY_PLANNING_ENABLED).

Three checks run on a finished plan, before any tool executes:

* prompt-injection / override requests are refused: no tools run, and the plan carries a
  ``PROMPT_INJECTION_BLOCKED`` safety flag;
* references the planner cannot resolve to one seller-owned entity ("the blue shirt",
  "which competitor is cheapest?" with no product) ask a clarifying question;
* recommendation-style questions are labelled ``RECOMMENDATION`` without changing the
  tools they plan.

Rules are plain patterns over the question (English, Bangla and Banglish). They decide
nothing about numbers or prices; they only stop, clarify or relabel.
"""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any

from app.services.copilot.language.normalizer import normalize_digits

BLOCKED_FLAG = "PROMPT_INJECTION_BLOCKED"

# (reason code, pattern). Patterns run on the case-folded, digit-normalised question.
_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CROSS_SELLER", re.compile(r"\b(every|all|other|another)\s+sellers?'?s?\b|\bseller scope\b|\bsellers\s+table\b")),
    ("RAW_SQL", re.compile(r"\bselect\s+\*|\bselect\b.+\bfrom\b|\braw sql\b|\bsql query\b|\b(drop|truncate)\s+table\b|\bchange the database\b|\bdelete\b.+\b(database|table|records)\b")),
    ("SYSTEM_EXECUTION", re.compile(r"\bos\.system\b|\bshell_exec\b|\bshell command\b|\barbitrary tool\b|\btool named\b|\brun (a |the )?command\b")),
    ("SECRET_REQUEST", re.compile(r"\b(system prompt|api key|passwords?|tokens?|secrets?|credentials?)\b|\breveal\b")),
    ("GUARD_OVERRIDE", re.compile(r"\b(ignore|bypass|disable|skip|override)\b.{0,40}\b(guard|marginguard|check|ownership|confirmation|rules?|instructions?|policy|safety|scope)\b")),
    ("UNCONFIRMED_EXECUTION", re.compile(r"\bwithout (confirmation|approval|asking|permission)\b|\bexecute\b.{0,40}\bimmediately\b")),
    ("FABRICATION", re.compile(r"\b(fabricate|make up|invent|fake)\b|\bpretend\b|\bas if it were\b|\bunsupported\b.{0,30}\bas if\b")),
    ("METRIC_OVERRIDE", re.compile(r"\bignore\b.{0,30}\b(failed|cancelled|canceled|returned)\b.{0,20}\borders\b")),
    ("RAW_PRIVATE_DATA", re.compile(r"\braw (customer )?(messages|data|records)\b")),
    # Bangla
    ("GUARD_OVERRIDE", re.compile(r"(নির্দেশ|নিয়ম).{0,12}(ভুলে|বাদ)|মার্জিন গার্ড.{0,12}বাদ|গার্ড বাদ")),
    ("CROSS_SELLER", re.compile(r"সব বিক্রেতা|অন্য বিক্রেতা")),
    ("UNCONFIRMED_EXECUTION", re.compile(r"অনুমতি ছাড়া")),
    # Banglish
    ("GUARD_OVERRIDE", re.compile(r"\b(instruction|rules?|niyom)\b.{0,15}\b(bhule|bad)\b|\bguard bad\b")),
    ("CROSS_SELLER", re.compile(r"\b(sob|onno) seller\b")),
    ("UNCONFIRMED_EXECUTION", re.compile(r"\b(permission|onumoti) (chara|chhara)\b")),
)

# A definite reference to one item the planner could not resolve.
_DEFINITE_ITEM_RE = re.compile(
    r"\b(the|that|this)\s+(?:[a-z0-9-]+\s+){0,2}(shirt|case|bundle|one|listing|item|sku|charger|variant|pack)\b"
    r"|\b(oi|ei) (product|jinish|listing)\b|ওই (পণ্য|জিনিস|লিস্টিং)"
)
# "the lowest listing quality score" ranks many items; it is not a reference to one.
_RANKING_WORDS = frozenset({"lowest", "highest", "best", "worst", "top", "most", "least", "cheapest", "biggest"})
_COMPETITOR_PRICE_RE = re.compile(r"\bcompetitors?\b.{0,30}\b(cheapest|lowest price|lowest-priced)\b|\b(cheapest|lowest price)\b.{0,30}\bcompetitors?\b")
_VAGUE_WEAKNESS_RE = re.compile(r"\b(category|categories)\b.{0,20}\b(weak|bad|poor|underperforming|worst)\b")
_MEASURE_WORDS = ("sales", "revenue", "profit", "margin", "stock", "inventory", "visibility", "price", "orders")

_RECOMMENDATION_RE = re.compile(
    r"\bneeds? restocking\b|\bwhat should i (restock|prioriti[sz]e|do|focus on)\b|\bwhat (promotion|discount|offer) should i\b"
    r"|\bshould i (restock|reorder|promote|discount)\b|\bprioriti[sz]e\b|\bki kora uchit\b|কী করা উচিত|কি করা উচিত"
)

_CLARIFY_TEXT = {
    "item": {
        "en": "Which product do you mean? Please give the exact product name or SKU.",
        "bn": "আপনি কোন পণ্যের কথা বলছেন? সঠিক পণ্যের নাম বা SKU লিখুন।",
    },
    "competitor": {
        "en": "For which product should I compare competitor prices? Please give the product name or SKU.",
        "bn": "কোন পণ্যের জন্য প্রতিযোগীদের দাম তুলনা করব? পণ্যের নাম বা SKU লিখুন।",
    },
    "weakness": {
        "en": "Weak in what way: sales, profit margin, stock or visibility?",
        "bn": "কোন দিক থেকে দুর্বল: বিক্রি, লাভের মার্জিন, স্টক নাকি ভিজিবিলিটি?",
    },
}


def injection_reason(question: str) -> str | None:
    text = normalize_digits(question).casefold()
    return next((code for code, pattern in _INJECTION_RULES if pattern.search(text)), None)


def clarification_reason(question: str, plan: Any) -> str | None:
    text = normalize_digits(question).casefold()
    entities = plan.entities
    has_product = bool(entities.products)
    if not has_product and any(
        not (_RANKING_WORDS & set(match.group(0).split())) for match in _DEFINITE_ITEM_RE.finditer(text)
    ):
        return "item"
    if _COMPETITOR_PRICE_RE.search(text) and not has_product and not entities.competitors:
        return "competitor"
    if _VAGUE_WEAKNESS_RE.search(text) and not any(word in text for word in _MEASURE_WORDS):
        return "weakness"
    return None


def apply_strict_safety(plan: Any, *, question: str) -> Any:
    """Return ``plan`` refused, turned into a clarification, or relabelled; or unchanged."""
    from app.services.copilot.question_planner import CopilotQuestionType

    reason = injection_reason(question)
    if reason is not None:
        execution_plan = dict(plan.execution_plan or {})
        execution_plan["tool_calls"] = []
        execution_plan["metric_queries"] = []
        return replace(
            plan,
            tool_plan=[],
            metric_plan=[],
            needs_clarification=False,
            clarification_question=None,
            memory_search_plan=replace(plan.memory_search_plan, enabled=False),
            safety_flags=[*plan.safety_flags, BLOCKED_FLAG, f"{BLOCKED_FLAG}:{reason}"],
            execution_plan=execution_plan,
        )

    if not plan.needs_clarification:
        clarify = clarification_reason(question, plan)
        if clarify is not None:
            language = "bn" if plan.language == "bn" else "en"
            return replace(
                plan,
                needs_clarification=True,
                clarification_question=_CLARIFY_TEXT[clarify][language],
                safety_flags=[*plan.safety_flags, f"{clarify.upper()}_AMBIGUITY"],
            )

    if plan.question_type in {
        CopilotQuestionType.GENERAL_BUSINESS,
        CopilotQuestionType.DIAGNOSTIC,
        CopilotQuestionType.ANALYTIC,
        CopilotQuestionType.LOOKUP,
        CopilotQuestionType.UNKNOWN,
    } and _RECOMMENDATION_RE.search(normalize_digits(question).casefold()):
        return replace(plan, question_type=CopilotQuestionType.RECOMMENDATION)
    return plan


def is_blocked(plan: Any) -> bool:
    return BLOCKED_FLAG in (plan.safety_flags or [])
