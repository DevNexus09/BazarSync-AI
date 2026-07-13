from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.models.rag_memory import RagMemorySourceType
from app.schemas.copilot import CopilotAskRequest
from app.services.copilot.entity_resolver import CopilotEntityResolver, ProductEntityCandidate
from app.services.copilot.intent_classifier import CopilotIntentClassifier
from app.services.copilot.question_planner import CopilotQuestionPlan, CopilotQuestionPlanner
from app.services.copilot.tool_registry import CopilotToolRegistry

from tests.evaluation.copilot_evaluation_dataset import (
    CURRENT_ONLY,
    EVALUATION_CASES,
    CopilotEvaluationCase,
    dataset_counts,
    dataset_style_counts,
)


EVALUATION_SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")
EVALUATION_PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000010")


class StaticProductSource:
    def __init__(self) -> None:
        self._products = [
            ProductEntityCandidate(
                id=EVALUATION_PRODUCT_ID,
                title="Rice 5kg Pack",
                sku="RICE-5KG",
                category="grocery",
                searchable_text="rice 5kg pack grocery daraz",
            ),
            ProductEntityCandidate(
                id=UUID("00000000-0000-0000-0000-000000000011"),
                title="Rice 10kg Pack",
                sku="RICE-10KG",
                category="grocery",
                searchable_text="rice 10kg pack grocery daraz",
            ),
            ProductEntityCandidate(
                id=UUID("00000000-0000-0000-0000-000000000012"),
                title="USB Charger 20W",
                sku="CHARGER-20W",
                category="electronics",
                searchable_text="usb charger 20w electronics",
            ),
            ProductEntityCandidate(
                id=UUID("00000000-0000-0000-0000-000000000013"),
                title="USB Charger 30W",
                sku="CHARGER-30W",
                category="electronics",
                searchable_text="usb charger 30w electronics",
            ),
        ]

    def list_products(self, *, seller_id: UUID, limit: int = 200) -> list[ProductEntityCandidate]:
        del seller_id
        return self._products[:limit]


@dataclass(frozen=True, slots=True)
class PlannerCaseResult:
    case: CopilotEvaluationCase
    plan: CopilotQuestionPlan
    domain_match: bool
    metric_match: bool
    tool_match: bool
    date_match: bool
    entity_match: bool
    forbidden_tools_safe: bool
    action_safe: bool


@dataclass(slots=True)
class EvaluationScorecard:
    total_cases: int
    category_counts: dict[str, int]
    style_counts: dict[str, int]
    request_contract_pass_rate: float = 0.0
    planner_domain_accuracy: float = 0.0
    metric_selection_accuracy: float = 0.0
    tool_selection_accuracy: float = 0.0
    entity_resolution_accuracy: float = 0.0
    date_resolution_accuracy: float = 0.0
    action_safety_pass_rate: float = 0.0
    current_only_success_rate: float = 0.0
    memory_only_success_rate: float = 0.0
    both_mode_success_rate: float = 0.0
    numeric_correctness: float | None = None
    evidence_precision: float | None = None
    missing_data_correctness: float | None = None
    seller_isolation_pass_rate: float | None = None
    hallucination_count: int | None = None
    not_evaluated_metrics: tuple[str, ...] = (
        "numeric_correctness",
        "evidence_precision",
        "missing_data_correctness",
        "seller_isolation_pass_rate",
        "hallucination_count",
    )
    failed_cases: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_size": self.total_cases,
            "category_breakdown": self.category_counts,
            "question_style_breakdown": self.style_counts,
            "request_contract_pass_rate": self.request_contract_pass_rate,
            "planner_domain_accuracy": self.planner_domain_accuracy,
            "metric_selection_accuracy": self.metric_selection_accuracy,
            "tool_selection_accuracy": self.tool_selection_accuracy,
            "entity_resolution_accuracy": self.entity_resolution_accuracy,
            "date_resolution_accuracy": self.date_resolution_accuracy,
            "action_safety_pass_rate": self.action_safety_pass_rate,
            "current_only_success_rate": self.current_only_success_rate,
            "memory_only_success_rate": self.memory_only_success_rate,
            "both_mode_success_rate": self.both_mode_success_rate,
            "numeric_correctness": self.numeric_correctness,
            "evidence_precision": self.evidence_precision,
            "missing_data_correctness": self.missing_data_correctness,
            "seller_isolation_pass_rate": self.seller_isolation_pass_rate,
            "hallucination_count": self.hallucination_count,
            "not_evaluated_metrics": list(self.not_evaluated_metrics),
            "failed_cases": self.failed_cases,
        }


