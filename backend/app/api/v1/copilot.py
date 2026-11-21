from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.copilot import CopilotActionProposalStatus, CopilotMessage, CopilotMessageRole
from app.models.product import Product
from app.models.seller import Seller
from app.schemas.copilot import (
    CopilotApiAskResponse,
    CopilotActionProposalListResponse,
    CopilotActionProposalResponse,
    CopilotActionProposalTransitionResponse,
    CopilotConversationCreate,
    CopilotConversationDetailResponse,
    CopilotConversationListResponse,
    CopilotConversationResponse,
    CopilotAskRequest,
    CopilotErrorResponse,
    CopilotMessageFeedbackRequest,
    CopilotMessageFeedbackResponse,
    CopilotMessageResponse,
    CopilotSearchResponse,
    CopilotToolMetadataResponse,
    CopilotToolsResponse,
    CopilotToolUsedResponse,
)
from app.repositories.copilot_repository import CopilotConversationNotFoundError, CopilotMessageNotFoundError, CopilotRepository
from app.services.copilot.action_proposal_service import (
    CopilotActionProposalNotFoundError,
    CopilotActionProposalService,
    CopilotActionProposalTransitionError,
)
from app.services.copilot.observability import capability_snapshot, copilot_health_snapshot
from app.services.copilot.orchestrator import CopilotOrchestrator, CopilotOrchestratorRequest
from app.services.copilot.rate_limiter import CopilotRateLimitExceeded, copilot_ask_rate_limiter
from app.services.copilot.tool_registry import CopilotToolRegistry

router = APIRouter(prefix="/copilot", tags=["copilot"])
logger = logging.getLogger(__name__)


