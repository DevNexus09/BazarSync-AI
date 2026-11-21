from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping

from app.services.copilot.context_builder import CopilotAnswerContext
from app.services.copilot.language.detector import detect_input_language
from app.services.copilot.language.normalizer import normalize_digits


class CopilotResponseValidationError(ValueError):
    """Rejected model answer. ``code`` is a stable reason for telemetry; the message stays human-readable."""

    def __init__(self, message: str, *, code: str = "INVALID_ANSWER") -> None:
        super().__init__(message)
        self.code = code


# Multilingual-mode claim vocabulary (Banglish and extra Bangla). Latin words match on word boundaries.
EXECUTED_CLAIMS_ML = (
    "execute kora hoyeche", "apply kora hoyeche", "change kora hoyeche", "dam komano hoyeche", "dam change kora hoyeche",
    "order kora hoyeche", "campaign chalu kora hoyeche", "পরিবর্তন করা হয়েছে", "প্রয়োগ করেছি", "অর্ডার করা হয়েছে",
)
PROFIT_CLAIMS_ML = ("lav", "labh", "laabh", "lokshan", "loss", "লাভ", "লোকসান")
FINANCIAL_CLAIMS_ML = ("bikri", "bikroy", "bikry", "bechakena", "বিক্রয়", "বেচাকেনা")
NO_SALES_CLAIMS_ML = (
    "bikri hoyni", "bikri hoy nai", "kono bikri nai", "kono bikri hoyni", "sale hoyni", "বিক্রি নেই", "কোনো বিক্রি হয়নি",
)
VISIBILITY_CLAIMS_ML = ("visibility kom", "visibility low")
BANGLA_SCRIPT_MIN_SHARE = 0.4
LATIN_SCRIPT_MAX_BANGLA_SHARE = 0.15
CURRENCY_PREFIX_RE = re.compile(r"(?i)(?<![a-z])(tk|bdt)(?=\d)|৳")
ML_NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:,\d{2,3})*(?:\.\d+)?%?")


@dataclass(frozen=True, slots=True)
class CopilotValidatedResponse:
    payload: dict[str, Any]
    removed_evidence_ids: list[str]