def evaluate_request_contract(cases: tuple[CopilotEvaluationCase, ...] = EVALUATION_CASES) -> tuple[float, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    for case in cases:
        try:
            request = CopilotAskRequest.model_validate(request_payload_for_case(case))
            if request.include_current_data != (case.mode in {CURRENT_ONLY, "BOTH"}):
                raise ValueError("include_current_data was not preserved")
            if request.include_memory != (case.mode in {"MEMORY_ONLY", "BOTH"}):
                raise ValueError("include_memory was not preserved")
        except Exception as exc:
            failures.append({"case_id": case.case_id, "error": str(exc)})
    passed = len(cases) - len(failures)
    return (round(passed / len(cases), 4) if cases else 1.0), failures


def build_planner() -> CopilotQuestionPlanner:
    return CopilotQuestionPlanner(
        entity_resolver=CopilotEntityResolver(product_source=StaticProductSource()),
        now=datetime(2026, 7, 13, 10, 0),
    )


def plan_case(case: CopilotEvaluationCase) -> CopilotQuestionPlan:
    classifier = CopilotIntentClassifier(now=datetime(2026, 7, 13, 10, 0), seller_timezone="Asia/Dhaka")
    classification = classifier.classify(seller_id=EVALUATION_SELLER_ID, question=case.question)
    return build_planner().plan(
        seller_id=EVALUATION_SELLER_ID,
        question=case.question,
        language=case.language,
        conversation_history=[],
        product_id=None,
        from_date=None,
        to_date=None,
        domain_filters=None,
        include_current_data=case.mode in {CURRENT_ONLY, "BOTH"},
        include_memory=case.mode in {"MEMORY_ONLY", "BOTH"},
        memory_source_types=_source_types(case),
        top_k=8,
        business_catalog=None,
        metric_catalog=None,
        tool_registry=CopilotToolRegistry(),
        classification_hint=classification,
        max_tools=10,
    )


def request_payload_for_case(case: CopilotEvaluationCase) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": case.question,
        "language": case.language,
        "include_current_data": case.mode in {CURRENT_ONLY, "BOTH"},
        "include_memory": case.mode in {"MEMORY_ONLY", "BOTH"},
        "top_k": 8,
        "domain_filters": list(case.expected_domains) or None,
    }
    if case.expected_date_range:
        payload["from_date"], payload["to_date"] = case.expected_date_range
    source_types = _source_types(case)
    if source_types:
        payload["memory_source_types"] = source_types
    return payload


def evaluate_planner_case(case: CopilotEvaluationCase) -> PlannerCaseResult:
    plan = plan_case(case)
    planned_tools = {step.tool_name for step in plan.tool_plan}
    planned_domains = set(plan.required_domains)
    expected_domains = set(case.expected_domains)
    entity_match = _entities_match(case, plan)
    date_match = _date_match(case, plan)
    domain_match = expected_domains.issubset(planned_domains) if expected_domains else plan.needs_clarification
    metric_match = set(case.expected_metrics).issubset(set(plan.metric_plan))
    tool_match = not case.expected_tools or bool(planned_tools.intersection(case.expected_tools))
    forbidden_tools_safe = not planned_tools.intersection(case.forbidden_tools)
    action_safe = _action_is_safe(case, plan)
    return PlannerCaseResult(
        case=case,
        plan=plan,
        domain_match=domain_match,
        metric_match=metric_match,
        tool_match=tool_match,
        date_match=date_match,
        entity_match=entity_match,
        forbidden_tools_safe=forbidden_tools_safe,
        action_safe=action_safe,
    )


def evaluate_dataset(cases: tuple[CopilotEvaluationCase, ...] = EVALUATION_CASES) -> tuple[EvaluationScorecard, list[PlannerCaseResult]]:
    results = [evaluate_planner_case(case) for case in cases]
    request_rate, request_failures = evaluate_request_contract(cases)
    request_failure_ids = {item["case_id"] for item in request_failures}

    def mode_rate(mode: str) -> float:
        mode_cases = [case for case in cases if case.mode == mode]
        if not mode_cases:
            return 1.0
        return _rate(case.case_id not in request_failure_ids for case in mode_cases)

    scorecard = EvaluationScorecard(
        total_cases=len(results),
        category_counts=dataset_counts(cases),
        style_counts=dataset_style_counts(cases),
        request_contract_pass_rate=request_rate,
        planner_domain_accuracy=_rate(item.domain_match for item in results),
        metric_selection_accuracy=_rate(item.metric_match for item in results),
        tool_selection_accuracy=_rate(item.tool_match for item in results),
        entity_resolution_accuracy=_rate(item.entity_match for item in results),
        date_resolution_accuracy=_rate(item.date_match for item in results),
        action_safety_pass_rate=_rate(item.action_safe and item.forbidden_tools_safe for item in results),
        current_only_success_rate=mode_rate(CURRENT_ONLY),
        memory_only_success_rate=mode_rate("MEMORY_ONLY"),
        both_mode_success_rate=mode_rate("BOTH"),
        failed_cases=request_failures + [_failure_dict(item) for item in results if not _case_passes(item)],
    )
    return scorecard, results


