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


if __name__ == "__main__":
    unittest.main()