class CopilotResponseValidator:
    required_keys = {
        "answer",
        "summary",
        "confidence",
        "question_type",
        "language",
        "domains_used",
        "tools_used",
        "evidence",
        "missing_data",
        "data_freshness",
        "recommended_next_steps",
        "action_proposal",
    }

    def validate(self, payload: Mapping[str, Any], *, context: CopilotAnswerContext) -> CopilotValidatedResponse:
        missing = self.required_keys - set(payload)
        if missing:
            raise CopilotResponseValidationError(f"Copilot Groq answer missing keys: {sorted(missing)}")
        answer = str(payload.get("answer") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        if not answer or not summary:
            raise CopilotResponseValidationError("Copilot Groq answer requires answer and summary.")
        language = str(payload.get("language") or "")
        multilingual = bool(context.reply_language)
        if multilingual:
            self._validate_reply_language(language, [answer, summary], context=context)
        elif language != context.language:
            raise CopilotResponseValidationError("Copilot Groq answer language mismatch.", code="LANGUAGE_MISMATCH")
        confidence = str(payload.get("confidence") or "").upper()
        if confidence not in {"HIGH", "MEDIUM", "LOW", "NO_CONTEXT"}:
            raise CopilotResponseValidationError("Copilot Groq answer confidence is invalid.", code="INVALID_CONFIDENCE")

        evidence, removed = self._validated_evidence(payload.get("evidence"), context=context)
        text_fields = [answer, summary, *_string_list(payload.get("recommended_next_steps"))]
        if multilingual:
            self._validate_numbers_multilingual(text_fields, context=context)
        else:
            self._validate_numbers(text_fields, context=context)
        self._validate_sensitive_claims(text_fields, context=context)
        if multilingual:
            self._validate_multilingual_claims(text_fields, context=context)

        validated = {
            "answer": answer,
            "summary": summary,
            "confidence": confidence,
            "question_type": context.question_type,
            "language": language,
            "domains_used": _string_list(payload.get("domains_used")) or context.domains_used,
            "tools_used": _tools_used(payload.get("tools_used"), context=context),
            "evidence": evidence,
            "missing_data": _structured_missing(payload.get("missing_data"), context=context),
            "data_freshness": _freshness(payload.get("data_freshness"), context=context),
            "recommended_next_steps": _string_list(payload.get("recommended_next_steps")),
            "action_proposal": payload.get("action_proposal") if isinstance(payload.get("action_proposal"), dict) else None,
        }
        if not evidence and context.allowed_evidence_ids:
            validated["evidence"] = context.evidence[:8]
        return CopilotValidatedResponse(payload=validated, removed_evidence_ids=removed)

    def _validated_evidence(self, value: Any, *, context: CopilotAnswerContext) -> tuple[list[dict[str, Any]], list[str]]:
        if not isinstance(value, list):
            raise CopilotResponseValidationError("Copilot Groq evidence must be a list.")
        evidence = []
        removed = []
        by_id = {item["evidence_id"]: item for item in context.evidence}
        for item in value:
            if not isinstance(item, Mapping):
                raise CopilotResponseValidationError("Copilot Groq evidence item must be an object.")
            evidence_id = str(item.get("evidence_id") or "")
            if evidence_id not in context.allowed_evidence_ids:
                removed.append(evidence_id)
                continue
            source = by_id[evidence_id]
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "source_type": source.get("source_type") or item.get("source_type"),
                    "title": source.get("title") or item.get("title"),
                    "event_time": source.get("event_time"),
                    "stale": bool(source.get("stale")),
                    "source_metadata": source.get("source_metadata") or {},
                }
            )
        return evidence, removed

    def _validate_numbers(self, texts: list[str], *, context: CopilotAnswerContext) -> None:
        allowed = set(context.allowed_numbers)
        for text in texts:
            for number in _numbers(text):
                if number not in allowed:
                    raise CopilotResponseValidationError(f"Unsupported numeric claim: {number}", code="UNSUPPORTED_NUMBER")

    def _validate_reply_language(self, language: str, texts: list[str], *, context: CopilotAnswerContext) -> None:
        reply_language = str(context.reply_language)
        accepted = {reply_language} | ({"bn"} if reply_language == "banglish" else set())
        if language not in accepted:
            raise CopilotResponseValidationError("Copilot Groq answer language mismatch.", code="LANGUAGE_MISMATCH")
        if not _script_matches(" ".join(texts), reply_language):
            raise CopilotResponseValidationError(f"Copilot Groq answer is not written in {reply_language}.", code="SCRIPT_MISMATCH")

    def _validate_numbers_multilingual(self, texts: list[str], *, context: CopilotAnswerContext) -> None:
        """Same rule as ``_validate_numbers``, but ১২৫০, 1,250 and 1250.00 all count as the fact 1250."""
        allowed = set(context.allowed_numbers) | {_canonical_number(value) for value in context.allowed_numbers}
        for text in texts:
            for number in _multilingual_numbers(text):
                if number not in allowed:
                    raise CopilotResponseValidationError(f"Unsupported numeric claim: {number}", code="UNSUPPORTED_NUMBER")

    def _validate_multilingual_claims(self, texts: list[str], *, context: CopilotAnswerContext) -> None:
        text = normalize_digits(" ".join(texts)).casefold()
        if _contains_term(text, EXECUTED_CLAIMS_ML) and not context.backend_action_executed:
            raise CopilotResponseValidationError("Copilot Groq answer claimed an action was executed.", code="UNSUPPORTED_EXECUTION_CLAIM")
        if _contains_term(text, PROFIT_CLAIMS_ML) and not context.has_profit_margin_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer made unsupported profit or margin claims.", code="UNSUPPORTED_PROFIT_CLAIM")
        if _contains_term(text, FINANCIAL_CLAIMS_ML) and not context.has_financial_evidence and not context.has_memory_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer made unsupported financial claims.", code="UNSUPPORTED_FINANCIAL_CLAIM")
        if _contains_term(text, VISIBILITY_CLAIMS_ML) and not context.has_visibility_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer claimed low visibility without visibility evidence.", code="UNSUPPORTED_VISIBILITY_CLAIM")
        if _contains_term(text, NO_SALES_CLAIMS_ML) and not context.has_reliable_no_sales_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer claimed no sales without reliable sales-history proof.", code="UNSUPPORTED_NO_SALES_CLAIM")

    def _validate_sensitive_claims(self, texts: list[str], *, context: CopilotAnswerContext) -> None:
        text = " ".join(texts).casefold()
        if _contains_any(text, ("executed", "changed your price", "created campaign", "order placed", "প্রয়োগ করা হয়েছে", "চালু করা হয়েছে")) and not context.backend_action_executed:
            raise CopilotResponseValidationError("Copilot Groq answer claimed an action was executed.", code="UNSUPPORTED_EXECUTION_CLAIM")
        if _contains_any(text, ("profit", "margin", "মুনাফা", "মার্জিন")) and not context.has_profit_margin_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer made unsupported profit or margin claims.", code="UNSUPPORTED_PROFIT_CLAIM")
        if _contains_any(text, ("revenue", "sales", "রেভিনিউ", "বিক্রি")) and not context.has_financial_evidence and not context.has_memory_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer made unsupported financial claims.", code="UNSUPPORTED_FINANCIAL_CLAIM")
        if _contains_any(text, ("low visibility", "visibility is low", "ভিজিবিলিটি কম")) and not context.has_visibility_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer claimed low visibility without visibility evidence.", code="UNSUPPORTED_VISIBILITY_CLAIM")
        if _contains_any(text, ("no sales", "not sold", "zero sales", "বিক্রি হয়নি")) and not context.has_reliable_no_sales_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer claimed no sales without reliable sales-history proof.", code="UNSUPPORTED_NO_SALES_CLAIM")


