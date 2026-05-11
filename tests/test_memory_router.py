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

    def test_long_term_context_defaults_to_no_llm_hybrid_retrieval(self) -> None:
        with patch.object(
            memory_context,
            "load_json_object",
            return_value={"meetings": []},
        ), patch.object(
            memory_context,
            "plan_recall",
            side_effect=AssertionError("planner should not be called by default"),
        ), patch.object(
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
        self.assertEqual(recall_call.call_args.kwargs["model_name"], "answer-model")
        self.assertEqual(recall_call.call_args.kwargs["retrieval_mode"], "hybrid")
        self.assertEqual(
            recall_call.call_args.kwargs["plan"]["search_targets"],
            ["long_term_l1", "long_term_l2", "long_term_l3"],
        )

    def test_long_term_context_uses_generous_runtime_budget_and_previews(self) -> None:
        with patch.object(
            memory_context,
            "load_json_object",
            return_value={"meetings": []},
        ), patch.object(
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
        ) as formatter_call:
            memory_context.retrieve_long_term_context(
                query="memory retrieval",
                api_key="test-key",
                model_name="answer-model",
            )

        kwargs = recall_call.call_args.kwargs
        self.assertEqual(kwargs["top_k_raw"], 60)
        self.assertEqual(kwargs["max_l1_seeds_for_prompt"], 24)
        self.assertEqual(kwargs["max_global_topic_map_chars"], 600)
        self.assertEqual(kwargs["max_relevant_l2_summaries"], 2)
        self.assertEqual(kwargs["max_expanded_l2_topics"], 2)
        self.assertEqual(kwargs["max_events_per_l2"], 4)
        self.assertEqual(kwargs["max_events_per_child_l2"], 8)
        self.assertEqual(kwargs["max_event_chars"], 220)
        self.assertEqual(formatter_call.call_args.kwargs["l1_content_chars"], 220)
        self.assertEqual(formatter_call.call_args.kwargs["l1_evidence_chars"], 320)

    def test_current_state_query_adds_current_implementation_context(self) -> None:
        with patch.object(
            memory_context,
            "load_json_object",
            return_value={"meetings": []},
        ), patch.object(
            memory_context,
            "recall",
            return_value={
                "global_topic_map": {},
                "long_term_l1": [],
                "long_term_l2": [],
                "long_term_l3": [],
            },
        ), patch.object(
            memory_context,
            "format_recall_for_prompt",
            return_value="=== L1 Evidence Seeds ===\nhistorical meeting evidence",
        ):
            context = memory_context.retrieve_long_term_context(
                query="L1 到 L2 的分群現在是怎麼決定的？",
                api_key="test-key",
                model_name="answer-model",
            )

        self.assertIn("=== Current Implementation State ===", context)
        self.assertIn("topic-based", context)
        self.assertIn("share_mem/tree.json", context)
        self.assertIn("long_term/l2/l2_view.json", context)
        self.assertIn("L3 promotion", context)
        self.assertLess(
            context.index("=== Current Implementation State ==="),
            context.index("=== L1 Evidence Seeds ==="),
        )

    def test_historical_query_does_not_add_current_implementation_context(self) -> None:
        with patch.object(
            memory_context,
            "load_json_object",
            return_value={"meetings": []},
        ), patch.object(
            memory_context,
            "recall",
            return_value={
                "global_topic_map": {},
                "long_term_l1": [],
                "long_term_l2": [],
                "long_term_l3": [],
            },
        ), patch.object(
            memory_context,
            "format_recall_for_prompt",
            return_value="=== L1 Evidence Seeds ===\nhistorical meeting evidence",
        ):
            context = memory_context.retrieve_long_term_context(
                query="我們之前為什麼要把 transcript 拆成 segment / idea units？",
                api_key="test-key",
                model_name="answer-model",
            )

        self.assertNotIn("=== Current Implementation State ===", context)

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

    def test_unified_context_default_budget_allows_twelve_thousand_chars(self) -> None:
        with patch.object(
            memory_context,
            "plan_memory_retrieval",
            return_value={
                "targets": ["long_term"],
                "strategy": "long_term_only",
                "reason": "historical rationale",
                "confidence": 0.85,
            },
        ), patch.object(
            memory_context,
            "retrieve_long_term_context",
            return_value="long context " * 800,
        ):
            context = memory_context.retrieve_memory_context(
                query="manager-agent 架構怎麼演變？",
                api_key="test-key",
                model_name="test-model",
            )

        self.assertGreater(len(context), 8000)
        self.assertLess(len(context), 12000)
        self.assertNotIn("...(truncated)", context)

    def test_unified_context_gives_long_term_more_room_when_short_term_is_present(self) -> None:
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
            return_value="short context",
        ) as short_call, patch.object(
            memory_context,
            "retrieve_long_term_context",
            return_value="long context",
        ) as long_call:
            memory_context.retrieve_memory_context(
                query="recent status and long-term rationale",
                api_key="test-key",
                model_name="test-model",
            )

        self.assertGreaterEqual(short_call.call_args.kwargs["max_context_chars"], 2400)
        self.assertGreaterEqual(long_call.call_args.kwargs["max_context_chars"], 9000)

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
