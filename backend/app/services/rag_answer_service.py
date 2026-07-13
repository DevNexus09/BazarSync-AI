from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import re
from typing import Any, Awaitable, Callable, Mapping
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ai.groq_client import GroqInvalidResponseError, generate_json_completion
from app.models.rag_memory import RagAnswerStatus, RagQueryLog
from app.services.rag_prompt_builder import (
    RAG_PROMPT_VERSION,
    RagPromptBuilder,
    detect_language,
    normalize_logged_question,
)
from app.services.rag_observability import elapsed_ms, increment_metric, log_event, now_ms, observe_latency
from app.services.rag_retrieval_service import NO_CONTEXT_MESSAGE, RagRetrievalResult, RagRetrievalService

logger = logging.getLogger(__name__)

RAG_ANSWER_SCHEMA = {
    "answer": "...",
    "summary": "...",
    "evidence": [],
    "confidence": "HIGH|MEDIUM|LOW|NO_CONTEXT",
    "missing_context": [],
    "recommended_next_steps": [],
    "language": "bn|en",
    "disclaimer": "...",
}


@dataclass(slots=True)
class RagAnswerResult:
    answer: str
    summary: str
    evidence: list[dict[str, Any]]
    confidence: str
    missing_context: list[str]
    recommended_next_steps: list[str]
    language: str
    disclaimer: str
    answer_status: str
    model_id: str | None
    prompt_version: str = RAG_PROMPT_VERSION
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "summary": self.summary,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "missing_context": self.missing_context,
            "recommended_next_steps": self.recommended_next_steps,
            "language": self.language,
            "disclaimer": self.disclaimer,
            "answer_status": self.answer_status,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "evidence_ids": self.evidence_ids,
        }


GroqJsonCallable = Callable[..., Awaitable[Mapping[str, Any]]]


