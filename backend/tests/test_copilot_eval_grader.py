import json
from pathlib import Path
import unittest

from scripts.copilot_eval import FIXTURE, grade, value_present


class CopilotEvalGraderTests(unittest.TestCase):
    def test_numbers_match_with_grouping_rounding_sign_and_bangla_digits(self):
        self.assertTrue(value_present("290360.28", "Revenue was ৳2,90,360.28 in that period."))
        self.assertTrue(value_present("290360.28", "Revenue was about 290,360."))
        self.assertTrue(value_present("17287.94", "It fell by -17,287.94 BDT."))
        self.assertTrue(value_present("15", "আপনার ১৫টি পণ্য আছে।"))
        self.assertTrue(value_present("1874", "Price is 1,874.00 BDT"))
        self.assertFalse(value_present("290360.28", "Revenue was 290,361.28."))
        self.assertFalse(value_present("7", "Change was 7.03%"))

    def test_text_match_is_case_insensitive(self):
        self.assertTrue(value_present("NORTH STAR HAFSA", "Your top seller is North Star Hafsa ladies sneaker."))

    def test_grade_any_of_and_forbidden(self):
        case = {"expected_facts": [{"label": "x", "value": "invoice", "any_of": ["not recorded"]}], "must_not_contain": ["secret"], "expected_tools_any": []}
        self.assertTrue(grade(case, "Invoices are not recorded.", [])["passed"])
        self.assertFalse(grade(case, "Invoices are not recorded. secret", [])["passed"])

    def test_fixture_has_forty_well_formed_questions(self):
        questions = json.loads(Path(FIXTURE).read_text(encoding="utf-8"))["questions"]
        self.assertEqual(40, len(questions))
        self.assertEqual(len(questions), len({q["id"] for q in questions}))
        for q in questions:
            self.assertTrue({"id", "question", "language", "expected_tools_any", "expected_facts"} <= set(q))


if __name__ == "__main__":
    unittest.main()