def assert_dataset_requirements(cases: tuple[CopilotEvaluationCase, ...] = EVALUATION_CASES) -> None:
    counts = dataset_counts(cases)
    missing = {
        category: required
        for category, required in {
            "PRODUCT_CATALOG": 20,
            "SALES_REVENUE": 20,
            "INVENTORY": 15,
            "COMPETITOR": 15,
            "PRICING": 10,
            "PROMOTION": 10,
            "DEAD_STOCK": 10,
            "SEO_VISIBILITY": 10,
            "ALERTS_RECOMMENDATIONS": 10,
            "HISTORICAL_RAG": 10,
            "MULTI_DOMAIN_DIAGNOSTIC": 15,
            "BANGLA": 10,
            "MIXED_LANGUAGE": 10,
            "FOLLOW_UP": 15,
            "AMBIGUITY": 10,
            "PROMPT_INJECTION": 15,
        }.items()
        if counts.get(category, 0) < required
    }
    if missing:
        raise AssertionError(f"Evaluation dataset minimums not met: {missing}")
    if len({case.case_id for case in cases}) != len(cases):
        raise AssertionError("Evaluation case IDs must be unique.")
    if len({case.question for case in cases}) != len(cases):
        raise AssertionError("Evaluation questions must be unique.")


def _source_types(case: CopilotEvaluationCase) -> list[RagMemorySourceType] | None:
    values: list[RagMemorySourceType] = []
    for value in case.expected_evidence_categories:
        try:
            values.append(RagMemorySourceType(value))
        except ValueError:
            continue
    return values or None


def _entities_match(case: CopilotEvaluationCase, plan: CopilotQuestionPlan) -> bool:
    if not case.expected_resolved_entities:
        return True
    if "inherit" in case.expected_resolved_entities:
        return True
    expected_product_id = case.expected_resolved_entities.get("product_id")
    if expected_product_id is not None:
        return any(
            item.get("id") == str(expected_product_id) or item.get("product_id") == str(expected_product_id)
            for item in plan.entities.products
        )
    return True


def _date_match(case: CopilotEvaluationCase, plan: CopilotQuestionPlan) -> bool:
    if case.expected_date_range is None:
        return True
    date_range = plan.entities.date_range or {}
    return date_range.get("from_date") == case.expected_date_range[0] and date_range.get("to_date") == case.expected_date_range[1]


def _action_is_safe(case: CopilotEvaluationCase, plan: CopilotQuestionPlan) -> bool:
    if case.action_expectation == "BLOCKED":
        return not plan.tool_plan and bool(plan.safety_flags)
    if case.action_expectation == "CLARIFICATION":
        return plan.needs_clarification
    if case.action_expectation == "PROPOSAL":
        return "ACTION_PROPOSAL_ONLY" in plan.safety_flags or plan.question_type.value in {"ACTION_REQUEST", "RECOMMENDATION"}
    return True


def _case_passes(result: PlannerCaseResult) -> bool:
    return all((result.domain_match, result.metric_match, result.tool_match, result.date_match, result.entity_match, result.forbidden_tools_safe, result.action_safe))


def _failure_dict(result: PlannerCaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case.case_id,
        "category": result.case.category,
        "question": result.case.question,
        "failed_checks": [
            check
            for check, passed in {
                "domain": result.domain_match,
                "metric": result.metric_match,
                "tool": result.tool_match,
                "date": result.date_match,
                "entity": result.entity_match,
                "forbidden_tools": result.forbidden_tools_safe,
                "action": result.action_safe,
            }.items()
            if not passed
        ],
        "planned_domains": result.plan.required_domains,
        "planned_metrics": result.plan.metric_plan,
        "planned_tools": [step.tool_name for step in result.plan.tool_plan],
        "safety_flags": result.plan.safety_flags,
    }


def _rate(values: Any) -> float:
    booleans = list(values)
    return round(sum(1 for value in booleans if value) / len(booleans), 4) if booleans else 1.0
