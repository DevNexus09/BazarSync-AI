from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.copilot import (
    CopilotActionProposal,
    CopilotActionProposalStatus,
    CopilotActionType,
)
from app.repositories.copilot_repository import CopilotRepository
from app.services.copilot.intent_classifier import CopilotIntent, CopilotIntentResult
from app.services.copilot.tool_registry import ToolExecutionResult


APPROVAL_MESSAGE = "Execution is not implemented yet. This proposal has been approved for future execution."
REJECTION_MESSAGE = "This proposal has been rejected. No marketplace action was executed."


class CopilotActionProposalNotFoundError(Exception):
    pass


class CopilotActionProposalTransitionError(Exception):
    pass


class CopilotActionProposalRepository(Protocol):
    def list_action_proposals(self, *, seller_id: UUID, status: CopilotActionProposalStatus | None = None, limit: int = 20, offset: int = 0) -> tuple[list[CopilotActionProposal], int]: ...
    def get_action_proposal(self, *, seller_id: UUID, proposal_id: UUID) -> CopilotActionProposal | None: ...
    def save_action_proposal(self, proposal: CopilotActionProposal) -> CopilotActionProposal: ...


@dataclass(frozen=True, slots=True)
class ActionProposalPlan:
    action_type: CopilotActionType
    proposal_type: str
    proposed_payload_json: dict[str, Any]
    safety_checks_json: dict[str, Any]
    expected_impact_json: dict[str, Any] | None
    evidence_json: list[dict[str, Any]]
    requires_confirmation: bool = True


