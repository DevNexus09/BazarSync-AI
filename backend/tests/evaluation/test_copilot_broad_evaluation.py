from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from app.api.v1 import copilot as copilot_api
from app.models.rag_memory import RagMemorySourceType
from app.models.seller import Seller
from app.schemas.copilot import CopilotAskRequest
from app.services.copilot.copilot_response_validator import CopilotResponseValidationError, CopilotResponseValidator
from app.services.copilot.context_builder import CopilotAnswerContext
from app.services.copilot.intent_classifier import CopilotIntentClassifier
from app.services.copilot.metric_catalog import MetricCatalogService
from app.services.copilot.metric_execution_service import MetricExecutionService
from app.services.copilot.question_planner import CopilotPlanningContext
from app.services.copilot.query_constraints import CatalogValidationError
from app.services.copilot.tool_registry import CopilotToolRegistry
from app.services.rag_retrieval_service import RagRetrievalService
from app.services.rag_observability import reset_metrics
from app.services.rag_retrieval_service import settings as rag_retrieval_settings

from tests.evaluation.copilot_evaluation_dataset import EVALUATION_CASES, dataset_counts, dataset_style_counts
from tests.evaluation.copilot_evaluation_harness import (
    EVALUATION_PRODUCT_ID,
    EVALUATION_SELLER_ID,
    build_planner,
    evaluate_dataset,
    evaluate_request_contract,
    assert_dataset_requirements,
    request_payload_for_case,
)


