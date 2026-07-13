from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from app.services.copilot.context_builder import CopilotAnswerContext


class CopilotResponseValidationError(ValueError):
    pass


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
        if language != context.language:
            raise CopilotResponseValidationError("Copilot Groq answer language mismatch.")
        confidence = str(payload.get("confidence") or "").upper()
        if confidence not in {"HIGH", "MEDIUM", "LOW", "NO_CONTEXT"}:
            raise CopilotResponseValidationError("Copilot Groq answer confidence is invalid.")

        evidence, removed = self._validated_evidence(payload.get("evidence"), context=context)
        text_fields = [answer, summary, *_string_list(payload.get("recommended_next_steps"))]
        self._validate_numbers(text_fields, context=context)
        self._validate_sensitive_claims(text_fields, context=context)

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
                    raise CopilotResponseValidationError(f"Unsupported numeric claim: {number}")

    def _validate_sensitive_claims(self, texts: list[str], *, context: CopilotAnswerContext) -> None:
        text = " ".join(texts).casefold()
        if _contains_any(text, ("executed", "changed your price", "created campaign", "order placed", "প্রয়োগ করা হয়েছে", "চালু করা হয়েছে")) and not context.backend_action_executed:
            raise CopilotResponseValidationError("Copilot Groq answer claimed an action was executed.")
        if _contains_any(text, ("profit", "margin", "মুনাফা", "মার্জিন")) and not context.has_profit_margin_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer made unsupported profit or margin claims.")
        if _contains_any(text, ("revenue", "sales", "রেভিনিউ", "বিক্রি")) and not context.has_financial_evidence and not context.has_memory_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer made unsupported financial claims.")
        if _contains_any(text, ("low visibility", "visibility is low", "ভিজিবিলিটি কম")) and not context.has_visibility_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer claimed low visibility without visibility evidence.")
        if _contains_any(text, ("no sales", "not sold", "zero sales", "বিক্রি হয়নি")) and not context.has_reliable_no_sales_evidence:
            raise CopilotResponseValidationError("Copilot Groq answer claimed no sales without reliable sales-history proof.")


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
