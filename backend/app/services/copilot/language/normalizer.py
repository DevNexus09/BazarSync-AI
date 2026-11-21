from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from app.services.copilot.language.lexicon import BANGLA_PHRASES, BANGLA_TERMS, BANGLISH_PHRASES, BANGLISH_TERMS

BANGLA_DIGIT_TRANSLATION = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
TOKEN_RE = re.compile(r"[a-z0-9ঀ-৿]+", re.IGNORECASE)
# "goto 7 din" / "last 7 din" / "গত 7 দিন" (after digit normalisation).
LAST_N_DAYS_RE = re.compile(r"\b(?:goto|gotho|last|ager)\s+(\d{1,3})\s+(?:din|dine|diner|days?)\b|গত\s+(\d{1,3})\s+দিন")
FUZZY_MIN_LENGTH = 6
STEM_MIN_LENGTH = 4


def normalize_digits(value: str | None) -> str:
    """NFKC-normalise text and convert Bangla digits to ASCII digits."""
    return unicodedata.normalize("NFKC", value or "").translate(BANGLA_DIGIT_TRANSLATION)


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    original: str
    normalized: str
    canonical_terms: tuple[str, ...]

    @property
    def planning_text(self) -> str:
        """The question plus canonical English terms, for keyword-based planning only.

        It is never stored or shown to the seller; the original question is kept for
        persistence, prompts and evidence matching.
        """
        if not self.canonical_terms:
            return self.normalized
        return f"{self.normalized} {' '.join(self.canonical_terms)}"


def _normalized_keys(table: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    return {normalize_digits(key).casefold(): value for key, value in table.items()}


_BANGLISH_TERMS = _normalized_keys(BANGLISH_TERMS)
_BANGLA_TERMS = _normalized_keys(BANGLA_TERMS)
_PHRASES = tuple(_normalized_keys({**BANGLISH_PHRASES, **BANGLA_PHRASES}).items())


def normalize_query(question: str) -> NormalizedQuery:
    normalized = " ".join(normalize_digits(question).split())
    lowered = normalized.casefold()
    terms: list[str] = []

    match = LAST_N_DAYS_RE.search(lowered)
    if match:
        terms.append(f"last {match.group(1) or match.group(2)} days")

    tokens = TOKEN_RE.findall(lowered)
    for phrase, mapped in _PHRASES:
        if (_is_bangla(phrase) and phrase in lowered) or _phrase_in_tokens(phrase.split(), tokens):
            terms.extend(mapped)

    for token in tokens:
        token_terms = _BANGLISH_TERMS.get(token) or _BANGLA_TERMS.get(token) or _bangla_stem(token) or _fuzzy_banglish(token)
        if token_terms:
            terms.extend(token_terms)

    canonical = tuple(dict.fromkeys(term for term in terms if term not in lowered))
    return NormalizedQuery(original=question, normalized=normalized, canonical_terms=canonical)


def _phrase_in_tokens(words: list[str], tokens: list[str]) -> bool:
    """Match a phrase; a longer word may carry a suffix ("goto shoptahe", "ei mashe")."""
    for start in range(len(tokens) - len(words) + 1):
        if all(
            token == word or (len(word) >= STEM_MIN_LENGTH and token.startswith(word))
            for word, token in zip(words, tokens[start : start + len(words)])
        ):
            return True
    return False


def _bangla_stem(token: str) -> tuple[str, ...] | None:
    """Bengali-script words take case endings ("স্টকে", "পণ্যের"); match the known stem."""
    if not _is_bangla(token):
        return None
    for known, mapped in _BANGLA_TERMS.items():
        if len(known) >= 3 and token.startswith(known):
            return mapped
    return None


def _fuzzy_banglish(token: str) -> tuple[str, ...] | None:
    """Tolerate one-character spelling variants of longer Banglish terms ("bikroi" -> "bikroy")."""
    if len(token) < FUZZY_MIN_LENGTH or not token.isascii() or not token.isalpha():
        return None
    for known, mapped in _BANGLISH_TERMS.items():
        if len(known) >= FUZZY_MIN_LENGTH and abs(len(known) - len(token)) <= 1 and _within_one_edit(token, known):
            return mapped
    return None


def _within_one_edit(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    if len(left) > len(right):
        left, right = right, left
    for index in range(len(right)):
        if right[:index] + right[index + 1 :] == left:
            return True
    return False


def _is_bangla(value: str) -> bool:
    return any("ঀ" <= character <= "৿" for character in value)
