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

    def test_parser_supports_all_transcript_scope(self) -> None:
        args = run_evaluation_questions.build_parser().parse_args(
            ["--transcript-scope", "all"]
        )

        self.assertEqual(args.transcript_scope, "all")

    def test_format_error_keeps_exception_summary_compact(self) -> None:
        message = run_evaluation_questions.format_error(
            "structured",
            TimeoutError("the read operation timed out"),
        )

        self.assertEqual(
            message,
            "structured: TimeoutError: the read operation timed out",
        )

    def test_has_successful_answer_requires_non_error_text(self) -> None:
        self.assertTrue(run_evaluation_questions.has_successful_answer("answer"))
        self.assertFalse(run_evaluation_questions.has_successful_answer(""))
        self.assertFalse(run_evaluation_questions.has_successful_answer("ERROR: timeout"))


if __name__ == "__main__":
    unittest.main()