class CopilotActionProposalService:
    def __init__(self, db: Session | None = None, *, repository: CopilotActionProposalRepository | None = None, now: datetime | None = None) -> None:
        if repository is None and db is None:
            raise ValueError("CopilotActionProposalService requires a repository or database session.")
        self._repository = repository or CopilotRepository(db)  # type: ignore[arg-type]
        self._now = now

    def list_proposals(
        self,
        *,
        seller_id: UUID,
        status: CopilotActionProposalStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[CopilotActionProposal], int]:
        rows, total = self._repository.list_action_proposals(
            seller_id=seller_id,
            status=status,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )
        return [self._expire_if_needed(row) for row in rows], total

    def get_proposal(self, *, seller_id: UUID, proposal_id: UUID) -> CopilotActionProposal:
        proposal = self._repository.get_action_proposal(seller_id=seller_id, proposal_id=proposal_id)
        if proposal is None:
            raise CopilotActionProposalNotFoundError
        return self._expire_if_needed(proposal)

    def approve(self, *, seller_id: UUID, proposal_id: UUID) -> tuple[CopilotActionProposal, str]:
        proposal = self.get_proposal(seller_id=seller_id, proposal_id=proposal_id)
        if proposal.status == CopilotActionProposalStatus.EXPIRED:
            raise CopilotActionProposalTransitionError("Expired proposals cannot be approved.")
        if proposal.status == CopilotActionProposalStatus.REJECTED:
            raise CopilotActionProposalTransitionError("Rejected proposals cannot be approved.")
        proposal.status = CopilotActionProposalStatus.APPROVED
        proposal.approved_at = self._now_utc()
        proposal.executed_at = None
        return self._repository.save_action_proposal(proposal), APPROVAL_MESSAGE

    def reject(self, *, seller_id: UUID, proposal_id: UUID) -> tuple[CopilotActionProposal, str]:
        proposal = self.get_proposal(seller_id=seller_id, proposal_id=proposal_id)
        if proposal.status == CopilotActionProposalStatus.APPROVED:
            raise CopilotActionProposalTransitionError("Approved proposals cannot be rejected.")
        proposal.status = CopilotActionProposalStatus.REJECTED
        proposal.rejected_at = self._now_utc()
        proposal.executed_at = None
        return self._repository.save_action_proposal(proposal), REJECTION_MESSAGE

    def build_plan(
        self,
        *,
        classification: CopilotIntentResult,
        question: str,
        product_id: UUID | None,
        tool_results: list[ToolExecutionResult],
    ) -> ActionProposalPlan:
        evidence = _collect_evidence(tool_results)
        tool_data = {result.tool_name: result.data for result in tool_results}
        if classification.intent == CopilotIntent.ACTION_REQUEST_PRICE_CHANGE:
            simulation = tool_data.get("simulate_price_change", {})
            return ActionProposalPlan(
                action_type=CopilotActionType.PRICE_CHANGE,
                proposal_type="PRICE_CHANGE",
                proposed_payload_json={
                    "proposal_type": "PRICE_CHANGE",
                    "product_id": str(product_id) if product_id else None,
                    "requested_change": _requested_change(question),
                    "current_price": _first_value(tool_data, "current_price"),
                    "proposed_price": simulation.get("candidate_price") or _first_value(tool_data, "recommended_price"),
                    "execution_enabled": False,
                },
                safety_checks_json={
                    "tool": "simulate_price_change",
                    "allowed": bool(simulation.get("allowed")),
                    "blocked_reasons": simulation.get("blocked_reasons") or _collect_blocked_reasons(tool_results),
                    "requires_confirmation": True,
                    "execution_not_implemented": True,
                },
                expected_impact_json={
                    "expected_revenue": simulation.get("expected_revenue"),
                    "expected_profit": simulation.get("expected_profit"),
                    "margin_guard": simulation.get("margin_guard"),
                },
                evidence_json=evidence,
            )
        if classification.intent == CopilotIntent.ACTION_REQUEST_PROMOTION:
            missing = _collect_missing(tool_results)
            return ActionProposalPlan(
                action_type=CopilotActionType.PROMOTION_PLAN,
                proposal_type="PROMOTION_PLAN",
                proposed_payload_json={
                    "proposal_type": "PROMOTION_PLAN",
                    "product_id": str(product_id) if product_id else None,
                    "requested_promotion": _requested_change(question),
                    "execution_enabled": False,
                },
                safety_checks_json={
                    "tools": ["get_promotion_recommendations", "get_pricing_recommendations"],
                    "allowed": not _looks_like_discount(question) or not missing,
                    "blocked_reasons": missing if _looks_like_discount(question) else [],
                    "requires_confirmation": True,
                    "execution_not_implemented": True,
                },
                expected_impact_json=_first_value(tool_data, "expected_impact") or {},
                evidence_json=evidence,
            )
        if classification.intent == CopilotIntent.ACTION_REQUEST_REORDER_PLAN:
            row = _first_row(tool_data, "get_restock_recommendations")
            return ActionProposalPlan(
                action_type=CopilotActionType.REORDER_PLAN,
                proposal_type="REORDER_PLAN",
                proposed_payload_json={
                    "proposal_type": "REORDER_PLAN",
                    "product": row.get("product"),
                    "suggested_quantity": row.get("reorder_quantity"),
                    "reason": row.get("risk_level"),
                    "supplier_lead_time": row.get("supplier_lead_time"),
                    "execution_enabled": False,
                },
                safety_checks_json={"allowed": bool(row), "requires_confirmation": True, "execution_not_implemented": True},
                expected_impact_json={"risk": row.get("risk_level")},
                evidence_json=evidence,
            )
        if classification.intent == CopilotIntent.ACTION_REQUEST_SEO_FIX:
            row = _first_row(tool_data, "get_seo_opportunities")
            return ActionProposalPlan(
                action_type=CopilotActionType.SEO_FIX,
                proposal_type="SEO_FIX",
                proposed_payload_json={
                    "proposal_type": "SEO_FIX",
                    "product": row.get("product"),
                    "suggested_title_or_keywords": row.get("suggested_improvement"),
                    "issue": row.get("issue"),
                    "execution_enabled": False,
                },
                safety_checks_json={"allowed": bool(row), "requires_confirmation": True, "execution_not_implemented": True},
                expected_impact_json={"visibility_evidence": row.get("visibility_evidence")},
                evidence_json=evidence,
            )
        if classification.intent == CopilotIntent.ACTION_REQUEST_DEAD_STOCK_RECOVERY:
            row = _first_row(tool_data, "get_dead_stock_recovery")
            action_type = CopilotActionType.BUNDLE_PLAN if "bundle" in question.casefold() else CopilotActionType.DISCOUNT_PLAN
            return ActionProposalPlan(
                action_type=action_type,
                proposal_type="DEAD_STOCK_RECOVERY",
                proposed_payload_json={
                    "proposal_type": "DEAD_STOCK_RECOVERY",
                    "product": row.get("product"),
                    "requested_change": _requested_change(question),
                    "recovery_action": row.get("recovery_action"),
                    "suggestion": row.get("potential_recovery_range"),
                    "execution_enabled": False,
                },
                safety_checks_json={"allowed": bool(row), "requires_confirmation": True, "execution_not_implemented": True},
                expected_impact_json={"expected_recovery": row.get("potential_recovery_range")},
                evidence_json=evidence,
            )
        return ActionProposalPlan(
            action_type=CopilotActionType.MANUAL_REVIEW,
            proposal_type="MANUAL_REVIEW",
            proposed_payload_json={"proposal_type": "MANUAL_REVIEW", "question": question, "execution_enabled": False},
            safety_checks_json={"allowed": False, "requires_confirmation": True, "execution_not_implemented": True},
            expected_impact_json=None,
            evidence_json=evidence,
        )

    def _expire_if_needed(self, proposal: CopilotActionProposal) -> CopilotActionProposal:
        if (
            proposal.expires_at is not None
            and proposal.expires_at <= self._now_utc()
            and proposal.status == CopilotActionProposalStatus.PROPOSED
        ):
            proposal.status = CopilotActionProposalStatus.EXPIRED
            return self._repository.save_action_proposal(proposal)
        return proposal

    def _now_utc(self) -> datetime:
        if self._now is not None:
            return self._now
        return datetime.now(timezone.utc)


