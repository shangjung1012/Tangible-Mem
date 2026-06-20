from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

import evaluate_retrieval  # noqa: E402
import retrieval_profiles  # noqa: E402


class RetrievalEvalTests(unittest.TestCase):
    def test_score_counts_acceptable_obj_ids_separately_from_strict_gold(self) -> None:
        row = {
            "query": "memory retrieval",
            "strict_gold_obj_ids": ["L1-strict"],
            "acceptable_obj_ids": ["L1-acceptable"],
            "expected_l2_ids": ["L2-memory-retrieval"],
            "expected_l3_ids": [],
        }
        scored = evaluate_retrieval._score_query_result(
            row,
            {
                "global_topic_map": {},
                "long_term_l1": [{"obj_id": "L1-acceptable"}],
                "long_term_l2": [{"l2_id": "L2-memory-retrieval"}],
                "long_term_l3": [],
                "retrieval_debug": {},
            },
        )

        self.assertEqual(scored["expected_obj_recall_at_context"], 1.0)
        self.assertEqual(scored["strict_obj_recall_at_context"], 0.0)
        self.assertEqual(scored["acceptable_obj_recall_at_context"], 1.0)

    def test_score_counts_expected_obj_ids_in_l2_timeline_context(self) -> None:
        scored = evaluate_retrieval._score_query_result(
            {"query": "topic evolution", "expected_obj_ids": ["L1-timeline"]},
            {
                "global_topic_map": {},
                "long_term_l1": [{"obj_id": "L1-seed"}],
                "long_term_l2": [
                    {
                        "l2_id": "L2-topic",
                        "timeline_digest": [{"obj_id": "L1-timeline"}],
                    }
                ],
                "long_term_l3": [],
                "retrieval_debug": {},
            },
        )

        self.assertEqual(scored["expected_obj_recall_at_context"], 1.0)

    def test_no_llm_mode_uses_heuristic_plan_without_planner_call(self) -> None:
        with patch.object(evaluate_retrieval, "plan_recall", side_effect=AssertionError("planner called")), patch.object(
            evaluate_retrieval,
            "recall",
            return_value={"long_term_l1": [], "long_term_l2": [], "long_term_l3": [], "retrieval_debug": {}},
        ) as recall_call:
            evaluate_retrieval.run_retrieval_once(
                query="memory retrieval",
                tree={"meetings": []},
                api_key="",
                model_name="test-model",
                params={"top_k_raw": 10},
                use_llm_planner=False,
                retrieval_mode="lexical",
            )

        _, kwargs = recall_call.call_args
        self.assertEqual(kwargs["plan"]["search_targets"], ["long_term_l1", "long_term_l2", "long_term_l3"])
        self.assertEqual(kwargs["retrieval_mode"], "lexical")

    def test_llm_mode_can_use_separate_planner_model(self) -> None:
        with patch.object(
            evaluate_retrieval,
            "plan_recall",
            return_value={
                "complexity": "simple",
                "search_targets": ["long_term_l1"],
                "keywords": ["memory"],
            },
        ) as planner, patch.object(
            evaluate_retrieval,
            "recall",
            return_value={"long_term_l1": [], "long_term_l2": [], "long_term_l3": [], "retrieval_debug": {}},
        ) as recall_call:
            evaluate_retrieval.run_retrieval_once(
                query="memory retrieval",
                tree={"meetings": []},
                api_key="test-key",
                model_name="answer-model",
                planner_model_name="planner-model",
                params={"top_k_raw": 10},
                use_llm_planner=True,
                retrieval_mode="lexical",
            )

        self.assertEqual(planner.call_args.kwargs["model_name"], "planner-model")
        self.assertEqual(recall_call.call_args.kwargs["model_name"], "answer-model")

    def test_eval_script_writes_json_and_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.jsonl"
            out = root / "eval"
            queries.write_text(
                json.dumps(
                    {
                        "query": "long-term memory retrieval 現在是怎麼運作的？",
                        "expected_obj_ids": ["L1-a"],
                        "expected_l2_ids": ["L2-memory-retrieval"],
                        "expected_l3_ids": ["L3-memory-retrieval"],
                        "notes": "smoke",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(
                evaluate_retrieval,
                "run_retrieval_once",
                return_value={
                    "global_topic_map": {},
                    "long_term_l1": [{"obj_id": "L1-a"}],
                    "long_term_l2": [{"l2_id": "L2-memory-retrieval"}],
                    "long_term_l3": [{"l3_id": "L3-memory-retrieval"}],
                    "retrieval_debug": {
                        "context_char_count": 900,
                        "selected_l1_count": 1,
                        "selected_l2_count": 1,
                        "selected_child_l2_count": 0,
                        "omitted_event_count": 0,
                        "large_l2_expanded_without_child_split": False,
                    },
                },
            ):
                report = evaluate_retrieval.evaluate_retrieval_grid(
                    queries_path=queries,
                    out=out,
                    api_key="test-key",
                    model_name="test-model",
                    grid={
                        "top_k_raw": [10],
                        "max_events_per_l2": [3],
                        "max_expanded_l2_topics": [1],
                        "max_global_topic_map_chars": [400],
                        "topic_size_penalty": [0.05],
                        "prefer_materialized_l3": [True],
                    },
                )

            self.assertEqual(report["query_count"], 1)
            self.assertEqual(report["runs"][0]["expected_obj_recall_at_context"], 1.0)
            self.assertTrue((out / "retrieval_eval_report.json").exists())
            self.assertTrue((out / "retrieval_eval_report.md").exists())

    def test_prompt_budget_allows_twelve_thousand_runtime_chars(self) -> None:
        with patch.object(evaluate_retrieval, "format_recall_for_prompt", return_value="x" * 11000):
            scored = evaluate_retrieval._score_query_result(
                {"query": "memory retrieval", "expected_obj_ids": ["L1-a"]},
                {
                    "global_topic_map": {},
                    "long_term_l1": [{"obj_id": "L1-a"}],
                    "long_term_l2": [],
                    "long_term_l3": [],
                    "retrieval_debug": {},
                },
            )

        self.assertTrue(scored["prompt_budget_pass"])

    def test_eval_cli_defaults_to_no_llm_planner(self) -> None:
        with patch.object(
            evaluate_retrieval,
            "evaluate_retrieval_grid",
            return_value={"query_count": 0, "run_count": 0},
        ) as runner:
            evaluate_retrieval.main([])

        self.assertFalse(runner.call_args.kwargs["use_llm_planner"])
        self.assertEqual(runner.call_args.kwargs["retrieval_mode"], "hybrid")

    def test_eval_cli_can_opt_into_llm_planner(self) -> None:
        with patch.object(
            evaluate_retrieval,
            "evaluate_retrieval_grid",
            return_value={"query_count": 0, "run_count": 0},
        ) as runner:
            evaluate_retrieval.main(["--use-llm-planner"])

        self.assertTrue(runner.call_args.kwargs["use_llm_planner"])

    def test_large_corpus_tight_profile_is_named_and_compact(self) -> None:
        profile = retrieval_profiles.get_retrieval_budget_profile("large_corpus_tight")

        self.assertEqual(profile["top_k_raw"], 20)
        self.assertEqual(profile["max_l1_seeds_for_prompt"], 8)
        self.assertEqual(profile["max_expanded_l2_topics"], 1)
        self.assertEqual(profile["max_events_per_l2"], 1)
        self.assertEqual(profile["max_events_per_child_l2"], 1)
        self.assertLessEqual(profile["max_global_topic_map_chars"], 300)
        self.assertLessEqual(profile["max_event_chars"], 100)

    def test_eval_best_profile_uses_hybrid_balanced_seed_budget(self) -> None:
        profile = retrieval_profiles.get_retrieval_budget_profile("eval_best")

        self.assertEqual(profile["top_k_raw"], 30)
        self.assertEqual(profile["max_l1_seeds_for_prompt"], 12)
        self.assertEqual(profile["max_expanded_l2_topics"], 1)
        self.assertEqual(profile["max_events_per_child_l2"], 2)
        self.assertLessEqual(profile["max_global_topic_map_chars"], 300)
        self.assertLessEqual(profile["max_event_chars"], 100)

    def test_deep_layered_profile_keeps_more_l1_and_timeline_coverage(self) -> None:
        profile = retrieval_profiles.get_retrieval_budget_profile("deep_layered")

        self.assertGreaterEqual(profile["max_l1_seeds_for_prompt"], 32)
        self.assertGreaterEqual(profile["max_events_per_child_l2"], 20)
        self.assertGreaterEqual(profile["max_relevant_l2_summaries"], 5)

    def test_generous_layered_profile_relaxes_eval_best_without_becoming_deep(self) -> None:
        profile = retrieval_profiles.get_retrieval_budget_profile("generous_layered")

        self.assertGreater(profile["top_k_raw"], 30)
        self.assertGreaterEqual(profile["max_l1_seeds_for_prompt"], 20)
        self.assertGreaterEqual(profile["max_global_topic_map_chars"], 600)
        self.assertGreaterEqual(profile["max_relevant_l2_summaries"], 2)
        self.assertGreaterEqual(profile["max_expanded_l2_topics"], 2)
        self.assertGreaterEqual(profile["max_events_per_l2"], 4)
        self.assertGreaterEqual(profile["max_events_per_child_l2"], 6)
        self.assertGreaterEqual(profile["max_event_chars"], 220)
        self.assertLess(profile["max_l1_seeds_for_prompt"], 32)
        self.assertLess(profile["max_events_per_child_l2"], 20)

    def test_observatory_trace_profile_keeps_tight_topic_count_but_readable_events(self) -> None:
        profile = retrieval_profiles.get_retrieval_budget_profile("observatory_trace")

        self.assertEqual(profile["max_l1_seeds_for_prompt"], 8)
        self.assertEqual(profile["max_expanded_l2_topics"], 1)
        self.assertEqual(profile["max_events_per_child_l2"], 1)
        self.assertGreaterEqual(profile["max_event_chars"], 220)
        self.assertLess(profile["max_event_chars"], 300)

    def test_observatory_paper_trace_profile_expands_context_without_becoming_deep(self) -> None:
        profile = retrieval_profiles.get_retrieval_budget_profile("observatory_paper_trace")

        self.assertGreaterEqual(profile["top_k_raw"], 80)
        self.assertGreaterEqual(profile["max_l1_seeds_for_prompt"], 16)
        self.assertGreaterEqual(profile["max_global_topic_map_chars"], 800)
        self.assertGreaterEqual(profile["max_relevant_l2_summaries"], 3)
        self.assertGreaterEqual(profile["max_expanded_l2_topics"], 2)
        self.assertGreaterEqual(profile["max_events_per_l2"], 4)
        self.assertGreaterEqual(profile["max_events_per_child_l2"], 4)
        self.assertLess(profile["max_l1_seeds_for_prompt"], 32)
        self.assertLess(profile["max_events_per_child_l2"], 20)

    def test_eval_cli_budget_profile_overrides_grid_with_single_run(self) -> None:
        with patch.object(
            evaluate_retrieval,
            "evaluate_retrieval_grid",
            return_value={"query_count": 0, "run_count": 0},
        ) as runner:
            evaluate_retrieval.main(["--budget-profile", "large_corpus_tight"])

        grid = runner.call_args.kwargs["grid"]
        self.assertEqual(grid["top_k_raw"], [20])
        self.assertEqual(grid["max_l1_seeds_for_prompt"], [8])
        self.assertEqual(grid["max_expanded_l2_topics"], [1])
        self.assertEqual(grid["max_events_per_child_l2"], [1])

    def test_eval_can_pass_sidecar_l2_l3_roots_to_recall(self) -> None:
        with patch.object(
            evaluate_retrieval,
            "plan_recall",
            side_effect=AssertionError("planner called"),
        ), patch.object(
            evaluate_retrieval,
            "recall",
            return_value={"long_term_l1": [], "long_term_l2": [], "long_term_l3": [], "retrieval_debug": {}},
        ) as recall_call:
            evaluate_retrieval.run_retrieval_once(
                query="memory retrieval",
                tree={"meetings": []},
                api_key="",
                model_name="test-model",
                params={"top_k_raw": 10},
                use_llm_planner=False,
                retrieval_mode="lexical",
                l2_root=Path("synthetic/l2"),
                l3_root=Path("synthetic/l3"),
            )

        _, kwargs = recall_call.call_args
        self.assertEqual(kwargs["l2_index_path"], Path("synthetic/l2/l2_index.json"))
        self.assertEqual(kwargs["l2_view_path"], Path("synthetic/l2/l2_view.json"))
        self.assertEqual(kwargs["l3_view_path"], Path("synthetic/l3/l3_view.json"))
        self.assertEqual(kwargs["l3_index_path"], Path("synthetic/l3/l3_index.json"))


if __name__ == "__main__":
    unittest.main()