class RagAnswerService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        retrieval_service: RagRetrievalService | None = None,
        prompt_builder: RagPromptBuilder | None = None,
        groq_json_completion: GroqJsonCallable | None = None,
        model: str | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._retrieval_service = retrieval_service
        self._prompt_builder = prompt_builder or RagPromptBuilder()
        self._groq_json_completion = groq_json_completion or generate_json_completion
        self._model = model or settings.rag_groq_model
        self._log = log or logger

    async def answer_question(
        self,
        *,
        seller_id: UUID,
        question: str,
        user_id: UUID | None = None,
        product_id: UUID | None = None,
        source_types=None,
        from_event_time: datetime | None = None,
        to_event_time: datetime | None = None,
        top_k: int | None = None,
        min_similarity: float | None = None,
        include_stale: bool = False,
        business_context: Mapping[str, Any] | None = None,
    ) -> RagAnswerResult:
        start_ms = now_ms()
        if self._retrieval_service is None:
            if self._db is None:
                raise ValueError("RagAnswerService requires a retrieval service or database session")
            self._retrieval_service = RagRetrievalService(self._db)

        retrieval = self._retrieval_service.retrieve_context(
            seller_id=seller_id,
            question=question,
            product_id=product_id,
            source_types=source_types,
            from_event_time=from_event_time,
            to_event_time=to_event_time,
            top_k=top_k,
            min_similarity=min_similarity,
            include_stale=include_stale,
        )
        if retrieval.retrieval_confidence == "NO_CONTEXT":
            result = self._fallback_answer(
                question=question,
                retrieval=retrieval,
                status=RagAnswerStatus.NO_CONTEXT,
            )
            self._audit(
                seller_id=seller_id,
                user_id=user_id,
                question=question,
                retrieval=retrieval,
                answer_status=RagAnswerStatus.NO_CONTEXT,
                model_id=None,
            )
            duration_ms = elapsed_ms(start_ms)
            observe_latency("rag_answer_latency_ms", duration_ms)
            increment_metric("rag_no_context_total")
            log_event(
                self._log,
                logging.INFO,
                "rag_answer_no_context",
                seller_id=seller_id,
                duration_ms=duration_ms,
            )
            return result

        prompt = self._prompt_builder.build_prompt(
            question=question,
            retrieval=retrieval,
            business_context=business_context,
        )
        try:
            response = await self._groq_json_completion(
                prompt.messages,
                model=self._model,
                temperature=0.1,
                max_tokens=900,
                schema_hint=RAG_ANSWER_SCHEMA,
            )
            payload = self._extract_payload(response)
            result = self._validate_payload(
                payload,
                question=question,
                retrieval=retrieval,
                model_id=str(response.get("model") or self._model or "unknown"),
            )
            answer_status = RagAnswerStatus.SUCCESS
            log_event(
                self._log,
                logging.INFO,
                "rag_groq_success",
                seller_id=seller_id,
                model=result.model_id,
                evidence_count=len(result.evidence_ids),
                confidence=result.confidence,
            )
        except Exception as exc:  # noqa: BLE001 - failures intentionally degrade to evidence fallback
            log_event(
                self._log,
                logging.WARNING,
                "rag_groq_failure",
                seller_id=seller_id,
                reason=exc.__class__.__name__,
            )
            result = self._fallback_answer(
                question=question,
                retrieval=retrieval,
                status=RagAnswerStatus.FALLBACK,
            )
            answer_status = RagAnswerStatus.FALLBACK

        self._audit(
            seller_id=seller_id,
            user_id=user_id,
            question=question,
            retrieval=retrieval,
            answer_status=answer_status,
            model_id=result.model_id,
        )
        duration_ms = elapsed_ms(start_ms)
        observe_latency("rag_answer_latency_ms", duration_ms)
        log_event(
            self._log,
            logging.INFO,
            "rag_answer_completed",
            seller_id=seller_id,
            status=answer_status.value,
            confidence=result.confidence,
            duration_ms=duration_ms,
            evidence_count=len(result.evidence_ids),
        )
        return result

    def _extract_payload(self, response: Mapping[str, Any]) -> Mapping[str, Any]:
        content = response.get("content")
        if isinstance(content, Mapping):
            return content
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                raise GroqInvalidResponseError("Groq returned invalid JSON.") from exc
            if isinstance(parsed, Mapping):
                return parsed
        raise GroqInvalidResponseError("Groq answer response must be a JSON object.")

    def _validate_payload(
        self,
        payload: Mapping[str, Any],
        *,
        question: str,
        retrieval: RagRetrievalResult,
        model_id: str | None,
    ) -> RagAnswerResult:
        required = {
            "answer",
            "summary",
            "evidence",
            "confidence",
            "missing_context",
            "recommended_next_steps",
            "language",
            "disclaimer",
        }
        missing = required - set(payload)
        if missing:
            raise GroqInvalidResponseError(f"Groq answer missing keys: {sorted(missing)}")
        language = str(payload["language"])
        expected_language = detect_language(question)
        if language != expected_language:
            raise GroqInvalidResponseError("Groq answer language mismatch.")
        confidence = str(payload["confidence"])
        if confidence not in {"HIGH", "MEDIUM", "LOW", "NO_CONTEXT"}:
            raise GroqInvalidResponseError("Groq answer confidence is invalid.")
        if confidence == "NO_CONTEXT" and retrieval.retrieval_confidence != "NO_CONTEXT":
            confidence = "LOW"
        if not isinstance(payload["evidence"], list):
            raise GroqInvalidResponseError("Groq answer evidence must be a list.")

        allowed_evidence_ids = set(retrieval.evidence_ids)
        evidence = []
        for item in payload["evidence"]:
            if not isinstance(item, Mapping):
                raise GroqInvalidResponseError("Groq answer evidence item must be an object.")
            evidence_id = str(item.get("evidence_id") or "")
            if evidence_id not in allowed_evidence_ids:
                raise GroqInvalidResponseError("Groq answer referenced evidence outside retrieval context.")
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "source_type": str(item.get("source_type") or ""),
                    "source_title": str(item.get("source_title") or ""),
                    "event_time": item.get("event_time"),
                }
            )

        answer = str(payload["answer"])
        summary = str(payload["summary"])
        next_steps = _string_list(payload["recommended_next_steps"])
        missing_context = _string_list(payload["missing_context"])
        disclaimer = str(payload["disclaimer"])
        if _has_unsupported_numbers(
            [answer, summary, *next_steps, disclaimer],
            question=question,
            retrieval=retrieval,
        ):
            raise GroqInvalidResponseError("Groq answer included unsupported numbers.")

        return RagAnswerResult(
            answer=answer,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            missing_context=missing_context,
            recommended_next_steps=next_steps,
            language=language,
            disclaimer=disclaimer,
            answer_status=RagAnswerStatus.SUCCESS.value,
            model_id=model_id,
            evidence_ids=[item["evidence_id"] for item in evidence],
        )

    def _fallback_answer(
        self,
        *,
        question: str,
        retrieval: RagRetrievalResult,
        status: RagAnswerStatus,
    ) -> RagAnswerResult:
        language = detect_language(question)
        no_context = retrieval.retrieval_confidence == "NO_CONTEXT"
        if language == "bn":
            answer = (
                "এই প্রশ্নের নির্ভরযোগ্য উত্তর দেওয়ার মতো seller-specific history পাওয়া যায়নি।"
                if no_context
                else "আমি পাওয়া evidence থেকে নিশ্চিতভাবে উত্তর দিতে পারছি না, তবে নিচের history ব্যবহার করা যেতে পারে।"
            )
            summary = "যথেষ্ট প্রমাণ নেই।" if no_context else "Groq unavailable বা response invalid ছিল; retrieved evidence ফেরত দেওয়া হলো।"
            disclaimer = "এই উত্তর শুধু পাওয়া seller-specific evidence-এর উপর ভিত্তি করে।"
            next_steps = ["নতুন data sync করুন।"] if no_context else ["Evidence দেখে deterministic recommendation যাচাই করুন।"]
        else:
            answer = (
                NO_CONTEXT_MESSAGE
                if no_context
                else "I could not safely generate a Groq answer, so I am returning the retrieved seller-specific evidence."
            )
            summary = "Evidence is insufficient." if no_context else "Groq failed or returned an invalid response; fallback evidence is returned."
            disclaimer = "This answer is grounded only in retrieved seller-specific evidence."
            next_steps = ["Sync or backfill more business history."] if no_context else ["Review the cited evidence and deterministic recommendations."]

        evidence = _evidence_from_retrieval(retrieval)
        return RagAnswerResult(
            answer=answer,
            summary=summary,
            evidence=evidence,
            confidence=retrieval.retrieval_confidence,
            missing_context=list(retrieval.missing_data_notes),
            recommended_next_steps=next_steps,
            language=language,
            disclaimer=disclaimer,
            answer_status=status.value,
            model_id=None,
            evidence_ids=[item["evidence_id"] for item in evidence],
        )

    def _audit(
        self,
        *,
        seller_id: UUID,
        user_id: UUID | None,
        question: str,
        retrieval: RagRetrievalResult,
        answer_status: RagAnswerStatus,
        model_id: str | None,
    ) -> None:
        if self._db is None:
            return
        source_types = sorted({item.source_type.value for item in retrieval.retrieved_chunks})
        try:
            self._db.add(
                RagQueryLog(
                    seller_id=seller_id,
                    user_id=user_id,
                    question=normalize_logged_question(question),
                    normalized_question=normalize_logged_question(question),
                    retrieval_confidence=retrieval.retrieval_confidence,
                    source_types_used=source_types,
                    evidence_ids=retrieval.evidence_ids,
                    answer_status=answer_status,
                    model_id=model_id,
                    prompt_version=RAG_PROMPT_VERSION,
                )
            )
            self._db.commit()
        except SQLAlchemyError:
            self._db.rollback()
            self._log.warning("rag_query_audit_failed seller_id=%s", seller_id)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:10]]


def _evidence_from_retrieval(retrieval: RagRetrievalResult) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in retrieval.source_documents}
    evidence = []
    for item in retrieval.retrieved_chunks:
        doc = by_id.get(item.memory_document_id, {})
        evidence.append(
            {
                "evidence_id": item.evidence_id,
                "source_type": item.source_type.value,
                "source_title": doc.get("title") or item.source_table or "",
                "event_time": item.event_time.isoformat() if item.event_time else None,
            }
        )
    return evidence


def _has_unsupported_numbers(texts: list[str], *, question: str, retrieval: RagRetrievalResult) -> bool:
    allowed = set(_numbers(question))
    for item in retrieval.retrieved_chunks:
        allowed.update(_numbers(item.chunk_text))
        if item.event_time is not None:
            allowed.update(_numbers(item.event_time.isoformat()))
    for text in texts:
        for number in _numbers(text):
            if number not in allowed:
                return True
    return False


def _numbers(text: str) -> list[str]:
    values = []
    for match in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?%?", text or ""):
        normalized = match.rstrip("%")
        if len(normalized.replace(".", "").replace("-", "")) <= 1:
            continue
        values.append(normalized)
    return values
