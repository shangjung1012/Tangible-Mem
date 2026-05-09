from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import run_evaluation_questions  # noqa: E402


class RunEvaluationQuestionsTests(unittest.TestCase):
    def test_extract_route_and_l1_ids_from_context(self) -> None:
        context = """
=== Memory Router ===
strategy: long_term_only

matched L1: L1-0506-001, L1-0429-013
source L1: L1-0506-001
"""

        self.assertEqual(
            run_evaluation_questions.extract_actual_route(context),
            "long_term_only",
        )
        self.assertEqual(
            run_evaluation_questions.extract_l1_ids(context),
            "L1-0429-013, L1-0506-001",
        )

    def test_select_rows_by_ids_and_limit(self) -> None:
        rows = [
            {"question_id": "VM-E01"},
            {"question_id": "VM-E02"},
            {"question_id": "VM-E03"},
        ]

        selected = run_evaluation_questions.select_rows(
            rows,
            ids={"VM-E02", "VM-E03"},
            limit=1,
        )

        self.assertEqual(selected, [{"question_id": "VM-E02"}])

    def test_parse_methods_defaults_and_rejects_unknown(self) -> None:
        self.assertEqual(
            run_evaluation_questions.parse_methods(""),
            {"structured", "rag", "transcript"},
        )
        self.assertEqual(
            run_evaluation_questions.parse_methods("structured,rag"),
            {"structured", "rag"},
        )
        with self.assertRaises(ValueError):
            run_evaluation_questions.parse_methods("structured,magic")


if __name__ == "__main__":
    unittest.main()
