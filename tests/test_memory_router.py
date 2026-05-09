from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
for path in (REPO_ROOT, APP_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import memory_context  # noqa: E402
from memory_router import plan_memory_retrieval  # noqa: E402


class MemoryRouterTests(unittest.TestCase):
    def test_recent_status_query_routes_short_term_and_long_term(self) -> None:
        plan = plan_memory_retrieval("目前 action items 是什麼？")

        self.assertEqual(plan["targets"], ["short_term", "long_term"])
        self.assertEqual(plan["strategy"], "both")
        self.assertGreaterEqual(plan["confidence"], 0.7)

    def test_history_rationale_query_routes_long_term_only(self) -> None:
        plan = plan_memory_retrieval("我們之前為什麼改成 L1 先命中再展開 L2？")

        self.assertEqual(plan["targets"], ["long_term"])
        self.assertEqual(plan["strategy"], "long_term_only")
        self.assertGreaterEqual(plan["confidence"], 0.7)

    def test_l3_promotion_query_routes_long_term_only(self) -> None:
        plan = plan_memory_retrieval("L3 promotion 是怎麼從過大的 L2 產生 child L2 的？")

        self.assertEqual(plan["targets"], ["long_term"])
        self.assertEqual(plan["strategy"], "long_term_only")
        self.assertGreaterEqual(plan["confidence"], 0.7)

    def test_manager_agent_evolution_query_routes_long_term(self) -> None:
        plan = plan_memory_retrieval("manager-agent 架構怎麼演變？")

        self.assertIn("long_term", plan["targets"])
        self.assertNotIn("short_term", plan["targets"])

    def test_non_meeting_greeting_routes_none(self) -> None:
        plan = plan_memory_retrieval("早安，謝謝")

        self.assertEqual(plan["targets"], [])
        self.assertEqual(plan["strategy"], "none")

    def test_recent_plus_history_query_routes_both(self) -> None:
        plan = plan_memory_retrieval("目前最新進度是什麼，跟之前的設計演進有什麼差異？")

        self.assertEqual(plan["targets"], ["short_term", "long_term"])
        self.assertEqual(plan["strategy"], "both")

    def test_unified_context_uses_router_and_handles_missing_short_term_module(self) -> None:
        with patch.object(
            memory_context,
            "plan_memory_retrieval",
            return_value={
                "targets": ["short_term"],
                "strategy": "short_term_only",
                "reason": "recent status query",
                "confidence": 0.9,
            },
        ):
            context = memory_context.retrieve_memory_context(
                query="目前最新待辦是什麼？",
                api_key="test-key",
                model_name="test-model",
            )

        self.assertIn("=== Memory Router ===", context)
        self.assertIn("strategy: short_term_only", context)
        self.assertIn("=== Short-Term Memory ===", context)
        self.assertIn("短期記憶", context)

    def test_unified_context_can_retrieve_both_targets(self) -> None:
        with patch.object(
            memory_context,
            "plan_memory_retrieval",
            return_value={
                "targets": ["short_term", "long_term"],
                "strategy": "both",
                "reason": "recent status plus historical rationale",
                "confidence": 0.85,
            },
        ), patch.object(
            memory_context,
            "retrieve_short_term_context_adapter",
            return_value="recent status context",
        ), patch.object(
            memory_context,
            "retrieve_long_term_context",
            return_value="historical long-term context",
        ):
            context = memory_context.retrieve_memory_context(
                query="目前進度和歷史原因？",
                api_key="test-key",
                model_name="test-model",
            )

        self.assertIn("=== Short-Term Memory ===", context)
        self.assertIn("recent status context", context)
        self.assertIn("=== Long-Term Memory ===", context)
        self.assertIn("historical long-term context", context)

    def test_long_term_context_uses_planner_model_separately_from_answer_model(self) -> None:
        with patch.object(
            memory_context,
            "load_json_object",
            return_value={"meetings": []},
        ), patch.object(
            memory_context,
            "plan_recall",
            return_value={
                "complexity": "simple",
                "search_targets": ["long_term_l1"],
                "keywords": ["memory"],
            },
        ) as planner, patch.object(
            memory_context,
            "recall",
            return_value={
                "global_topic_map": {},
                "long_term_l1": [],
                "long_term_l2": [],
                "long_term_l3": [],
            },
        ) as recall_call, patch.object(
            memory_context,
            "format_recall_for_prompt",
            return_value="formatted context",
        ):
            context = memory_context.retrieve_long_term_context(
                query="memory retrieval",
                api_key="test-key",
                model_name="answer-model",
                planner_model_name="planner-model",
            )

        self.assertEqual(context, "formatted context")
        self.assertEqual(planner.call_args.kwargs["model_name"], "planner-model")
        self.assertEqual(recall_call.call_args.kwargs["model_name"], "answer-model")

    def test_unified_context_preserves_both_sections_when_truncated(self) -> None:
        with patch.object(
            memory_context,
            "plan_memory_retrieval",
            return_value={
                "targets": ["short_term", "long_term"],
                "strategy": "both",
                "reason": "recent status plus historical rationale",
                "confidence": 0.85,
            },
        ), patch.object(
            memory_context,
            "retrieve_short_term_context_adapter",
            return_value="short context " * 120,
        ), patch.object(
            memory_context,
            "retrieve_long_term_context",
            return_value="long context " * 120,
        ):
            context = memory_context.retrieve_memory_context(
                query="目前進度和歷史原因？",
                api_key="test-key",
                model_name="test-model",
                max_context_chars=1200,
            )

        self.assertIn("=== Short-Term Memory ===", context)
        self.assertIn("short context", context)
        self.assertIn("=== Long-Term Memory ===", context)
        self.assertIn("long context", context)

    def test_short_term_adapter_uses_retrieval_module(self) -> None:
        context = memory_context.retrieve_short_term_context_adapter(
            query="目前 memory retrieval 的最新狀態是什麼？",
            api_key="test-key",
        )

        self.assertIn("=== Short-Term Memory Retrieval ===", context)
        self.assertIn("last_updated_meeting_id", context)
        self.assertIn("source L1:", context)


if __name__ == "__main__":
    unittest.main()
