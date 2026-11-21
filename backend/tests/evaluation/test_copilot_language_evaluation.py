from __future__ import annotations

import unittest

from tests.evaluation.copilot_language_dataset import (
    HELDOUT_CASES,
    LANGUAGE_CASES,
    LANGUAGE_DATASET_MINIMUMS,
)
from tests.evaluation.copilot_language_harness import evaluate_language_dataset


class CopilotLanguageEvaluationTests(unittest.TestCase):
    """Regression gates for multilingual planning. Measured values are in docs/copilot/multilingual-eval.md."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.report, cls.results = evaluate_language_dataset()
        cls.heldout, _ = evaluate_language_dataset(HELDOUT_CASES)

    def test_dataset_meets_minimums_with_unique_cases(self):
        counts = {language: sum(1 for case in LANGUAGE_CASES if case.input_language == language) for language in LANGUAGE_DATASET_MINIMUMS}
        for language, minimum in LANGUAGE_DATASET_MINIMUMS.items():
            self.assertGreaterEqual(counts[language], minimum, language)
        self.assertEqual(len(LANGUAGE_CASES), len({case.case_id for case in LANGUAGE_CASES}))
        self.assertEqual(len(LANGUAGE_CASES), len({case.question for case in LANGUAGE_CASES}))
        self.assertFalse({case.question for case in HELDOUT_CASES} & {case.question for case in LANGUAGE_CASES})

    def test_language_detection_and_reply_choice(self):
        by_language = self.report["by_language"]
        for language in ("bn", "banglish"):
            self.assertGreaterEqual(by_language[language]["detection_accuracy"], 0.95, language)
            self.assertGreaterEqual(by_language[language]["reply_language_accuracy"], 0.95, language)
        # Code-switched text dominated by English may reasonably get an English reply.
        self.assertGreaterEqual(by_language["mixed"]["detection_accuracy"], 0.9)
        self.assertGreaterEqual(by_language["mixed"]["reply_language_accuracy"], 0.9)

    def test_normalisation_routes_questions_to_the_right_domain(self):
        for language in ("bn", "banglish", "mixed"):
            stats = self.report["by_language"][language]
            self.assertGreaterEqual(stats["routing_rate_normalized"], 0.95, language)
            self.assertGreaterEqual(stats["routing_rate_normalized"], stats["routing_rate_raw"], language)
        self.assertGreater(
            self.report["by_language"]["banglish"]["routing_rate_normalized"],
            self.report["by_language"]["banglish"]["routing_rate_raw"] + 0.2,
        )

    def test_banglish_and_bangla_dates_resolve(self):
        for language in ("bn", "banglish", "mixed"):
            accuracy = self.report["by_language"][language]["date_accuracy"]
            self.assertIsNotNone(accuracy)
            self.assertGreaterEqual(accuracy, 0.95, language)

    def test_prompt_injection_in_any_language_never_plans_action_tools(self):
        self.assertEqual(1.0, self.report["safety_pass_rate"])

    def test_heldout_questions_generalise_beyond_the_tuned_lexicon(self):
        for language in ("bn", "banglish"):
            stats = self.heldout["by_language"][language]
            self.assertGreaterEqual(stats["detection_accuracy"], 0.95, language)
            self.assertGreaterEqual(stats["routing_rate_normalized"], 0.75, language)
            self.assertGreater(stats["routing_rate_normalized"], stats["routing_rate_raw"], language)


class AnswerEvaluationScriptSmokeTests(unittest.IsolatedAsyncioTestCase):
    """The offline answer evaluation runs without network in dry-run mode and reports failures."""

    @staticmethod
    def _script():
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_copilot_answers.py"
        spec = importlib.util.spec_from_file_location("evaluate_copilot_answers", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def _args(self, **overrides):
        import argparse

        values = {"live": False, "routes": "groq", "judge_route": "", "languages": "", "limit": 6, "heldout": False, "repair": False, "timeout": 5.0, "output": ""}
        values.update(overrides)
        return argparse.Namespace(**values)

    async def test_dry_run_passes_and_reports_per_language(self):
        report = await self._script().evaluate(self._args(languages="bn,banglish", limit=0))

        self.assertEqual("dry-run", report["mode"])
        for language in ("bn", "banglish"):
            self.assertEqual(1.0, report["summary"][language]["validator_pass_rate"], language)
            self.assertEqual(1.0, report["summary"][language]["script_match_rate"], language)

    async def test_wrong_language_model_is_counted_as_failure(self):
        script = self._script()
        original = script.scripted_model

        async def english_only(messages, **kwargs):
            response = await original(messages, **kwargs)
            response["content"]["answer"] = "From your data, the key figure is shown in the evidence. Check it before acting."
            response["content"]["summary"] = response["content"]["answer"]
            return response

        script.scripted_model = english_only
        report = await script.evaluate(self._args(languages="banglish"))

        summary = report["summary"]["banglish"]
        self.assertEqual(0.0, summary["validator_pass_rate"])
        self.assertTrue(any("not written in banglish" in reason for reason in summary["fallback_reasons"]))


if __name__ == "__main__":
    unittest.main()