def _collect_evidence(tool_results: list[ToolExecutionResult]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for result in tool_results:
        evidence.extend(result.evidence)
    return evidence


def _collect_missing(tool_results: list[ToolExecutionResult]) -> list[str]:
    missing: list[str] = []
    for result in tool_results:
        missing.extend(result.missing_data)
        if result.error:
            missing.append(result.error.get("message", "Tool failed safely."))
    return missing


def _collect_blocked_reasons(tool_results: list[ToolExecutionResult]) -> list[str]:
    reasons: list[str] = []
    for result in tool_results:
        data = result.data if isinstance(result.data, dict) else {}
        blocked = data.get("blocked_reasons")
        if isinstance(blocked, list):
            reasons.extend(str(item) for item in blocked)
        if result.error:
            reasons.append(result.error.get("message", "Tool blocked safely."))
    return reasons


def _first_row(tool_data: dict[str, Any], tool_name: str) -> dict[str, Any]:
    data = tool_data.get(tool_name)
    if not isinstance(data, dict):
        return {}
    for key in ("recommendations", "promotions", "recovery", "opportunities", "actions"):
        rows = data.get(key)
        if isinstance(rows, list) and rows:
            return rows[0] if isinstance(rows[0], dict) else {}
    return {}


def _first_value(tool_data: dict[str, Any], key: str) -> Any:
    for value in tool_data.values():
        found = _find_key(value, key)
        if found is not None:
            return found
    return None


def _find_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for item in value.values():
            found = _find_key(item, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None


def _requested_change(question: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"raw_request": question}
    percent = re.search(r"(\d+(?:\.\d+)?)\s*%", question or "")
    if percent:
        payload["percentage"] = str(Decimal(percent.group(1)))
    price = re.search(r"(?:price|৳|tk|bdt)\s*(\d+(?:\.\d+)?)", question or "", flags=re.IGNORECASE)
    if price:
        payload["price"] = str(Decimal(price.group(1)))
    if "bundle" in question.casefold():
        payload["promotion_type"] = "BUNDLE"
    if "discount" in question.casefold():
        payload["promotion_type"] = "DISCOUNT"
    return payload


def _looks_like_discount(question: str) -> bool:
    normalized = question.casefold()
    return "discount" in normalized or "%" in normalized
