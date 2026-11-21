"""Deterministic ranking and compatibility for already evaluated candidates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.recommendation import RecommendationAction, RecommendationConfidence
from app.schemas.recommendation_candidate import (
    CandidateEngine,
    CandidateStatus,
    RecommendationCandidate,
    RecoveryParameters,
    ReorderParameters,
)
from app.schemas.recommendation_decision import RecommendationDecisionContext

from app.services.action_evaluation_service import (
    PRICE_ACTIONS,
    STOCK_RECOVERY,
    ActionEvaluation,
    ActionEvaluationPolicy,
    ActionEvaluationService,
    candidate_price,
)

RECOVERY_ACTIONS = STOCK_RECOVERY | {
    DeadStockRecoveryAction.SEO_FIX,
    DeadStockRecoveryAction.MANUAL_REVIEW,
}


@dataclass(frozen=True)
class EngineEvaluation:
    engine: CandidateEngine
    candidate: RecommendationCandidate | None = None
    reason_codes: tuple[str, ...] = ()
    guard: dict[str, Any] | None = None
    action_evaluation: ActionEvaluation | None = None

    def to_context(self) -> dict[str, Any]:
        return {
            "engine": self.engine.value,
            "status": self.candidate.evaluation_status.value
            if self.candidate
            else CandidateStatus.INSUFFICIENT_EVIDENCE.value,
            "candidate": self.candidate.model_dump(mode="json")
            if self.candidate
            else None,
            "reason_codes": list(self.reason_codes),
            "final_margin_guard": self.guard,
            **(
                {"action_evaluation": self.action_evaluation.model_dump(mode="json")}
                if self.action_evaluation
                else {}
            ),
        }


@dataclass(frozen=True)
class RecommendationDecision:
    context: RecommendationDecisionContext
    evaluations: tuple[EngineEvaluation, ...]
    analytics: dict[str, Any]
    primary: RecommendationCandidate | None
    supporting: tuple[RecommendationCandidate, ...]
    reason_codes: tuple[str, ...]
    action_policy: ActionEvaluationPolicy | None = None

    @property
    def action(self) -> RecommendationAction:
        return self.primary.action_type if self.primary else RecommendationAction.HOLD

    @property
    def target_price(self) -> Decimal | None:
        if self.primary and self.primary.action_type in PRICE_ACTIONS:
            return candidate_price(self.primary)
        return None

    @property
    def confidence(self) -> RecommendationConfidence:
        score = self.primary.confidence if self.primary else None
        # Engine confidence is a rule score. Cap the displayed classification
        # until a shared, out-of-time calibration is available.
        return (
            RecommendationConfidence.MEDIUM
            if self.action != RecommendationAction.HOLD
            and score is not None
            and score >= 50
            else RecommendationConfidence.LOW
        )

    def to_context(self) -> dict[str, Any]:
        return {
            "version": 1,
            **(
                {"action_evaluation_policy": self.action_policy.model_dump(mode="json")}
                if self.action_policy
                else {}
            ),
            "inputs": self.context.model_dump(mode="json", exclude={"competitors"}),
            "primary_action": self.action.value,
            "primary_candidate_id": str(self.primary.candidate_id)
            if self.primary
            else None,
            "supporting_candidate_ids": [
                str(item.candidate_id) for item in self.supporting
            ],
            "supporting_advice": (
                [
                    {
                        "action": "HOLD",
                        "scope": "base_price",
                        "reason_code": "KEEP_PRICE_WHILE_REPLENISHING",
                    }
                ]
                if self.action == RecommendationAction.REORDER
                else []
            ),
            "evaluations": [item.to_context() for item in self.evaluations],
            "reason_codes": list(self.reason_codes),
        }


def reject_candidate(item: EngineEvaluation, *reasons: str) -> EngineEvaluation:
    candidate = item.candidate
    assert candidate is not None
    candidate = candidate.model_copy(
        update={
            "evaluation_status": CandidateStatus.REJECTED,
            "rejection_reasons": reasons,
        }
    )
    return replace(item, candidate=candidate)


def before_selection(item: EngineEvaluation) -> EngineEvaluation:
    candidate = item.candidate
    if candidate is None:
        return item
    assessment = item.action_evaluation
    if (
        (
            assessment
            and assessment.preference_rejections
            and candidate.rejection_reasons == assessment.preference_rejections
        )
        or candidate.evaluation_status == CandidateStatus.SELECTED
        or candidate.rejection_reasons
        in (
            ("INCOMPATIBLE_WITH_PRIMARY_ACTION",),
            ("INCOMPATIBLE_WITH_SUPPORTING_ACTION",),
        )
    ):
        return replace(
            item,
            candidate=candidate.model_copy(
                update={
                    "evaluation_status": CandidateStatus.ELIGIBLE,
                    "rejection_reasons": (),
                }
            ),
        )
    return item


def _priority(candidate: RecommendationCandidate) -> tuple[int, date, Decimal, str]:
    params = candidate.proposed_parameters
    if candidate.action_type == RecommendationAction.REORDER:
        rank = 0
    elif candidate.action_type in PRICE_ACTIONS:
        rank = 1
    elif isinstance(params, RecoveryParameters) and params.action in RECOVERY_ACTIONS:
        rank = 2
    else:
        rank = 3
    deadline = (
        params.deadline if rank == 0 and isinstance(params, ReorderParameters) else None
    )
    impact = candidate.estimated_financial_impact
    profit = (
        impact.profit_delta
        if impact and impact.profit_delta is not None
        else Decimal(0)
    )
    return (
        rank,
        deadline or date.max,
        -profit,
        candidate.source_engine.value + ":" + candidate.action_type.value,
    )


def _compatible(
    primary: RecommendationCandidate, candidate: RecommendationCandidate
) -> bool:
    params = candidate.proposed_parameters
    if candidate_price(primary) is not None and candidate_price(candidate) is not None:
        return False
    if (
        primary.action_type == RecommendationAction.RAISE
        and isinstance(params, RecoveryParameters)
        and params.action in STOCK_RECOVERY
    ):
        return False
    if primary.action_type == RecommendationAction.REORDER:
        return candidate.action_type == RecommendationAction.HOLD and not (
            isinstance(params, RecoveryParameters) and params.action in STOCK_RECOVERY
        )
    return True


def _apply_evaluator(
    context: RecommendationDecisionContext,
    item: EngineEvaluation,
    evaluator: ActionEvaluationService,
    at: datetime | None,
) -> EngineEvaluation:
    candidate = item.candidate
    if candidate is None:
        return item
    report = evaluator.evaluate(candidate, context, final_guard=item.guard, at=at)
    item = replace(item, action_evaluation=report)
    if candidate.evaluation_status == CandidateStatus.ELIGIBLE and not report.eligible:
        return reject_candidate(
            item, *report.hard_rejections, *report.preference_rejections
        )
    return item


def _scored_priority(
    item: EngineEvaluation,
) -> tuple[int, int, Decimal, int, date, str, str, str]:
    assert item.candidate is not None and item.action_evaluation is not None
    candidate, report = item.candidate, item.action_evaluation
    rank, deadline, _, label = _priority(candidate)
    return (
        int(not report.actionable),
        int(report.priority_tier != "due_reorder"),
        -(report.score or Decimal(0)),
        rank,
        deadline,
        label,
        candidate.proposed_parameters.model_dump_json(),
        candidate.candidate_id.hex,
    )


def _selection_plan(
    evaluations: tuple[EngineEvaluation, ...],
) -> list[RecommendationCandidate]:
    scored = sorted(
        (
            item
            for item in evaluations
            if item.action_evaluation
            and item.action_evaluation.eligible
            and item.candidate
            and item.candidate.evaluation_status == CandidateStatus.ELIGIBLE
        ),
        key=_scored_priority,
    )
    plan: list[RecommendationCandidate] = []
    for item in scored:
        candidate, report = item.candidate, item.action_evaluation
        assert candidate is not None and report is not None
        if (plan or report.actionable) and all(
            _compatible(selected, candidate) and _compatible(candidate, selected)
            for selected in plan
        ):
            plan.append(candidate)
    return plan


def select_decision(
    context: RecommendationDecisionContext,
    evaluations: tuple[EngineEvaluation, ...],
    analytics: dict[str, Any],
    *,
    evaluator: ActionEvaluationService | None = None,
    at: datetime | None = None,
) -> RecommendationDecision:
    planned_ids: set[UUID] | None = None
    if evaluator is not None:
        evaluations = tuple(
            _apply_evaluator(context, item, evaluator, at) for item in evaluations
        )
        plan = _selection_plan(evaluations)
        primary = plan[0] if plan else None
        planned_ids = {candidate.candidate_id for candidate in plan}
    else:
        ranked = sorted(
            (
                item.candidate
                for item in evaluations
                if item.candidate
                and item.candidate.evaluation_status == CandidateStatus.ELIGIBLE
            ),
            key=_priority,
        )
        primary = next((item for item in ranked if _priority(item)[0] < 3), None)
    selected: list[RecommendationCandidate] = []
    evaluated = []
    for item in evaluations:
        candidate = item.candidate
        if (
            candidate
            and candidate.evaluation_status == CandidateStatus.ELIGIBLE
            and primary
        ):
            compatible_with_primary = _compatible(primary, candidate) and (
                evaluator is None or _compatible(candidate, primary)
            )
            if (
                candidate.candidate_id in planned_ids
                if planned_ids is not None
                else candidate is primary or compatible_with_primary
            ):
                candidate = candidate.model_copy(
                    update={"evaluation_status": CandidateStatus.SELECTED}
                )
                selected.append(candidate)
                item = replace(item, candidate=candidate)
            else:
                reason = (
                    "INCOMPATIBLE_WITH_SUPPORTING_ACTION"
                    if compatible_with_primary
                    else "INCOMPATIBLE_WITH_PRIMARY_ACTION"
                )
                item = reject_candidate(item, reason)
        evaluated.append(item)
    primary = next(
        (
            item
            for item in selected
            if primary and item.candidate_id == primary.candidate_id
        ),
        None,
    )
    reasons = list(context.quality_flags)
    for item in evaluated:
        reasons.extend(item.reason_codes)
        if item.candidate:
            reasons.extend(item.candidate.rejection_reasons)
            if (
                item.candidate.evaluation_status
                == CandidateStatus.INSUFFICIENT_EVIDENCE
            ):
                reasons.append(f"{item.engine.value.upper()}_INSUFFICIENT_EVIDENCE")
    if primary:
        reasons.append(f"{primary.source_engine.value.upper()}_SELECTED")
    else:
        reasons.append("NO_SUPPORTED_ACTION")
    return RecommendationDecision(
        context,
        tuple(evaluated),
        analytics,
        primary,
        tuple(item for item in selected if item is not primary),
        tuple(dict.fromkeys(reasons)),
        evaluator.policy if evaluator is not None else None,
    )
