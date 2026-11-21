"""Per-language answer instructions for the Copilot explanation model.

The examples carry no digits on purpose: every number in an answer must come from
the supplied facts, and the validator rejects numbers it cannot trace.
"""

from __future__ import annotations

MULTILINGUAL_PROMPT_VERSION = "copilot-answer-v3-multilingual"

_SHARED_RULES = (
    "Keep product names, SKUs, marketplace names and competitor names exactly as written in the facts. "
    "Write every number with ASCII digits (0-9) exactly as it appears in the facts, with the same currency (BDT/Tk/৳) and units. "
    "Set the JSON field \"language\" to \"{reply_language}\"."
)

LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "en": (
        "Reply in clear, plain English for a small online seller in Bangladesh. "
        + _SHARED_RULES
    ),
    "bn": (
        "Reply in natural, colloquial standard Bangla written in Bengali script (বাংলা), the way a helpful business "
        "advisor talks to a Bangladeshi seller. Common business words such as stock, order, promotion or SKU may stay in "
        "English when sellers normally say them that way. Do not answer in English or in romanised Bangla. "
        + _SHARED_RULES
        + " Example style: \"গত সপ্তাহে আপনার বিক্রি কমেছে, কারণ <product> এর স্টক শেষ হয়ে গিয়েছিল। "
        "আজই রিস্টক প্ল্যানটি দেখে নিন।\""
    ),
    "banglish": (
        "Reply in Banglish: Bangla language written in Latin (English) letters, the way Bangladeshi sellers type in "
        "chat (for example \"apnar\", \"bikri\", \"komeche\", \"keno\", \"dekhun\"). Business words such as sales, price, "
        "stock, order and profit may stay in English. Do not use Bengali script and do not reply in plain English. "
        + _SHARED_RULES
        + " Example style: \"Goto shoptahe apnar sales komeche, karon <product> er stock shesh hoye gechilo. "
        "Aj-i restock plan ta dekhe nin.\""
    ),
}


def language_instruction(reply_language: str) -> str:
    template = LANGUAGE_INSTRUCTIONS.get(reply_language, LANGUAGE_INSTRUCTIONS["en"])
    return template.replace("{reply_language}", reply_language)
