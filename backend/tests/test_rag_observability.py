from __future__ import annotations

import unittest

from app.services.rag_observability import record_rag_retrieval_quality, reset_metrics
from app.services.copilot.observability import rag_quality_snapshot


class RagObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_metrics()

    def test_quality_summary_contains_aggregate_counts_only(self):
        record_rag_retrieval_quality(
            keyword_result_count=4,
            vector_result_count=6,
            fused_result_count=7,
            final_context_count=3,
            top_score=0.91,
            average_score=0.73,
            filtered_by_seller_count=2,
            stale_result_count=1,
            duration_ms=17,
        )

        payload = rag_quality_snapshot()
        self.assertEqual(4, payload["counters"]["rag_keyword_results_total"])
        self.assertEqual(6, payload["counters"]["rag_vector_results_total"])
        self.assertEqual(3, payload["counters"]["rag_final_context_total"])
        self.assertEqual(2, payload["counters"]["rag_filtered_by_seller_total"])
        self.assertNotIn("embedding", str(payload).lower())
        self.assertNotIn("chunk_text", str(payload).lower())

    def test_no_result_is_counted(self):
        record_rag_retrieval_quality(
            keyword_result_count=0,
            vector_result_count=0,
            fused_result_count=0,
            final_context_count=0,
            top_score=None,
            average_score=None,
            filtered_by_seller_count=0,
            stale_result_count=0,
            duration_ms=1,
        )

        self.assertEqual(1, rag_quality_snapshot()["counters"]["rag_retrieval_no_result_total"])


if __name__ == "__main__":
    unittest.main()
