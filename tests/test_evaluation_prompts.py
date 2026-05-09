from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
LONG_TERM_DIR = REPO_ROOT / "long_term"
for path in (APP_DIR, LONG_TERM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import baseline_retrieval  # noqa: E402
import retrieve_once  # noqa: E402
from evaluation_prompts import EVALUATION_SYSTEM_PROMPT, build_evaluation_answer_prompt  # noqa: E402
from recall_planner import _build_planner_prompt  # noqa: E402


class EvaluationPromptTests(unittest.TestCase):
    def test_evaluation_system_prompt_disallows_outside_context_and_tool_assumptions(self) -> None:
        self.assertIn("只能根據提供的 context", EVALUATION_SYSTEM_PROMPT)
        self.assertIn("不可使用外部知識", EVALUATION_SYSTEM_PROMPT)
        self.assertNotIn("工具", EVALUATION_SYSTEM_PROMPT)

    def test_structured_and_baseline_answers_share_prompt_builder(self) -> None:
        structured_prompt = retrieve_once.build_answer_prompt(
            query="L3 promotion 怎麼運作？",
            memory_context="matched L1: L1-0506-001",
        )
        baseline_prompt = build_evaluation_answer_prompt(
            query="L3 promotion 怎麼運作？",
            context="raw transcript chunk",
            context_source="baseline: plain raw transcript RAG",
        )

        for phrase in (
            "只能根據 context 作答",
            "不可使用 context 以外的會議資訊",
            "如果 context 不足以回答",
            "不要假裝它有 L2/L3 結構",
        ):
            self.assertIn(phrase, structured_prompt)
            self.assertIn(phrase, baseline_prompt)
        self.assertIn("structured memory context", structured_prompt)
        self.assertIn("baseline: plain raw transcript RAG", baseline_prompt)

    def test_baseline_module_uses_shared_prompt_builder(self) -> None:
        prompt = build_evaluation_answer_prompt(
            query="問題",
            context="baseline context",
            context_source="baseline: oracle full transcript",
        )

        self.assertIn("baseline: oracle full transcript", prompt)
        self.assertFalse(hasattr(baseline_retrieval, "BASELINE_ANSWER_PROMPT"))

    def test_recall_planner_prompt_uses_active_l1_l2_l3_definitions(self) -> None:
        prompt = _build_planner_prompt("L3 promotion 怎麼運作？")

        self.assertIn("L1 evidence", prompt)
        self.assertIn("L2 topic", prompt)
        self.assertIn("L3 promotion", prompt)
        self.assertIn("immutable memory objects", prompt)
        self.assertNotIn("月度 / 衝刺期摘要", prompt)
        self.assertNotIn("研究計畫輪廓", prompt)


if __name__ == "__main__":
    unittest.main()
