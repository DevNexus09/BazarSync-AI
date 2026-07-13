from __future__ import annotations

from types import SimpleNamespace
from dataclasses import replace
import time
import unittest
from uuid import uuid4

from app.models.copilot_telemetry import CopilotRunTelemetry
from app.services.copilot.observability import capability_snapshot
from app.services.copilot.telemetry import (
    CopilotTelemetrySnapshot,
    derive_planner_miss_reasons,
    normalize_miss_reasons,
    persist_copilot_run,
)
from app.services.rag_observability import reset_metrics, snapshot_metrics
from app.services.copilot.tool_registry import CopilotToolContext, CopilotToolRegistry, ToolExecutionStatus


class _Session:
    def __init__(self) -> None:
        self.items = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, item) -> None:
        self.items.append(item)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _SlowToolData:
    def verify_product_owned(self, **kwargs) -> bool:
        del kwargs
        return True

    def count_products(self, **kwargs):
        del kwargs
        time.sleep(0.01)
        return {"count": 0}, []


class CopilotObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_metrics()

    def test_planner_miss_codes_are_allowlisted_and_bounded(self):
        plan = SimpleNamespace(
            required_domains=[],
            metric_plan=[],
            tool_plan=[],
            safety_flags=["INVALID_TOOL_ARGS:foo", "TOOL_LIMIT_ENFORCED", "UNSUPPORTED_METRIC:revenue"],
            needs_clarification=True,
            question_type="METRIC",
        )
        reasons = derive_planner_miss_reasons(
            plan=plan,
            include_current_data=False,
            include_memory=False,
        )
        self.assertEqual(
            [
                "NO_DOMAIN_MATCH",
                "NO_METRIC_MATCH",
                "NO_TOOL_MATCH",
                "CURRENT_DATA_DISABLED",
                "MEMORY_DISABLED",
                "AMBIGUOUS_ENTITY",
                "METRIC_NOT_EXECUTABLE",
                "INVALID_FILTER",
                "TOOL_LIMIT_REACHED",
                "VALIDATION_FALLBACK",
            ],
            reasons,
        )
        self.assertEqual(["NO_DOMAIN_MATCH", "RAG_NO_RESULTS"], normalize_miss_reasons(["NO_DOMAIN_MATCH:detail", "RAG_NO_RESULTS", "not_allowed"]))

    def test_telemetry_persists_bounded_metadata_without_question_or_prompt(self):
        session = _Session()
        snapshot = CopilotTelemetrySnapshot(
            run_id=uuid4(),
            seller_id=uuid4(),
            conversation_id=uuid4(),
            request_mode="BOTH",
            question_type="OVERVIEW",
            selected_domains=["INVENTORY"],
            selected_metrics=["stockout_risk_count"],
            selected_tools=["get_stockout_summary"],
            planner_status="PLANNED",
            planner_fallback_used=False,
            clarification_requested=False,
            tools_succeeded=1,
            tools_failed=0,
            rag_requested=True,
            rag_result_count=2,
            evidence_count=2,
            missing_data_count=0,
            final_confidence="HIGH",
            result_status="SUCCESS",
            planner_miss_reasons=[],
            planner_duration_ms=3,
            tool_duration_ms=8,
            rag_duration_ms=4,
            groq_duration_ms=11,
            total_duration_ms=24,
        )

        persist_copilot_run(session, snapshot=snapshot)

        self.assertEqual(1, session.commits)
        self.assertIsInstance(session.items[0], CopilotRunTelemetry)
        stored = session.items[0]
        self.assertEqual(snapshot.seller_id, stored.seller_id)
        self.assertFalse(hasattr(stored, "question"))
        self.assertFalse(hasattr(stored, "prompt"))
        metrics = snapshot_metrics()["counters"]
        self.assertEqual(1, metrics["copilot_runs_total"])

    def test_capability_summary_does_not_expose_internal_paths(self):
        payload = capability_snapshot()

        self.assertGreater(payload["metrics"]["declared"], 0)
        self.assertGreater(payload["tools"]["registered"], 0)
        self.assertIn("rag_sources", payload)
        self.assertFalse(any("app.services" in str(value) for value in payload.values()))

    def test_tool_over_budget_returns_safe_timeout(self):
        registry = CopilotToolRegistry(data_access=_SlowToolData())
        registry._tools["count_products"] = replace(registry.get_tool("count_products"), max_runtime_ms=1)

        result = registry.execute(
            name="count_products",
            context=CopilotToolContext(seller_id=uuid4()),
            arguments={},
        )

        self.assertEqual(ToolExecutionStatus.FAILED, result.status)
        self.assertEqual("TOOL_TIMEOUT", result.error["code"])
        self.assertNotIn("traceback", str(result).lower())


if __name__ == "__main__":
    unittest.main()