@router.get("/health")
def get_copilot_health(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> dict:
    """Return seller-scoped Copilot telemetry without prompt or payload content."""

    return copilot_health_snapshot(db, seller_id=current_seller.id)


@router.get("/capabilities")
def get_copilot_capabilities(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> dict:
    return {
        "status": "ok",
        "capabilities": capability_snapshot(db, seller_id=current_seller.id),
    }


@router.get("/conversations", response_model=CopilotConversationListResponse)
def list_conversations(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    include_archived: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CopilotConversationListResponse:
    conversations, total = CopilotRepository(db).list_conversations(
        seller_id=current_seller.id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return CopilotConversationListResponse(
        items=[_conversation_response(db, item) for item in conversations],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/conversations", response_model=CopilotConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: CopilotConversationCreate,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> CopilotConversationResponse:
    conversation = CopilotRepository(db).create_conversation(
        seller_id=current_seller.id,
        user_id=current_seller.id,
        title=payload.title,
        language=payload.language,
        metadata_json=payload.metadata_json,
    )
    return _conversation_response(db, conversation)


@router.get("/conversations/{conversation_id}", response_model=CopilotConversationDetailResponse)
def get_conversation_messages(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> CopilotConversationDetailResponse:
    repository = CopilotRepository(db)
    conversation = repository.get_conversation(seller_id=current_seller.id, conversation_id=conversation_id)
    if conversation is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "conversation_not_found", "Conversation not found.")
    messages = repository.list_messages(seller_id=current_seller.id, conversation_id=conversation_id)
    return CopilotConversationDetailResponse(
        conversation=_conversation_response(db, conversation),
        messages=[_message_response(item) for item in messages],
    )


@router.post(
    "/ask",
    response_model=CopilotApiAskResponse,
    responses={403: {"model": CopilotErrorResponse}, 404: {"model": CopilotErrorResponse}},
)
async def ask_copilot(
    payload: CopilotAskRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> CopilotApiAskResponse:
    debug_allowed = _check_ask_allowed(payload, db=db, current_seller=current_seller)
    try:
        result = await CopilotOrchestrator(db=db).ask(_orchestrator_request(payload, current_seller=current_seller, debug_allowed=debug_allowed))
    except CopilotConversationNotFoundError as exc:
        raise _http_error(status.HTTP_404_NOT_FOUND, "conversation_not_found", "Conversation not found.") from exc
    return _ask_response(result, debug_allowed=debug_allowed)


@router.post(
    "/ask/stream",
    responses={403: {"model": CopilotErrorResponse}, 404: {"model": CopilotErrorResponse}},
)
async def ask_copilot_stream(
    payload: CopilotAskRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> StreamingResponse:
    """Server-sent events: ``stage`` progress events, then one ``answer`` (same body as /ask) or ``error``.

    Answer text is never streamed before validation, so the grounding guarantee holds.
    """
    if not settings.copilot_streaming_enabled:
        raise _http_error(status.HTTP_404_NOT_FOUND, "streaming_not_enabled", "Copilot streaming is not enabled.")
    debug_allowed = _check_ask_allowed(payload, db=db, current_seller=current_seller)
    orchestrator_request = _orchestrator_request(payload, current_seller=current_seller, debug_allowed=debug_allowed)
    return StreamingResponse(
        _ask_event_stream(orchestrator_request, debug_allowed=debug_allowed),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _ask_event_stream(orchestrator_request: CopilotOrchestratorRequest, *, debug_allowed: bool):
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    async def progress(event: dict[str, Any]) -> None:
        await queue.put(("stage", event))

    async def run() -> None:
        # The streaming body outlives the request dependencies, so it owns its session.
        session = _stream_session_factory()
        try:
            result = await CopilotOrchestrator(db=session).ask(orchestrator_request, progress=progress)
            await queue.put(("answer", _ask_response(result, debug_allowed=debug_allowed).model_dump(mode="json")))
        except CopilotConversationNotFoundError:
            await queue.put(("error", {"error_code": "conversation_not_found", "detail": "Conversation not found."}))
        except Exception:
            logger.exception("copilot_stream_failed seller_id=%s", orchestrator_request.seller_id)
            await queue.put(("error", {"error_code": "copilot_failed", "detail": "Copilot could not answer right now."}))
        finally:
            session.close()
            await queue.put(None)

    task = asyncio.create_task(run())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    finally:
        if not task.done():
            task.cancel()


def _stream_session_factory() -> Session:
    from app.db.session import SessionLocal

    return SessionLocal()


def _check_ask_allowed(payload: CopilotAskRequest, *, db: Session, current_seller: Seller) -> bool:
    """Ownership, rate-limit, language and debug checks shared by /ask and /ask/stream. Returns debug_allowed."""
    if payload.product_id is not None and not _seller_owns_product(
        db,
        seller_id=current_seller.id,
        product_id=payload.product_id,
    ):
        raise _http_error(status.HTTP_403_FORBIDDEN, "product_not_owned", "Product is not available for this seller.")

    try:
        copilot_ask_rate_limiter.check(current_seller.id)
    except CopilotRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error_code": "rate_limited", "detail": "Too many Copilot questions. Please wait a moment."},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    if payload.language == "banglish" and not settings.copilot_multilingual_enabled:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "language_not_supported",
            "Banglish replies are not enabled for this deployment.",
        )
    debug_allowed = payload.debug and (_debug_allowed() or _seller_can_debug(current_seller))
    if payload.debug and not debug_allowed:
        raise _http_error(status.HTTP_403_FORBIDDEN, "debug_not_allowed", "Copilot debug output is not enabled for this account.")
    return bool(debug_allowed)


def _orchestrator_request(payload: CopilotAskRequest, *, current_seller: Seller, debug_allowed: bool) -> CopilotOrchestratorRequest:
    return CopilotOrchestratorRequest(
        seller_id=current_seller.id,
        user_id=current_seller.id,
        conversation_id=payload.conversation_id,
        question=payload.question,
        product_id=payload.product_id,
        requested_language=payload.language,
        from_date=payload.from_date,
        to_date=payload.to_date,
        domain_filters=payload.domain_filters,
        include_current_data=payload.include_current_data,
        include_memory=payload.include_memory,
        memory_source_types=payload.memory_source_types,
        top_k=payload.top_k,
        debug_allowed=debug_allowed,
        include_tool_trace=True,
    )


def _ask_response(result: Any, *, debug_allowed: bool) -> CopilotApiAskResponse:
    tools_used = [
        CopilotToolUsedResponse(
            name=item.get("name") or item.get("tool_name", ""),
            status=item.get("status", "UNKNOWN"),
            evidence_count=item.get("evidence_count"),
            error=item.get("error") if isinstance(item.get("error"), dict) else None,
        )
        for item in (getattr(result, "tools_used", None) or result.tool_trace)
    ]
    return CopilotApiAskResponse(
        conversation_id=result.conversation_id,
        message_id=result.assistant_message_id,
        answer=result.answer,
        summary=result.summary,
        confidence=result.confidence,
        language=result.language,
        intent=result.intent,
        question_type=getattr(result, "question_type", None),
        domains_used=getattr(result, "domains_used", []),
        tools_used=tools_used,
        evidence=result.evidence,
        missing_data=result.missing_data,
        data_freshness=getattr(result, "data_freshness", []),
        recommended_next_steps=result.recommended_next_steps,
        action_proposal=result.action_proposal,
        debug={"tool_trace": result.tool_trace} if debug_allowed else None,
        reply_language=getattr(result, "reply_language", None),
        reply_script=getattr(result, "reply_script", None),
        suggested_follow_ups=list(getattr(result, "suggested_follow_ups", None) or []),
    )


@router.get("/search", response_model=CopilotSearchResponse)
def search_copilot_history(
    q: str = Query(min_length=1, max_length=200),
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CopilotSearchResponse:
    messages, total = CopilotRepository(db).search_messages(
        seller_id=current_seller.id,
        query=q,
        limit=limit,
        offset=offset,
    )
    return CopilotSearchResponse(
        items=[_message_response(item) for item in messages],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/tools", response_model=CopilotToolsResponse)
def get_available_tools(
    current_seller: Seller = Depends(get_current_seller),
) -> CopilotToolsResponse:
    del current_seller
    tools = [
        CopilotToolMetadataResponse(
            name=tool.name,
            domain=list(tool.catalog_domains),
            description=tool.description,
            input_fields=list(tool.argument_schema.model_fields.keys()),
            safety_level=tool.safety_level.value,
            requires_confirmation=tool.requires_confirmation,
            allowed_in_read_only_mode=tool.allowed_in_read_only_mode,
        )
        for tool in CopilotToolRegistry().list_tools()
    ]
    return CopilotToolsResponse(tools=tools)


@router.get("/action-proposals", response_model=CopilotActionProposalListResponse)
def list_action_proposals(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    status_filter: CopilotActionProposalStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CopilotActionProposalListResponse:
    service = CopilotActionProposalService(db)
    proposals, total = service.list_proposals(
        seller_id=current_seller.id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return CopilotActionProposalListResponse(
        items=[CopilotActionProposalResponse.model_validate(item) for item in proposals],
        total=total,
        limit=limit,
        offset=offset,
    )


def _seller_owns_product(db: Session, *, seller_id: UUID, product_id: UUID) -> bool:
    return bool(
        db.execute(
            select(Product.id).where(
                Product.id == product_id,
                Product.seller_id == seller_id,
            )
        ).scalar_one_or_none()
    )


def _debug_allowed() -> bool:
    return settings.env.lower() in {"development", "dev", "local", "test"}


def _seller_can_debug(seller: Seller) -> bool:
    return bool(getattr(seller, "is_admin", False) or getattr(seller, "role", None) == "admin")


def _conversation_response(db: Session, conversation) -> CopilotConversationResponse:
    message_count = 0
    if hasattr(db, "execute"):
        try:
            value = db.execute(
                select(func.count()).select_from(CopilotMessage).where(
                    CopilotMessage.seller_id == conversation.seller_id,
                    CopilotMessage.conversation_id == conversation.id,
                )
            ).scalar_one_or_none()
            message_count = int(value or 0) if isinstance(value, int) else 0
        except Exception:
            message_count = 0
    last_message = None
    try:
        last_message = db.execute(
            select(CopilotMessage)
            .where(CopilotMessage.seller_id == conversation.seller_id, CopilotMessage.conversation_id == conversation.id)
            .order_by(CopilotMessage.created_at.desc(), CopilotMessage.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    except Exception:
        last_message = None
    preview = getattr(last_message, "content", None)
    confidence = getattr(last_message, "answer_confidence", None)
    return CopilotConversationResponse(
        id=conversation.id,
        conversation_id=conversation.id,
        seller_id=conversation.seller_id,
        user_id=getattr(conversation, "user_id", None),
        title=getattr(conversation, "title", None),
        last_message_preview=_preview(preview),
        status=conversation.status,
        language=getattr(conversation, "language", "en"),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        archived_at=getattr(conversation, "archived_at", None),
        message_count=message_count,
        last_confidence=getattr(confidence, "value", confidence),
        metadata_json=getattr(conversation, "metadata_json", None),
    )


def _message_response(message) -> CopilotMessageResponse:
    metadata = getattr(message, "response_metadata_json", None) or {}
    evidence = _list_json(getattr(message, "evidence_json", None))
    missing = _list_json(getattr(message, "missing_data_json", None) or getattr(message, "missing_context_json", None))
    tools = _list_json(getattr(message, "tools_used_json", None))
    domains = _list_json(getattr(message, "domains_used_json", None))
    freshness = _list_json(getattr(message, "data_freshness_json", None))
    next_steps = _list_json(getattr(message, "recommended_next_steps_json", None))
    is_assistant = getattr(message, "role", None) == CopilotMessageRole.ASSISTANT
    return CopilotMessageResponse(
        id=message.id,
        seller_id=message.seller_id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        language=getattr(message, "language", "en"),
        answer_confidence=getattr(message, "answer_confidence", None),
        model_id=getattr(message, "model_id", None),
        prompt_version=getattr(message, "prompt_version", None),
        token_usage_json=getattr(message, "token_usage_json", None),
        evidence_json=getattr(message, "evidence_json", None),
        missing_context_json=getattr(message, "missing_context_json", None),
        missing_data_json=getattr(message, "missing_data_json", None),
        data_freshness_json=getattr(message, "data_freshness_json", None),
        tools_used_json=getattr(message, "tools_used_json", None),
        domains_used_json=getattr(message, "domains_used_json", None),
        recommended_next_steps_json=getattr(message, "recommended_next_steps_json", None),
        action_proposal_json=getattr(message, "action_proposal_json", None),
        response_metadata_json=getattr(message, "response_metadata_json", None),
        answer=message.content if is_assistant else None,
        summary=metadata.get("summary") if isinstance(metadata, dict) else None,
        confidence=getattr(message, "answer_confidence", None) if is_assistant else None,
        question_type=metadata.get("question_type") if isinstance(metadata, dict) else None,
        domains_used=[str(item) for item in domains],
        tools_used=[item for item in tools if isinstance(item, dict)],
        evidence=[item for item in evidence if isinstance(item, dict)],
        missing_data=missing,
        data_freshness=[item for item in freshness if isinstance(item, dict)],
        recommended_next_steps=[str(item) for item in next_steps],
        action_proposal=getattr(message, "action_proposal_json", None) if isinstance(getattr(message, "action_proposal_json", None), dict) else None,
        created_at=message.created_at,
    )


def _list_json(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "missing_data", "tools_used", "domains_used", "data_freshness", "recommended_next_steps", "evidence"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def _preview(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.split())[:160]


def _http_error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": error_code, "detail": message},
    )


@router.get("/action-proposals/{proposal_id}", response_model=CopilotActionProposalResponse)
def get_action_proposal(
    proposal_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> CopilotActionProposalResponse:
    try:
        proposal = CopilotActionProposalService(db).get_proposal(
            seller_id=current_seller.id,
            proposal_id=proposal_id,
        )
    except CopilotActionProposalNotFoundError as exc:
        raise _http_error(status.HTTP_404_NOT_FOUND, "action_proposal_not_found", "Action proposal not found.") from exc
    return CopilotActionProposalResponse.model_validate(proposal)


@router.post("/action-proposals/{proposal_id}/approve", response_model=CopilotActionProposalTransitionResponse)
def approve_action_proposal(
    proposal_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> CopilotActionProposalTransitionResponse:
    try:
        proposal, message = CopilotActionProposalService(db).approve(
            seller_id=current_seller.id,
            proposal_id=proposal_id,
        )
    except CopilotActionProposalNotFoundError as exc:
        raise _http_error(status.HTTP_404_NOT_FOUND, "action_proposal_not_found", "Action proposal not found.") from exc
    except CopilotActionProposalTransitionError as exc:
        raise _http_error(status.HTTP_409_CONFLICT, "action_proposal_transition_invalid", str(exc)) from exc
    return CopilotActionProposalTransitionResponse(
        proposal=CopilotActionProposalResponse.model_validate(proposal),
        message=message,
        executed=False,
    )


@router.post("/action-proposals/{proposal_id}/reject", response_model=CopilotActionProposalTransitionResponse)
def reject_action_proposal(
    proposal_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> CopilotActionProposalTransitionResponse:
    try:
        proposal, message = CopilotActionProposalService(db).reject(
            seller_id=current_seller.id,
            proposal_id=proposal_id,
        )
    except CopilotActionProposalNotFoundError as exc:
        raise _http_error(status.HTTP_404_NOT_FOUND, "action_proposal_not_found", "Action proposal not found.") from exc
    except CopilotActionProposalTransitionError as exc:
        raise _http_error(status.HTTP_409_CONFLICT, "action_proposal_transition_invalid", str(exc)) from exc
    return CopilotActionProposalTransitionResponse(
        proposal=CopilotActionProposalResponse.model_validate(proposal),
        message=message,
        executed=False,
    )


@router.post(
    "/messages/{message_id}/feedback",
    response_model=CopilotMessageFeedbackResponse,
    responses={404: {"model": CopilotErrorResponse}},
)
def submit_message_feedback(
    message_id: UUID,
    payload: CopilotMessageFeedbackRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> CopilotMessageFeedbackResponse:
    try:
        feedback = CopilotRepository(db).upsert_message_feedback(
            seller_id=current_seller.id,
            message_id=message_id,
            rating=payload.rating.upper(),
            reason=payload.reason.strip() if payload.reason else None,
            comment=payload.comment.strip() if payload.comment else None,
        )
    except CopilotMessageNotFoundError as exc:
        raise _http_error(status.HTTP_404_NOT_FOUND, "message_not_found", "Message not found.") from exc
    return CopilotMessageFeedbackResponse(
        message_id=feedback.message_id,
        rating="up" if feedback.rating == "UP" else "down",
        reason=feedback.reason,
        updated_at=feedback.updated_at,
    )
