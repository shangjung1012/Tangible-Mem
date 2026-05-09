from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import retrieve_once  # noqa: E402


class RetrieveOnceTests(unittest.TestCase):
    def test_read_question_from_argv_or_stdin(self) -> None:
        parser = retrieve_once.build_parser()

        args = parser.parse_args(["為什麼", "L2", "要升成", "L3？"])
        self.assertEqual(
            retrieve_once.read_question(args, stdin=io.StringIO("ignored")),
            "為什麼 L2 要升成 L3？",
        )

        args = parser.parse_args([])
        self.assertEqual(
            retrieve_once.read_question(args, stdin=io.StringIO("目前進度是什麼？\n")),
            "目前進度是什麼？",
        )

    def test_build_answer_prompt_includes_query_and_retrieved_context(self) -> None:
        prompt = retrieve_once.build_answer_prompt(
            query="L3 promotion 怎麼運作？",
            memory_context="=== Long-Term Memory ===\nL1 evidence -> L2 -> L3",
        )

        self.assertIn("L3 promotion 怎麼運作？", prompt)
        self.assertIn("=== Long-Term Memory ===", prompt)
        self.assertIn("不要編造", prompt)

    def test_context_only_runs_retrieval_without_generating_answer(self) -> None:
        with patch.object(retrieve_once, "resolve_api_keys", return_value=["fake-key"]), patch.object(
            retrieve_once,
            "retrieve_memory_context",
            return_value="retrieved context",
        ) as retrieve_mock, patch.object(
            retrieve_once,
            "generate_answer",
            side_effect=AssertionError("answer generation should not run"),
        ), patch(
            "sys.stdout",
            new_callable=io.StringIO,
        ) as stdout:
            exit_code = retrieve_once.run_once(["--context-only", "目前進度？"])

        self.assertEqual(exit_code, 0)
        retrieve_mock.assert_called_once()
        self.assertIn("retrieved context", stdout.getvalue())

    def test_sufficiency_gate_requires_real_memory_hits(self) -> None:
        self.assertFalse(retrieve_once.has_sufficient_memory_context(""))
        self.assertFalse(
            retrieve_once.has_sufficient_memory_context("（此問題不需要會議記憶檢索）")
        )
        self.assertFalse(retrieve_once.has_sufficient_memory_context("（無相關記憶）"))
        self.assertTrue(
            retrieve_once.has_sufficient_memory_context(
                "=== Long-Term Memory ===\nmatched L1: L1-0506-001"
            )
        )
        self.assertTrue(
            retrieve_once.has_sufficient_memory_context(
                "=== Short-Term Memory Retrieval ===\nsource L1: L1-0506-033"
            )
        )

    def test_no_memory_hit_returns_insufficient_answer_without_generating(self) -> None:
        with patch.object(retrieve_once, "resolve_api_keys", return_value=["fake-key"]), patch.object(
            retrieve_once,
            "retrieve_memory_context",
            return_value="（無相關記憶）",
        ), patch.object(
            retrieve_once,
            "generate_answer",
            side_effect=AssertionError("answer generation should not run"),
        ), patch(
            "sys.stdout",
            new_callable=io.StringIO,
        ) as stdout:
            exit_code = retrieve_once.run_once(["不存在的會議決策是什麼？"])

        self.assertEqual(exit_code, 0)
        self.assertIn(retrieve_once.INSUFFICIENT_MEMORY_ANSWER, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
