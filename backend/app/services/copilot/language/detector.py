from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Iterable

from app.services.copilot.language.lexicon import ENGLISH_STOPWORDS, STRONG_BANGLISH_MARKERS, WEAK_BANGLISH_MARKERS
from app.services.copilot.language.normalizer import normalize_digits

LATIN_WORD_RE = re.compile(r"[a-z]+")
BANGLA_SCRIPT_THRESHOLD = 0.5
MIXED_SCRIPT_THRESHOLD = 0.15
MIN_CONFIDENT_SIGNAL = 1.0


class InputLanguage(str, Enum):
    EN = "en"
    BN = "bn"
    BANGLISH = "banglish"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ReplyLanguage(str, Enum):
    EN = "en"
    BN = "bn"
    BANGLISH = "banglish"

    @property
    def base_language(self) -> str:
        """The two-value language the existing pipeline, templates and API speak."""
        return "en" if self == ReplyLanguage.EN else "bn"

    @property
    def script(self) -> str:
        return "bengali" if self == ReplyLanguage.BN else "latin"


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    input_language: InputLanguage
    reply_language: ReplyLanguage
    confidence: str
    source: str
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_language": self.input_language.value,
            "reply_language": self.reply_language.value,
            "reply_script": self.reply_language.script,
            "confidence": self.confidence,
            "source": self.source,
            "signals": self.signals,
        }


def detect_input_language(text: str) -> tuple[InputLanguage, str, dict[str, Any]]:
    normalized = normalize_digits(text).casefold()
    bengali_letters = sum(1 for character in normalized if "ঀ" <= character <= "৿" and character.isalpha())
    latin_letters = sum(1 for character in normalized if "a" <= character <= "z")
    total_letters = bengali_letters + latin_letters
    words = LATIN_WORD_RE.findall(normalized)
    banglish_score = sum(1.0 for word in words if word in STRONG_BANGLISH_MARKERS) + sum(
        0.5 for word in words if word in WEAK_BANGLISH_MARKERS
    )
    english_score = float(sum(1 for word in words if word in ENGLISH_STOPWORDS))
    signals = {
        "bengali_letters": bengali_letters,
        "latin_letters": latin_letters,
        "banglish_score": banglish_score,
        "english_score": english_score,
    }
    if total_letters == 0:
        return InputLanguage.UNKNOWN, "LOW", signals

    bengali_share = bengali_letters / total_letters
    signals["bengali_share"] = round(bengali_share, 3)
    if bengali_share >= BANGLA_SCRIPT_THRESHOLD:
        return InputLanguage.BN, "HIGH" if bengali_share >= 0.8 else "MEDIUM", signals
    if bengali_share >= MIXED_SCRIPT_THRESHOLD:
        return InputLanguage.MIXED, "MEDIUM", signals

    if banglish_score >= MIN_CONFIDENT_SIGNAL and banglish_score >= english_score * 0.6:
        confidence = "HIGH" if banglish_score >= 2 and banglish_score > english_score else "MEDIUM"
        return InputLanguage.BANGLISH, confidence, signals
    if english_score >= MIN_CONFIDENT_SIGNAL:
        return InputLanguage.EN, "HIGH" if english_score >= 2 and banglish_score == 0 else "MEDIUM", signals
    # A few Latin words with no strong signal ("stock?", "ok", a product name).
    return (InputLanguage.BANGLISH if banglish_score > 0 else InputLanguage.EN), "LOW", signals


def resolve_language_profile(
    question: str,
    *,
    requested_language: str = "auto",
    recent_messages: Iterable[dict[str, Any]] | None = None,
) -> LanguageProfile:
    """Pick the reply language: explicit request, then confident detection, then the conversation's last reply."""
    input_language, confidence, signals = detect_input_language(question)
    requested = (requested_language or "auto").strip().lower()
    if requested in {item.value for item in ReplyLanguage}:
        return LanguageProfile(input_language, ReplyLanguage(requested), "HIGH", "REQUEST", signals)

    detected = _reply_for_input(input_language)
    if confidence == "LOW":
        previous = _previous_reply_language(recent_messages)
        if previous is not None:
            return LanguageProfile(input_language, previous, confidence, "CONVERSATION", signals)
    return LanguageProfile(input_language, detected, confidence, "DETECTED", signals)


def _reply_for_input(input_language: InputLanguage) -> ReplyLanguage:
    if input_language in {InputLanguage.BN, InputLanguage.MIXED}:
        return ReplyLanguage.BN
    if input_language == InputLanguage.BANGLISH:
        return ReplyLanguage.BANGLISH
    return ReplyLanguage.EN


def _previous_reply_language(recent_messages: Iterable[dict[str, Any]] | None) -> ReplyLanguage | None:
    for message in reversed(list(recent_messages or [])):
        if str(getattr(message.get("role"), "value", message.get("role")) or "").upper() != "ASSISTANT":
            continue
        metadata = message.get("response_metadata") or {}
        value = (metadata.get("language_profile") or {}).get("reply_language") if isinstance(metadata, dict) else None
        if value in {item.value for item in ReplyLanguage}:
            return ReplyLanguage(value)
    return None
