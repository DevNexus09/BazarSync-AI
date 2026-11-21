"""Language detection and normalisation for multilingual (Bangla, English, Banglish) Copilot chat."""

from app.services.copilot.language.detector import (
    InputLanguage,
    LanguageProfile,
    ReplyLanguage,
    detect_input_language,
    resolve_language_profile,
)
from app.services.copilot.language.normalizer import NormalizedQuery, normalize_digits, normalize_query

__all__ = [
    "InputLanguage",
    "LanguageProfile",
    "NormalizedQuery",
    "ReplyLanguage",
    "detect_input_language",
    "normalize_digits",
    "normalize_query",
    "resolve_language_profile",
]