def _tools_used(value: Any, *, context: CopilotAnswerContext) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return context.tools_used
    allowed = {item["name"] for item in context.tools_used}
    rows = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or item.get("tool_name") or "")
        if name in allowed:
            source = next((tool for tool in context.tools_used if tool["name"] == name), {})
            rows.append({**source, "name": name, "status": str(item.get("status") or source.get("status") or "UNKNOWN")})
    return rows or context.tools_used


def _freshness(value: Any, *, context: CopilotAnswerContext) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else context.data_freshness


def _structured_missing(value: Any, *, context: CopilotAnswerContext) -> list[Any]:
    if not isinstance(value, list):
        return context.missing_data
    if any(isinstance(item, Mapping) for item in value):
        return [dict(item) if isinstance(item, Mapping) else {"message": str(item)} for item in value]
    return context.missing_data or [{"message": str(item)} for item in value]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:20]]


def _numbers(text: str) -> list[str]:
    values = []
    for match in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?%?", text or ""):
        normalized = match.rstrip("%")
        if len(normalized.replace(".", "").replace("-", "")) <= 1:
            continue
        values.append(normalized)
    return values


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _contains_term(value: str, needles: tuple[str, ...]) -> bool:
    for needle in needles:
        if needle.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", value):
                return True
        elif needle in value:
            return True
    return False


def _multilingual_numbers(text: str) -> list[str]:
    spaced = CURRENCY_PREFIX_RE.sub(lambda match: f"{match.group(0)} ", normalize_digits(text))
    values = []
    for match in ML_NUMBER_RE.findall(spaced):
        raw = match.rstrip("%").replace(",", "")
        if len(raw.replace(".", "").replace("-", "")) <= 1:
            continue
        values.append(_canonical_number(raw))
    return values


def _canonical_number(value: str) -> str:
    try:
        number = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    text = format(number.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _script_matches(text: str, reply_language: str) -> bool:
    normalized = normalize_digits(text).casefold()
    bengali = sum(1 for character in normalized if "\u0980" <= character <= "\u09ff" and character.isalpha())
    latin = sum(1 for character in normalized if "a" <= character <= "z")
    if bengali + latin == 0:
        return False
    bengali_share = bengali / (bengali + latin)
    if reply_language == "bn":
        return bengali_share >= BANGLA_SCRIPT_MIN_SHARE
    if bengali_share > LATIN_SCRIPT_MAX_BANGLA_SHARE:
        return False
    if reply_language == "banglish":
        _, _, signals = detect_input_language(normalized)
        return signals["banglish_score"] >= 2 and signals["banglish_score"] >= signals["english_score"] * 0.5
    return True
