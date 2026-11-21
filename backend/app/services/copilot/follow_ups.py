"""Deterministic follow-up question suggestions, by intent and reply language.

Templates only: no model call, no seller data, no numbers. Each suggestion is a
question the planner already knows how to route.
"""

from __future__ import annotations

from app.services.copilot.intent_classifier import CopilotIntent

# (English, Bangla, Banglish)
_Suggestion = tuple[str, str, str]

_FOLLOW_UPS: dict[CopilotIntent, tuple[_Suggestion, ...]] = {
    CopilotIntent.RESTOCK_ADVICE: (
        ("Which products are closest to stocking out?", "কোন পণ্যের স্টক সবচেয়ে আগে শেষ হবে?", "Kon product er stock sobar age shesh hobe?"),
        ("Do I have dead stock tying up cash?", "আমার কি ডেড স্টক আছে?", "Amar ki dead stock ache?"),
    ),
    CopilotIntent.REVENUE_DIAGNOSIS: (
        ("Was inventory involved?", "স্টকের কারণে কি বিক্রি কমেছে?", "Stock er karone ki sales komeche?"),
        ("Which competitor is hurting me?", "কোন প্রতিযোগী আমার ক্ষতি করছে?", "Kon competitor amar khoti korche?"),
        ("What should I do today?", "আজ আমার কী করা উচিত?", "Aj amar ki kora uchit?"),
    ),
    CopilotIntent.COMPETITOR_THREAT_ANALYSIS: (
        ("Should I change my price?", "আমার কি দাম বদলানো উচিত?", "Amar ki dam change kora uchit?"),
        ("Which competitor is cheapest?", "কোন প্রতিযোগী সবচেয়ে কম দামে বিক্রি করছে?", "Kon competitor sobcheye kom dame bikri korche?"),
    ),
    CopilotIntent.TODAY_ACTIONS: (
        ("What should I restock?", "কী রিস্টক করা উচিত?", "Ki restock kora uchit?"),
        ("Why is revenue down last week?", "গত সপ্তাহে বিক্রি কেন কমেছে?", "Goto shoptahe sales keno komeche?"),
    ),
    CopilotIntent.PRICING_ADVICE: (
        ("Is my margin safe at the current price?", "বর্তমান দামে কি আমার মার্জিন নিরাপদ?", "Ekhonkar dame ki amar margin safe?"),
        ("Which competitor is hurting me?", "কোন প্রতিযোগী আমার ক্ষতি করছে?", "Kon competitor amar khoti korche?"),
    ),
    CopilotIntent.PROMOTION_ADVICE: (
        ("Which products should I promote?", "কোন পণ্যের প্রমোশন করা উচিত?", "Kon product er promotion kora uchit?"),
        ("Is my margin safe for a discount?", "ছাড় দিলে কি মার্জিন নিরাপদ থাকবে?", "Discount dile ki margin safe thakbe?"),
    ),
    CopilotIntent.DEAD_STOCK_RECOVERY: (
        ("How can I recover dead stock?", "ডেড স্টক কীভাবে বিক্রি করব?", "Dead stock kivabe bikri korbo?"),
        ("What should I restock instead?", "এর বদলে কী রিস্টক করব?", "Er bodole ki restock korbo?"),
    ),
    CopilotIntent.SEO_ADVICE: (
        ("Which listings need better titles?", "কোন লিস্টিংয়ের টাইটেল ভালো করা দরকার?", "Kon listing er title better kora dorkar?"),
    ),
}

_DEFAULT: tuple[_Suggestion, ...] = (
    ("What should I do today?", "আজ আমার কী করা উচিত?", "Aj amar ki kora uchit?"),
    ("What should I restock?", "কী রিস্টক করা উচিত?", "Ki restock kora uchit?"),
)

_ACTION_TO_ADVICE = {
    CopilotIntent.ACTION_REQUEST_PRICE_CHANGE: CopilotIntent.PRICING_ADVICE,
    CopilotIntent.ACTION_REQUEST_PROMOTION: CopilotIntent.PROMOTION_ADVICE,
    CopilotIntent.ACTION_REQUEST_REORDER_PLAN: CopilotIntent.RESTOCK_ADVICE,
    CopilotIntent.ACTION_REQUEST_SEO_FIX: CopilotIntent.SEO_ADVICE,
    CopilotIntent.ACTION_REQUEST_DEAD_STOCK_RECOVERY: CopilotIntent.DEAD_STOCK_RECOVERY,
}

MAX_FOLLOW_UPS = 3


def suggested_follow_ups(intent: CopilotIntent, *, reply_language: str, question: str = "") -> list[str]:
    intent = _ACTION_TO_ADVICE.get(intent, intent)
    index = {"en": 0, "bn": 1, "banglish": 2}.get(reply_language, 0)
    asked = " ".join((question or "").casefold().split())
    suggestions = [item[index] for item in _FOLLOW_UPS.get(intent, _DEFAULT)]
    # Never suggest the question the seller just asked.
    return [text for text in suggestions if " ".join(text.casefold().split()) != asked][:MAX_FOLLOW_UPS]
