"""Render Bangla explanations from validated decisions and bounded Groq selections."""

from decimal import Decimal
from typing import get_args

from app.ai.schemas import (
    ExplanationEvidence,
    ExplanationMetricKey,
    ExplanationSelection,
)
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction

ACTION_TEMPLATES = {
    "LOWER": (
        "দাম কমানোর পরামর্শ দেওয়া হচ্ছে।",
        "প্রস্তাবিত দামে পণ্যের মূল্য কমানোর বিষয়টি বিবেচনা করুন।",
    ),
    "RAISE": (
        "দাম বাড়ানোর পরামর্শ দেওয়া হচ্ছে।",
        "প্রস্তাবিত দামে পণ্যের মূল্য বাড়ানোর বিষয়টি বিবেচনা করুন।",
    ),
    "HOLD": ("আপাতত বর্তমান পরিকল্পনা বজায় রাখুন।", "পণ্যটির জন্য এখনই পরিবর্তনের পরামর্শ নেই।"),
    "REORDER": (
        "পণ্যটি পুনরায় অর্ডার করার পরামর্শ দেওয়া হচ্ছে।",
        "মজুত পূরণ করতে পণ্যটি আবার অর্ডার করার বিষয়টি বিবেচনা করুন।",
    ),
}
MARGIN_BLOCKED = (
    "মার্জিন বা মূল্যনীতির শর্ত পূরণ না হওয়ায় দাম পরিবর্তনের পরামর্শ নেই। বর্তমান দাম বজায় রাখুন।"
)
INSUFFICIENT = "পরিবর্তনের পক্ষে যথেষ্ট যাচাই করা তথ্য নেই। আপাতত বর্তমান পরিকল্পনা বজায় রাখুন।"
MODEL_UNAVAILABLE = (
    "চাহিদার পূর্বাভাস পাওয়া যায়নি। পরামর্শটি বর্তমানে যাচাই করা তথ্যের ভিত্তিতে দেওয়া হয়েছে।"
)
METRIC_LABELS = {
    "target_price": ("প্রস্তাবিত দাম", "টাকা"),
    "current_price": ("বর্তমান দাম", "টাকা"),
    "competitor_median": ("প্রতিযোগীদের দামের মধ্যক", "টাকা"),
    "available_units": ("বিক্রির জন্য উপলব্ধ মজুত", "ইউনিট"),
    "reorder_quantity": ("প্রস্তাবিত পুনরায় অর্ডারের পরিমাণ", "ইউনিট"),
    "daily_sales_rate": ("দৈনিক নিট বিক্রির হার", "ইউনিট"),
}
SUPPORT_TEMPLATES = {
    DeadStockRecoveryAction.SEO_FIX: "পণ্যের তালিকার তথ্য ও সার্চ দৃশ্যমানতা পর্যালোচনা করুন।",
    DeadStockRecoveryAction.MANUAL_REVIEW: "ধীরগতির মজুতের তথ্য হাতে যাচাই করুন।",
    DeadStockRecoveryAction.DISCOUNT: "আলাদাভাবে সীমিত ছাড়ের প্রস্তাবটি পর্যালোচনা করুন।",
    DeadStockRecoveryAction.FLASH_SALE: "স্বল্পমেয়াদি অফারের প্রস্তাবটি পর্যালোচনা করুন।",
    DeadStockRecoveryAction.BUNDLE: "বান্ডেল প্রস্তাবটি পর্যালোচনা করুন।",
}
_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def approved_sentences(evidence: ExplanationEvidence) -> tuple[str, ...]:
    if evidence.action == "HOLD":
        if evidence.margin_guard.status == "blocked":
            return (MARGIN_BLOCKED,)
        if not evidence.supporting_actions and evidence.missing_evidence:
            return (INSUFFICIENT,)
    return ACTION_TEMPLATES[evidence.action]


def selection_schema(evidence: ExplanationEvidence) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "bangla_explanation_selection",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "sentence_bn": {
                        "type": "string",
                        "enum": approved_sentences(evidence),
                    },
                    "metric_keys": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": get_args(ExplanationMetricKey),
                        },
                    },
                },
                "required": ["sentence_bn", "metric_keys"],
                "additionalProperties": False,
            },
        },
    }


def render_explanation(
    evidence: ExplanationEvidence,
    selection: ExplanationSelection | None = None,
) -> str:
    sentences = approved_sentences(evidence)
    keys = selection.metric_keys if selection is not None else []
    if selection is not None and (
        selection.sentence_bn not in sentences
        or any(key not in evidence.metrics for key in keys)
    ):
        raise ValueError(
            "Explanation contains an unsupported sentence or metric reference."
        )
    lines = [selection.sentence_bn if selection is not None else sentences[0]]
    if evidence.margin_guard.status == "approved":
        lines.append("প্রস্তাবিত দাম প্রযোজ্য মূল্যনীতি ও মার্জিনের শর্ত পূরণ করে।")
    if (
        evidence.action == "REORDER"
        and {"daily_sales_rate", "available_units"} <= evidence.metrics.keys()
    ):
        lines.append("উপলব্ধ মজুত ও নথিভুক্ত বিক্রির তথ্য এই পরামর্শের ভিত্তি।")
    if evidence.prediction_uncertainty == "unavailable":
        lines.append(MODEL_UNAVAILABLE)
    required: tuple[ExplanationMetricKey, ...] = ("target_price", "reorder_quantity")
    for key in dict.fromkeys((*required, *keys)):
        metric = evidence.metrics.get(key)
        if metric is None:
            continue
        label, unit = METRIC_LABELS[key]
        prefix = "আনুমানিক " if metric.provenance == "estimated" else ""
        value = format(
            metric.value.normalize() if metric.value else Decimal(0), "f"
        ).translate(_DIGITS)
        lines.append(f"{prefix}{label} {value} {unit}।")
    lines.extend(
        SUPPORT_TEMPLATES[action]
        for action in evidence.supporting_actions
        if action in SUPPORT_TEMPLATES
    )
    return " ".join(lines)
