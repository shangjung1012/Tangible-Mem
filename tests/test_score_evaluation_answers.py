from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import score_evaluation_answers  # noqa: E402


class ScoreEvaluationAnswersTests(unittest.TestCase):
    def test_selects_prompt_variant_from_category(self) -> None:
        self.assertEqual(
            score_evaluation_answers.select_judge_variant({"category": "topic_synthesis"}),
            "temporal_evolution",
        )
        self.assertEqual(
            score_evaluation_answers.select_judge_variant({"category": "cross_meeting_recall"}),
            "temporal_evolution",
        )
        self.assertEqual(
            score_evaluation_answers.select_judge_variant({"category": "decision_reasoning"}),
            "decision_update",
        )
        self.assertEqual(
            score_evaluation_answers.select_judge_variant({"category": "conflict_or_update"}),
            "decision_update",
        )
        self.assertEqual(
            score_evaluation_answers.select_judge_variant({"category": "recent_context"}),
            "three_layer",
        )

    def test_build_judge_prompt_contains_variant_specific_fields(self) -> None:
        row = {
            "category": "decision_reasoning",
            "question": "Why did the decision change?",
            "expected_answer": "A was replaced by B.",
        }

        prompt = score_evaluation_answers.build_judge_prompt(row, "model says B")

        self.assertIn("最新優先", prompt)
        self.assertIn('"is_latest_info_captured"', prompt)
        self.assertIn("A was replaced by B.", prompt)
        self.assertIn("model says B", prompt)

    def test_parse_judge_json_accepts_code_fence(self) -> None:
        parsed = score_evaluation_answers.parse_judge_json(
            '```json\n{"final_judgment":"Yes","factuality_score":4}\n```'
        )

        self.assertEqual(parsed["final_judgment"], "Yes")
        self.assertEqual(parsed["factuality_score"], 4)

    def test_flatten_score_fields_maps_variant_outputs(self) -> None:
        row: dict[str, str] = {}
        score_evaluation_answers.write_score_fields(
            row,
            "structured_answer",
            "decision_update",
            {
                "is_latest_info_captured": "Yes",
                "knowledge_update_score": 5,
                "reasoning": "Captured latest decision.",
            },
            {"actual_input_tokens": 100, "actual_output_tokens": 20, "actual_total_tokens": 120},
        )

        self.assertEqual(row["structured_answer_judge_variant"], "decision_update")
        self.assertEqual(row["structured_answer_is_latest_info_captured"], "Yes")
        self.assertEqual(row["structured_answer_knowledge_update_score"], "5")
        self.assertEqual(row["structured_answer_judge_reasoning"], "Captured latest decision.")
        self.assertEqual(row["structured_answer_judge_total_tokens"], "120")

    def test_targets_include_answer_and_evidence_outputs(self) -> None:
        targets = score_evaluation_answers.parse_targets("")

        self.assertIn(("structured_answer", "agent_answer"), targets)
        self.assertIn(("structured_evidence", "structured_evidence_answer"), targets)
        self.assertIn(("rag_answer", "baseline_rag_answer"), targets)
        self.assertIn(("transcript_evidence", "transcript_evidence_answer"), targets)


if __name__ == "__main__":
    unittest.main()
