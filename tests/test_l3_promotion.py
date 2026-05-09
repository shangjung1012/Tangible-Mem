from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

from l3_promotion import (  # noqa: E402
    DEFAULT_L3_PROMOTION_THRESHOLDS,
    build_child_assignment_prompt,
    build_child_taxonomy_prompt,
    build_l3_materialization_sidecar,
    build_l3_promotion_sidecar,
    build_l3_promotion_record,
    l2_promotion_metrics,
    should_promote_l2,
)


def _l2_node(linked_count: int, meeting_count: int = 3) -> dict:
    return {
        "l2_id": "L2-crowded-topic",
        "label": "crowded topic",
        "current_state": "Crowded topic state.",
        "linked_obj_ids": [f"L1-0307-{i:03d}" for i in range(linked_count)],
        "timeline_digest": [
            {
                "meeting_id": "0307",
                "meeting_date": "2026-03-07",
                "obj_id": f"L1-0307-{i:03d}",
                "summary": f"summary {i}",
            }
            for i in range(linked_count)
        ],
        "meeting_ids": [f"M{i:02d}" for i in range(meeting_count)],
    }


class L3PromotionTests(unittest.TestCase):
    def test_large_l2_is_promotion_candidate(self) -> None:
        node = _l2_node(DEFAULT_L3_PROMOTION_THRESHOLDS["absolute_l1_threshold"])

        decision = should_promote_l2(node, total_l1_count=500)

        self.assertTrue(decision["promote"])
        self.assertIn("too_many_l1_nodes", decision["reason_codes"])
        self.assertEqual(
            decision["metrics"]["linked_l1_count"],
            DEFAULT_L3_PROMOTION_THRESHOLDS["absolute_l1_threshold"],
        )

    def test_small_l2_is_not_promotion_candidate(self) -> None:
        node = _l2_node(8, meeting_count=2)

        decision = should_promote_l2(node, total_l1_count=40)

        self.assertFalse(decision["promote"])
        self.assertEqual(decision["reason_codes"], [])
        self.assertEqual(l2_promotion_metrics(node)["meeting_count"], 2)

    def test_dominant_share_promotes_when_absolute_count_is_below_hard_threshold(self) -> None:
        node = _l2_node(18, meeting_count=2)

        decision = should_promote_l2(node, total_l1_count=40)

        self.assertTrue(decision["promote"])
        self.assertIn("dominant_topic_share", decision["reason_codes"])
        self.assertEqual(decision["metrics"]["linked_l1_count"], 18)
        self.assertAlmostEqual(decision["metrics"]["l1_share"], 0.45)

    def test_share_does_not_promote_when_minimum_count_is_not_met(self) -> None:
        node = _l2_node(10, meeting_count=2)

        decision = should_promote_l2(node, total_l1_count=20)

        self.assertFalse(decision["promote"])
        self.assertEqual(decision["reason_codes"], [])

    def test_build_record_maps_old_l2_to_new_l3_and_child_l2s(self) -> None:
        node = _l2_node(80, meeting_count=5)
        child_l2s = [
            {
                "child_l2_id": "L2-crowded-topic-a",
                "label": "crowded topic a",
                "linked_obj_ids": ["L1-0307-001"],
                "split_reason": "first subtopic",
            },
            {
                "child_l2_id": "L2-crowded-topic-b",
                "label": "crowded topic b",
                "linked_obj_ids": ["L1-0307-002"],
                "split_reason": "second subtopic",
            },
        ]

        record = build_l3_promotion_record(
            node,
            child_l2_candidates=child_l2s,
            total_l1_count=120,
        )

        self.assertEqual(record["source_l2_id"], "L2-crowded-topic")
        self.assertEqual(record["proposed_l3_id"], "L3-crowded-topic")
        self.assertEqual(record["status"], "promotion_candidate")
        self.assertEqual(
            record["mapping"],
            {
                "old_l2_id": "L2-crowded-topic",
                "new_l3_id": "L3-crowded-topic",
                "new_child_l2_ids": ["L2-crowded-topic-a", "L2-crowded-topic-b"],
            },
        )

    def test_build_record_does_not_mutate_l2_node_or_raw_l1(self) -> None:
        node = _l2_node(80, meeting_count=5)
        raw_l1 = {"obj_id": "L1-0307-001", "evidence": {"text": "raw evidence"}}
        before_node = copy.deepcopy(node)
        before_l1 = copy.deepcopy(raw_l1)

        build_l3_promotion_record(
            node,
            child_l2_candidates=[
                {"child_l2_id": "L2-a", "label": "a", "linked_obj_ids": ["L1-0307-001"]},
                {"child_l2_id": "L2-b", "label": "b", "linked_obj_ids": ["L1-0307-002"]},
            ],
            total_l1_count=120,
        )

        self.assertEqual(node, before_node)
        self.assertEqual(raw_l1, before_l1)

    def test_build_sidecar_promotes_large_l2_with_child_candidates(self) -> None:
        large = _l2_node(80, meeting_count=6)
        large["l2_id"] = "L2-transcript-segmentation-and-idea-unit-coverage"
        large["label"] = "transcript segmentation and idea-unit coverage"
        small = _l2_node(8, meeting_count=2)
        l2_view = {"l2_nodes": [large, small]}

        sidecar = build_l3_promotion_sidecar(l2_view, total_l1_count=120)

        self.assertEqual(sidecar["schema_version"], 1)
        self.assertEqual(sidecar["promotion_count"], 1)
        record = sidecar["promotions"][0]
        self.assertEqual(
            record["source_l2_id"],
            "L2-transcript-segmentation-and-idea-unit-coverage",
        )
        self.assertEqual(record["proposed_l3_id"], "L3-transcript-segmentation-and-idea-unit-coverage")
        self.assertEqual(record["status"], "promotion_candidate")
        self.assertEqual(
            record["mapping"]["new_child_l2_ids"],
            [
                "L2-transcript-segmentation",
                "L2-idea-unit-extraction-and-coverage-repair",
                "L2-evidence-grounding-and-line-coverage",
            ],
        )

    def test_llm_taxonomy_proposal_can_supply_child_l2_candidates(self) -> None:
        node = _l2_node(30, meeting_count=4)

        def proposer(l2_node: dict) -> dict:
            self.assertEqual(l2_node["l2_id"], "L2-crowded-topic")
            return {
                "promoted_l3": {
                    "l3_id": "L3-crowded-topic",
                    "label": "crowded topic",
                },
                "child_l2_candidates": [
                    {
                        "child_l2_id": "L2-crowded-topic-method",
                        "label": "crowded topic method",
                        "split_reason": "method subtopic",
                        "assignment_criteria": ["method"],
                    },
                    {
                        "child_l2_id": "L2-crowded-topic-risk",
                        "label": "crowded topic risk",
                        "split_reason": "risk subtopic",
                        "assignment_criteria": ["risk"],
                    },
                ],
            }

        sidecar = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=100,
            child_taxonomy_proposer=proposer,
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        record = sidecar["promotions"][0]
        self.assertEqual(record["status"], "promotion_candidate")
        self.assertEqual(
            record["mapping"]["new_child_l2_ids"],
            ["L2-crowded-topic-method", "L2-crowded-topic-risk"],
        )
        self.assertEqual(record["llm_usage"]["used"], True)
        self.assertEqual(record["llm_usage"]["stage"], "child_taxonomy_proposal")
        self.assertEqual(sidecar["llm_usage"]["used"], True)

    def test_llm_taxonomy_proposal_only_fills_missing_child_candidates(self) -> None:
        known = _l2_node(30, meeting_count=4)
        known["l2_id"] = "L2-transcript-segmentation-and-idea-unit-coverage"
        known["label"] = "transcript segmentation and idea-unit coverage"
        unknown = _l2_node(30, meeting_count=4)
        unknown["l2_id"] = "L2-memory-evaluation-strategy"
        unknown["label"] = "memory evaluation strategy"
        calls: list[str] = []

        def proposer(l2_node: dict) -> dict:
            calls.append(l2_node["l2_id"])
            return {
                "promoted_l3": {
                    "l3_id": "L3-memory-evaluation-strategy",
                    "label": "memory evaluation strategy",
                },
                "child_l2_candidates": [
                    {
                        "child_l2_id": "L2-benchmark-and-dataset-evaluation",
                        "label": "benchmark and dataset evaluation",
                        "split_reason": "Evaluation datasets and benchmark setup.",
                        "assignment_criteria": ["benchmark", "dataset", "locomo", "memo"],
                    },
                    {
                        "child_l2_id": "L2-llm-as-judge-scoring",
                        "label": "LLM-as-judge scoring",
                        "split_reason": "Judge prompts, scoring, and metrics.",
                        "assignment_criteria": ["llm-as-judge", "scoring", "metric"],
                    },
                ],
            }

        sidecar = build_l3_promotion_sidecar(
            {"l2_nodes": [known, unknown]},
            total_l1_count=100,
            child_taxonomy_proposer=proposer,
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        self.assertEqual(calls, ["L2-memory-evaluation-strategy"])
        records = {record["source_l2_id"]: record for record in sidecar["promotions"]}
        self.assertEqual(records["L2-transcript-segmentation-and-idea-unit-coverage"]["llm_usage"]["used"], False)
        self.assertEqual(records["L2-memory-evaluation-strategy"]["status"], "promotion_candidate")
        self.assertEqual(
            records["L2-memory-evaluation-strategy"]["mapping"]["new_child_l2_ids"],
            ["L2-benchmark-and-dataset-evaluation", "L2-llm-as-judge-scoring"],
        )

    def test_llm_taxonomy_proposal_can_be_limited_to_specific_source_l2(self) -> None:
        memory_eval = _l2_node(30, meeting_count=4)
        memory_eval["l2_id"] = "L2-memory-evaluation-strategy"
        memory_eval["label"] = "memory evaluation strategy"
        retrieval = _l2_node(30, meeting_count=4)
        retrieval["l2_id"] = "L2-memory-retrieval"
        retrieval["label"] = "memory retrieval"
        calls: list[str] = []

        def proposer(l2_node: dict) -> dict:
            calls.append(l2_node["l2_id"])
            return {
                "promoted_l3": {
                    "l3_id": "L3-memory-evaluation-strategy",
                    "label": "memory evaluation strategy",
                },
                "child_l2_candidates": [
                    {
                        "child_l2_id": "L2-benchmark-and-dataset-evaluation",
                        "label": "benchmark and dataset evaluation",
                        "split_reason": "Benchmark setup.",
                        "assignment_criteria": ["benchmark"],
                    },
                    {
                        "child_l2_id": "L2-llm-as-judge-scoring",
                        "label": "LLM-as-judge scoring",
                        "split_reason": "Scoring setup.",
                        "assignment_criteria": ["scoring"],
                    },
                ],
            }

        sidecar = build_l3_promotion_sidecar(
            {"l2_nodes": [memory_eval, retrieval]},
            total_l1_count=100,
            child_taxonomy_proposer=proposer,
            llm_source_l2_ids={"L2-memory-evaluation-strategy"},
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        self.assertEqual(calls, ["L2-memory-evaluation-strategy"])
        records = {record["source_l2_id"]: record for record in sidecar["promotions"]}
        self.assertEqual(records["L2-memory-evaluation-strategy"]["status"], "promotion_candidate")
        self.assertEqual(records["L2-memory-retrieval"]["status"], "needs_split_review")
        self.assertEqual(records["L2-memory-retrieval"]["llm_usage"]["used"], False)

    def test_llm_supplied_child_taxonomy_materializes_unknown_large_l2(self) -> None:
        node = _l2_node(3, meeting_count=2)
        node["l2_id"] = "L2-memory-evaluation-strategy"
        node["label"] = "memory evaluation strategy"
        node["timeline_digest"] = [
            {
                "meeting_id": "0318",
                "meeting_date": "2026-03-18",
                "obj_id": "L1-a",
                "summary": "LOCOMO and MEMO benchmarks require multi-hop evaluation.",
            },
            {
                "meeting_id": "0429",
                "meeting_date": "2026-04-29",
                "obj_id": "L1-b",
                "summary": "LLM-as-judge scoring should rate retrieval answer quality.",
            },
            {
                "meeting_id": "0506",
                "meeting_date": "2026-05-06",
                "obj_id": "L1-c",
                "summary": "The demo experiment needs expected questions and scoring criteria.",
            },
        ]

        def proposer(l2_node: dict) -> dict:
            self.assertEqual([row["obj_id"] for row in l2_node["timeline_digest"]], ["L1-a", "L1-b", "L1-c"])
            return {
                "promoted_l3": {
                    "l3_id": "L3-memory-evaluation-strategy",
                    "label": "memory evaluation strategy",
                },
                "child_l2_candidates": [
                    {
                        "child_l2_id": "L2-benchmark-and-dataset-evaluation",
                        "label": "benchmark and dataset evaluation",
                        "split_reason": "Benchmark datasets and question sets.",
                        "assignment_criteria": ["benchmark", "locomo", "memo", "question"],
                    },
                    {
                        "child_l2_id": "L2-llm-as-judge-scoring",
                        "label": "LLM-as-judge scoring",
                        "split_reason": "Scoring, metrics, and judge behavior.",
                        "assignment_criteria": ["llm-as-judge", "scoring", "quality"],
                    },
                ],
            }

        promotions = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=10,
            thresholds={"absolute_l1_threshold": 3},
            child_taxonomy_proposer=proposer,
            generated_at_utc="2026-05-09T00:00:00Z",
        )
        materialized = build_l3_materialization_sidecar(
            {"l2_nodes": [node]},
            promotions,
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        self.assertEqual(promotions["promotions"][0]["status"], "promotion_candidate")
        self.assertEqual(materialized["materialized_l3_count"], 1)
        self.assertEqual(materialized["l3_nodes"][0]["promoted_from_l2_id"], "L2-memory-evaluation-strategy")
        self.assertEqual(set(materialized["l3_index"]), {"L1-a", "L1-b", "L1-c"})

    def test_llm_prompts_use_only_promoted_l2_compact_evidence(self) -> None:
        node = _l2_node(3, meeting_count=1)
        child_l2s = [
            {
                "child_l2_id": "L2-crowded-topic-method",
                "label": "crowded topic method",
                "assignment_criteria": ["method"],
            }
        ]

        taxonomy_prompt = build_child_taxonomy_prompt(node)
        assignment_prompt = build_child_assignment_prompt(node, child_l2s)

        self.assertIn("L2-crowded-topic", taxonomy_prompt)
        self.assertIn("L1-0307-000", taxonomy_prompt)
        self.assertIn("Do not modify raw L1 evidence", taxonomy_prompt)
        self.assertIn("L2-crowded-topic-method", assignment_prompt)
        self.assertIn("L1-0307-001", assignment_prompt)
        self.assertIn("Return exactly one assignment per listed L1", assignment_prompt)

    def test_materialization_assigns_every_old_l1_to_one_child_l2(self) -> None:
        node = {
            "l2_id": "L2-transcript-segmentation-and-idea-unit-coverage",
            "label": "transcript segmentation and idea-unit coverage",
            "current_state": "Crowded transcript processing topic.",
            "linked_obj_ids": ["L1-a", "L1-b", "L1-c", "L1-d"],
            "meeting_ids": ["0307", "0318"],
            "timeline_digest": [
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "obj_id": "L1-a",
                    "summary": "The team discussed transcript chunk boundaries and segmentation windows.",
                },
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "obj_id": "L1-b",
                    "summary": "Idea unit coverage repair should catch missed lines.",
                },
                {
                    "meeting_id": "0318",
                    "meeting_date": "2026-03-18",
                    "obj_id": "L1-c",
                    "summary": "Evidence grounding needs line ranges and support checks.",
                },
                {
                    "meeting_id": "0318",
                    "meeting_date": "2026-03-18",
                    "obj_id": "L1-d",
                    "summary": "A vague transcript processing point without a clear child keyword.",
                },
            ],
        }
        before = copy.deepcopy(node)
        promotions = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=80,
            thresholds={"absolute_l1_threshold": 4},
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        materialized = build_l3_materialization_sidecar(
            {"l2_nodes": [node]},
            promotions,
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        self.assertEqual(node, before)
        self.assertEqual(materialized["materialized_l3_count"], 1)
        l3_node = materialized["l3_nodes"][0]
        self.assertEqual(l3_node["l3_id"], "L3-transcript-segmentation-and-idea-unit-coverage")
        self.assertEqual(l3_node["coverage"]["source_l1_count"], 4)
        self.assertEqual(l3_node["coverage"]["assigned_l1_count"], 4)
        self.assertEqual(l3_node["coverage"]["unassigned_l1_count"], 0)
        assigned_ids = set(materialized["l3_index"])
        self.assertEqual(assigned_ids, {"L1-a", "L1-b", "L1-c", "L1-d"})
        self.assertEqual(
            materialized["l3_index"]["L1-a"]["child_l2_id"],
            "L2-transcript-segmentation",
        )
        self.assertEqual(
            materialized["l3_index"]["L1-b"]["child_l2_id"],
            "L2-idea-unit-extraction-and-coverage-repair",
        )
        self.assertEqual(
            materialized["l3_index"]["L1-c"]["child_l2_id"],
            "L2-evidence-grounding-and-line-coverage",
        )

    def test_llm_assignment_is_validated_and_falls_back_when_invalid(self) -> None:
        node = {
            "l2_id": "L2-transcript-segmentation-and-idea-unit-coverage",
            "label": "transcript segmentation and idea-unit coverage",
            "current_state": "Crowded transcript processing topic.",
            "linked_obj_ids": ["L1-a", "L1-b", "L1-c"],
            "meeting_ids": ["0307"],
            "timeline_digest": [
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "obj_id": "L1-a",
                    "summary": "The team discussed transcript segmentation windows.",
                },
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "obj_id": "L1-b",
                    "summary": "Idea unit coverage repair should catch missed lines.",
                },
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "obj_id": "L1-c",
                    "summary": "Evidence grounding needs line ranges.",
                },
            ],
        }
        promotions = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=80,
            thresholds={"absolute_l1_threshold": 3},
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        def assignment_proposer(l2_node: dict, child_l2_candidates: list[dict]) -> list[dict]:
            self.assertEqual(l2_node["l2_id"], node["l2_id"])
            self.assertEqual(len(child_l2_candidates), 3)
            return [
                {
                    "obj_id": "L1-a",
                    "child_l2_id": "L2-transcript-segmentation",
                    "confidence": 0.93,
                    "reason": "windowing and segmentation",
                },
                {
                    "obj_id": "L1-b",
                    "child_l2_id": "L2-made-up-child",
                    "confidence": 0.95,
                    "reason": "invalid child id should be rejected",
                },
                {
                    "obj_id": "L1-c",
                    "child_l2_id": "L2-evidence-grounding-and-line-coverage",
                    "confidence": 0.2,
                    "reason": "low confidence should be reviewed",
                },
            ]

        materialized = build_l3_materialization_sidecar(
            {"l2_nodes": [node]},
            promotions,
            assignment_proposer=assignment_proposer,
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        self.assertEqual(materialized["llm_usage"]["used"], True)
        self.assertEqual(materialized["llm_usage"]["stage"], "l1_child_l2_assignment")
        self.assertEqual(
            materialized["l3_index"]["L1-a"]["assignment_reason"],
            "llm_assignment",
        )
        self.assertEqual(
            materialized["l3_index"]["L1-b"]["assignment_reason"],
            "llm_invalid_assignment_fallback",
        )
        self.assertEqual(
            materialized["l3_index"]["L1-c"]["assignment_reason"],
            "llm_low_confidence_fallback",
        )
        self.assertEqual(materialized["l3_nodes"][0]["coverage"]["assigned_l1_count"], 3)
        self.assertEqual(materialized["l3_nodes"][0]["manual_review_count"], 2)


if __name__ == "__main__":
    unittest.main()