class BroadCopilotEvaluationTests(unittest.TestCase):
    def test_dataset_meets_all_requested_minimums_and_has_unique_cases(self) -> None:
        assert_dataset_requirements()
        self.assertEqual(205, len(EVALUATION_CASES))
        self.assertGreaterEqual(len(dataset_counts()), 16)
        required_styles = {
            "count",
            "list",
            "filter",
            "grouping",
            "ranking",
            "comparison",
            "trend",
            "diagnostic",
            "overview",
            "missing-data",
            "historical recall",
            "follow-up",
            "action proposal",
        }
        self.assertTrue(required_styles.issubset(dataset_style_counts()))
        self.assertGreaterEqual(sum(1 for case in EVALUATION_CASES if case.language == "bn"), 20)
        self.assertGreaterEqual(sum(1 for case in EVALUATION_CASES if case.expected_numeric_result is not None), 8)

    def test_request_contract_accepts_every_case_and_preserves_modes(self) -> None:
        rate, failures = evaluate_request_contract()

        self.assertEqual(1.0, rate, failures[:3])
        for case in EVALUATION_CASES:
            request = CopilotAskRequest.model_validate(request_payload_for_case(case))
            self.assertEqual(case.question, request.question)
            self.assertEqual(case.mode in {"CURRENT_ONLY", "BOTH"}, request.include_current_data)
            self.assertEqual(case.mode in {"MEMORY_ONLY", "BOTH"}, request.include_memory)

    def test_planner_scorecard_is_reportable_without_calling_groq(self) -> None:
        scorecard, results = evaluate_dataset()

        self.assertEqual(len(EVALUATION_CASES), scorecard.total_cases)
        self.assertEqual(len(EVALUATION_CASES), len(results))
        for name, value in scorecard.to_dict().items():
            if name.endswith(("rate", "accuracy")) and value is not None:
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)
        # This is intentionally printed as a machine-readable baseline for CI.
        print(json.dumps(scorecard.to_dict(), sort_keys=True, default=str))

    def test_planner_never_selects_an_unregistered_tool_or_unsupported_metric(self) -> None:
        registry_names = {tool.name for tool in CopilotToolRegistry().list_tools()}
        catalog = MetricCatalogService()
        _, results = evaluate_dataset()

        for result in results:
            with self.subTest(case=result.case.case_id):
                planned_tools = {step.tool_name for step in result.plan.tool_plan}
                self.assertTrue(planned_tools.issubset(registry_names))
                for metric_key in result.plan.metric_plan:
                    metric = catalog.get_metric(metric_key)
                    self.assertTrue(metric.is_selectable_for_execution, metric_key)

    def test_metric_catalog_and_executor_parity_is_a_critical_gate(self) -> None:
        catalog = MetricCatalogService()
        service = MetricExecutionService(cast(Any, object()))

        catalog.validate_capability_contract(set(service._handlers))
        declared = {metric.metric_key for metric in catalog.list_metrics() if metric.is_selectable_for_execution}
        self.assertEqual(declared, set(service._handlers))

    def test_arbitrary_sql_is_rejected_before_database_execution(self) -> None:
        service = MetricExecutionService(cast(Any, object()))

        with self.assertRaises(CatalogValidationError):
            service.execute(seller_id=EVALUATION_SELLER_ID, metric_key="SELECT * FROM sellers")

    def test_answer_validator_rejects_unsupported_numbers_and_drops_unknown_evidence(self) -> None:
        context = CopilotAnswerContext(
            question="What happened?",
            question_type="DIAGNOSTIC",
            language="en",
            domains_used=["SALES_REVENUE"],
            tools_used=[{"name": "get_revenue_summary", "status": "SUCCEEDED"}],
            evidence=[{"evidence_id": "ev-1", "source_type": "sales", "title": "Revenue"}],
            missing_data=[],
            data_freshness=[],
            facts={},
            allowed_evidence_ids={"ev-1"},
            allowed_numbers={"20"},
            has_direct_evidence=True,
            has_memory_evidence=False,
            has_visibility_evidence=False,
            has_reliable_no_sales_evidence=False,
            has_financial_evidence=True,
            has_profit_margin_evidence=False,
        )
        payload = _answer_payload(
            answer="Revenue changed by 20.",
            evidence=[{"evidence_id": "ev-1"}, {"evidence_id": "forged-evidence"}],
        )

        result = CopilotResponseValidator().validate(payload, context=context)
        self.assertEqual(["forged-evidence"], result.removed_evidence_ids)
        self.assertEqual(["ev-1"], [item["evidence_id"] for item in result.payload["evidence"]])

        with self.assertRaises(CopilotResponseValidationError):
            CopilotResponseValidator().validate(_answer_payload(answer="Revenue changed by 99."), context=context)

    def test_action_execution_safety_gate_is_explicit(self) -> None:
        _, results = evaluate_dataset()
        action_cases = [item for item in results if item.case.action_expectation in {"BLOCKED", "PROPOSAL", "CLARIFICATION"}]

        self.assertTrue(action_cases)
        self.assertTrue(all(item.plan.question_type.value != "ACTION_REQUEST" or "ACTION_PROPOSAL_ONLY" in item.plan.safety_flags for item in action_cases if item.case.action_expectation == "PROPOSAL"))

    def test_followup_context_inherits_product_and_ambiguity_requests_clarification(self) -> None:
        planner = build_planner()
        classifier = CopilotIntentClassifier(
            now=datetime(2026, 7, 13, 10, 0),
            seller_timezone="Asia/Dhaka",
        )
        context = CopilotPlanningContext(
            active_products=[{"id": str(EVALUATION_PRODUCT_ID), "title": "Rice 5kg Pack"}],
            active_domains=["SALES_REVENUE"],
        )
        followup = planner.plan(
            seller_id=EVALUATION_SELLER_ID,
            question="What about last week?",
            language="en",
            conversation_history=[],
            product_id=None,
            from_date=None,
            to_date=None,
            domain_filters=None,
            include_current_data=True,
            include_memory=True,
            memory_source_types=None,
            top_k=8,
            business_catalog=None,
            metric_catalog=None,
            tool_registry=CopilotToolRegistry(),
            classification_hint=classifier.classify(seller_id=EVALUATION_SELLER_ID, question="What about last week?"),
            max_tools=10,
            planning_context=context,
        )
        self.assertEqual(str(EVALUATION_PRODUCT_ID), followup.entities.products[0]["product_id"])

        ambiguous_question = "Show me sales for charger."
        ambiguous = planner.plan(
            seller_id=EVALUATION_SELLER_ID,
            question=ambiguous_question,
            language="en",
            conversation_history=[],
            product_id=None,
            from_date=None,
            to_date=None,
            domain_filters=None,
            include_current_data=True,
            include_memory=True,
            memory_source_types=None,
            top_k=8,
            business_catalog=None,
            metric_catalog=None,
            tool_registry=CopilotToolRegistry(),
            classification_hint=classifier.classify(seller_id=EVALUATION_SELLER_ID, question=ambiguous_question),
            max_tools=10,
        )
        self.assertTrue(ambiguous.needs_clarification)
        self.assertIn("Which product", ambiguous.clarification_question or "")


class CopilotModeContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_memory_and_both_modes_reach_the_orchestrator(self) -> None:
        seller = Seller(id=EVALUATION_SELLER_ID, email="evaluation@example.com", password_hash="x")
        captured: list[Any] = []

        class CaptureOrchestrator:
            def __init__(self, db=None) -> None:
                del db

            async def ask(self, request):
                captured.append(request)
                return SimpleNamespace(
                    conversation_id=uuid4(),
                    assistant_message_id=uuid4(),
                    answer="Evidence-backed answer.",
                    summary="Summary.",
                    confidence="HIGH",
                    language=request.requested_language,
                    intent="LOOKUP",
                    tool_trace=[],
                    tools_used=[],
                    evidence=[],
                    missing_data=[],
                    data_freshness=[],
                    domains_used=[],
                    question_type="LOOKUP",
                    recommended_next_steps=[],
                    action_proposal=None,
                )

        class FakeDb:
            pass

        with patch.object(copilot_api, "CopilotOrchestrator", CaptureOrchestrator):
            for mode in ("CURRENT_ONLY", "MEMORY_ONLY", "BOTH"):
                payload = CopilotAskRequest(
                    question=f"Mode check {mode}",
                    include_current_data=mode in {"CURRENT_ONLY", "BOTH"},
                    include_memory=mode in {"MEMORY_ONLY", "BOTH"},
                    memory_source_types=[RagMemorySourceType.ALERT] if mode != "CURRENT_ONLY" else None,
                )
                await copilot_api.ask_copilot(payload, db=cast(Any, FakeDb()), current_seller=seller)

        self.assertEqual(3, len(captured))
        self.assertEqual((True, False), (captured[0].include_current_data, captured[0].include_memory))
        self.assertEqual((False, True), (captured[1].include_current_data, captured[1].include_memory))
        self.assertEqual((True, True), (captured[2].include_current_data, captured[2].include_memory))


class CopilotRagEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_metrics()
        # Fake distances in these cases are L2 distances; pin the legacy metric.
        metric = patch.object(rag_retrieval_settings, "rag_cosine_distance_enabled", False)
        metric.start()
        self.addCleanup(metric.stop)

    def test_rag_passes_seller_product_source_and_date_filters(self) -> None:
        seller_id = EVALUATION_SELLER_ID
        product_id = EVALUATION_PRODUCT_ID
        repository = _CaptureRagRepository(_rag_chunk(seller_id=seller_id, product_id=product_id))
        service = RagRetrievalService(repository=cast(Any, repository), embedding_service=cast(Any, _FakeEmbeddingService()), now=datetime(2026, 7, 13, tzinfo=timezone.utc))

        result = service.retrieve_context(
            seller_id=seller_id,
            product_id=product_id,
            source_types=[RagMemorySourceType.ALERT],
            from_event_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
            to_event_time=datetime(2026, 7, 12, tzinfo=timezone.utc),
            question="What alert happened?",
            min_similarity=0.1,
        )

        self.assertTrue(result.evidence_ids)
        self.assertEqual(seller_id, repository.vector_kwargs["seller_id"])
        self.assertEqual(product_id, repository.vector_kwargs["product_id"])
        self.assertEqual([RagMemorySourceType.ALERT], repository.vector_kwargs["source_types"])
        self.assertEqual(datetime(2026, 7, 1, tzinfo=timezone.utc), repository.vector_kwargs["from_event_time"])
        self.assertEqual(datetime(2026, 7, 12, tzinfo=timezone.utc), repository.vector_kwargs["to_event_time"])

    def test_rag_cross_seller_evidence_is_not_returned(self) -> None:
        other_chunk = _rag_chunk(seller_id=uuid4(), product_id=None)
        repository = _CaptureRagRepository(other_chunk)
        service = RagRetrievalService(repository=cast(Any, repository), embedding_service=cast(Any, _FakeEmbeddingService()))

        result = service.retrieve_context(seller_id=EVALUATION_SELLER_ID, question="What alert happened?", min_similarity=0.1)

        self.assertEqual("NO_CONTEXT", result.retrieval_confidence)

    def test_rag_reports_stale_memory_when_requested(self) -> None:
        stale = _rag_chunk(seller_id=EVALUATION_SELLER_ID, product_id=None, event_time=datetime(2025, 1, 1, tzinfo=timezone.utc))
        repository = _CaptureRagRepository(stale)
        service = RagRetrievalService(repository=cast(Any, repository), embedding_service=cast(Any, _FakeEmbeddingService()), now=datetime(2026, 7, 13, tzinfo=timezone.utc))

        result = service.retrieve_context(seller_id=EVALUATION_SELLER_ID, question="What alert happened?", include_stale=True, min_similarity=0.1)

        self.assertTrue(result.retrieved_chunks[0].is_stale)
        self.assertTrue(any("stale" in note.lower() for note in result.missing_data_notes))


class _FakeEmbeddingService:
    def embed_text(self, text: str) -> list[float]:
        del text
        return [0.1, 0.2, 0.3]


class _CaptureRagRepository:
    def __init__(self, chunk: Any) -> None:
        self.chunk = chunk
        self.vector_kwargs: dict[str, Any] = {}
        self.keyword_kwargs: dict[str, Any] = {}

    def vector_search(self, **kwargs):
        self.vector_kwargs = kwargs
        return [(self.chunk, 0.9)]

    def keyword_search(self, **kwargs):
        self.keyword_kwargs = kwargs
        return [self.chunk]

    def get_documents_by_ids(self, *, seller_id, document_ids):
        del seller_id
        return {
            document_id: SimpleNamespace(
                id=document_id,
                seller_id=EVALUATION_SELLER_ID,
                deleted_at=None,
                source_type=RagMemorySourceType.ALERT,
                product_id=self.chunk.product_id,
                source_table="alerts",
                source_id="alert-1",
                title="Inventory alert",
                event_time=self.chunk.event_time,
            )
            for document_id in document_ids
        }


def _rag_chunk(*, seller_id: UUID, product_id: UUID | None, event_time: datetime | None = None):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=seller_id,
        memory_document_id=uuid4(),
        product_id=product_id,
        source_type=RagMemorySourceType.ALERT,
        chunk_text="Inventory alert has 20 units.",
        metadata_json={},
        event_time=event_time or datetime(2026, 7, 5, tzinfo=timezone.utc),
        deleted_at=None,
    )


def _answer_payload(*, answer: str, evidence: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "answer": answer,
        "summary": "A grounded summary.",
        "confidence": "HIGH",
        "question_type": "DIAGNOSTIC",
        "language": "en",
        "domains_used": ["SALES_REVENUE"],
        "tools_used": [{"name": "get_revenue_summary", "status": "SUCCEEDED"}],
        "evidence": evidence or [{"evidence_id": "ev-1"}],
        "missing_data": [],
        "data_freshness": [],
        "recommended_next_steps": [],
        "action_proposal": None,
    }


if __name__ == "__main__":
    unittest.main()
