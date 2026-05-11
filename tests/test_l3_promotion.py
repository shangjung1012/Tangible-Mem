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
    build_l2_merge_review_sidecar,
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
                "L2-fixed-vs-dynamic-chunking",
                "L2-window-and-boundary-selection",
                "L2-tool-calling-transcript-reading",
                "L2-transcript-segmentation-strategy-and-validation",
                "L2-idea-unit-generation",
                "L2-idea-unit-granularity-and-semantics",
                "L2-idea-unit-generation-methods",
                "L2-idea-unit-candidate-classification",
                "L2-missing-line-coverage",
                "L2-repair-and-coarsening",
                "L2-cross-window-continuity",
                "L2-evidence-grounding-and-line-coverage",
            ],
        )

    def test_memory_evaluation_has_reviewed_deterministic_child_candidates(self) -> None:
        node = _l2_node(80, meeting_count=6)
        node["l2_id"] = "L2-memory-evaluation-strategy"
        node["label"] = "memory evaluation strategy"

        sidecar = build_l3_promotion_sidecar({"l2_nodes": [node]}, total_l1_count=120)

        record = sidecar["promotions"][0]
        self.assertEqual(record["source_l2_id"], "L2-memory-evaluation-strategy")
        self.assertEqual(record["status"], "promotion_candidate")
        self.assertEqual(
            record["mapping"]["new_child_l2_ids"],
            [
                "L2-overall-memory-system-evaluation",
                "L2-memory-mechanism-evaluation-metrics",
                "L2-evaluation-datasets-ground-truth",
            ],
        )
        self.assertEqual(record["llm_usage"]["used"], False)

    def test_retrieval_baseline_comparison_has_reviewed_child_candidates(self) -> None:
        node = _l2_node(80, meeting_count=6)
        node["l2_id"] = "L2-retrieval-baseline-comparison"
        node["label"] = "retrieval baseline comparison"

        sidecar = build_l3_promotion_sidecar({"l2_nodes": [node]}, total_l1_count=120)

        record = sidecar["promotions"][0]
        self.assertEqual(record["source_l2_id"], "L2-retrieval-baseline-comparison")
        self.assertEqual(record["status"], "promotion_candidate")
        self.assertEqual(
            record["mapping"]["new_child_l2_ids"],
            [
                "L2-full-context-baseline",
                "L2-traditional-rag-baseline",
                "L2-layered-memory-comparison",
                "L2-token-latency-and-cost",
                "L2-answer-quality-and-traceability",
            ],
        )
        self.assertEqual(record["llm_usage"]["used"], False)

    def test_memory_lifecycle_has_reviewed_child_candidates(self) -> None:
        node = _l2_node(80, meeting_count=6)
        node["l2_id"] = "L2-memory-lifecycle"
        node["label"] = "memory lifecycle"

        sidecar = build_l3_promotion_sidecar({"l2_nodes": [node]}, total_l1_count=120)

        record = sidecar["promotions"][0]
        self.assertEqual(record["source_l2_id"], "L2-memory-lifecycle")
        self.assertEqual(record["status"], "promotion_candidate")
        self.assertEqual(
            record["mapping"]["new_child_l2_ids"],
            [
                "L2-memory-retention-and-forgetting",
                "L2-importance-activation-and-recency",
                "L2-importance-feedback-and-editor",
                "L2-topic-lifecycle-and-evolution",
            ],
        )

    def test_memory_processing_architecture_has_reviewed_child_candidates(self) -> None:
        node = _l2_node(80, meeting_count=6)
        node["l2_id"] = "L2-memory-processing-architecture"
        node["label"] = "memory processing architecture"

        sidecar = build_l3_promotion_sidecar({"l2_nodes": [node]}, total_l1_count=120)

        record = sidecar["promotions"][0]
        self.assertEqual(record["source_l2_id"], "L2-memory-processing-architecture")
        self.assertEqual(record["status"], "promotion_candidate")
        self.assertEqual(
            record["mapping"]["new_child_l2_ids"],
            [
                "L2-l1-evidence-and-object-schema",
                "L2-evidence-first-layered-retrieval",
                "L2-l2-l3-hierarchy-and-promotion",
                "L2-memory-architecture-tradeoffs",
                "L2-latency-token-budget-architecture",
            ],
        )

    def test_operational_constraints_has_reviewed_child_candidates(self) -> None:
        node = _l2_node(80, meeting_count=6)
        node["l2_id"] = "L2-operational-constraints-and-resource-budget"
        node["label"] = "operational constraints and resource budget"

        sidecar = build_l3_promotion_sidecar({"l2_nodes": [node]}, total_l1_count=120)

        record = sidecar["promotions"][0]
        self.assertEqual(record["source_l2_id"], "L2-operational-constraints-and-resource-budget")
        self.assertEqual(record["status"], "promotion_candidate")
        self.assertEqual(
            record["mapping"]["new_child_l2_ids"],
            [
                "L2-api-budget-and-cost",
                "L2-token-latency-and-runtime-budget",
                "L2-offline-eval-and-no-llm-mode",
                "L2-scale-quota-and-budget-guardrails",
            ],
        )

    def test_l2_topic_grouping_has_reviewed_child_candidates(self) -> None:
        node = _l2_node(80, meeting_count=6)
        node["l2_id"] = "L2-l2-topic-grouping"
        node["label"] = "l2 topic grouping"

        sidecar = build_l3_promotion_sidecar({"l2_nodes": [node]}, total_l1_count=120)

        record = sidecar["promotions"][0]
        self.assertEqual(record["source_l2_id"], "L2-l2-topic-grouping")
        self.assertEqual(record["status"], "promotion_candidate")
        self.assertEqual(
            record["mapping"]["new_child_l2_ids"],
            [
                "L2-topic-labeling-and-grouping-rules",
                "L2-evidence-timeline-and-linked-l1",
                "L2-l3-promotion-and-child-splits",
                "L2-importance-editor-and-feedback",
                "L2-retrieval-demo-and-traceability",
            ],
        )

    def test_reviewed_child_assignment_routes_representative_large_topic_entries(self) -> None:
        node = {
            "l2_id": "L2-memory-processing-architecture",
            "label": "memory processing architecture",
            "current_state": "Large memory architecture topic.",
            "linked_obj_ids": [
                "L1-evidence",
                "L1-layered",
                "L1-promotion",
                "L1-latency",
                "L1-tradeoff",
            ],
            "meeting_ids": ["SYN-001"],
            "timeline_digest": [
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": "L1-evidence",
                    "summary": "L1 memory objects must preserve concrete evidence lines before any topic abstraction.",
                },
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": "L1-layered",
                    "summary": "Evidence-first layered retrieval starts from L1 evidence seeds.",
                },
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": "L1-promotion",
                    "summary": "If an L2 is too large, L3 promotion should create child L2 navigation.",
                },
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": "L1-latency",
                    "summary": "Latency and token budget affect whether this architecture can fit the prompt.",
                },
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": "L1-tradeoff",
                    "summary": "The architecture discussion compares topic memory against ordinary RAG and full context.",
                },
            ],
        }
        promotions = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=10,
            thresholds={"absolute_l1_threshold": 5},
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        materialized = build_l3_materialization_sidecar(
            {"l2_nodes": [node]},
            promotions,
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        index = materialized["l3_index"]
        self.assertEqual(index["L1-evidence"]["child_l2_id"], "L2-l1-evidence-and-object-schema")
        self.assertEqual(index["L1-layered"]["child_l2_id"], "L2-evidence-first-layered-retrieval")
        self.assertEqual(index["L1-promotion"]["child_l2_id"], "L2-l2-l3-hierarchy-and-promotion")
        self.assertEqual(index["L1-latency"]["child_l2_id"], "L2-latency-token-budget-architecture")
        self.assertEqual(index["L1-tradeoff"]["child_l2_id"], "L2-memory-architecture-tradeoffs")

    def test_materialized_l3_omits_zero_event_child_l2_nodes(self) -> None:
        node = {
            "l2_id": "L2-retrieval-baseline-comparison",
            "label": "retrieval baseline comparison",
            "current_state": "Baseline comparison topic.",
            "linked_obj_ids": ["L1-full", "L1-layered"],
            "meeting_ids": ["SYN-001"],
            "timeline_digest": [
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": "L1-full",
                    "summary": "Full context baseline includes all transcript context and may be truncated.",
                },
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": "L1-layered",
                    "summary": "Layered memory comparison uses L1 evidence, L2 context, and L3 navigation.",
                },
            ],
        }
        promotions = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=10,
            thresholds={"absolute_l1_threshold": 2},
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        materialized = build_l3_materialization_sidecar(
            {"l2_nodes": [node]},
            promotions,
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        child_ids = {
            child["l2_id"]
            for child in materialized["l3_nodes"][0]["child_l2_nodes"]
        }
        self.assertIn("L2-full-context-baseline", child_ids)
        self.assertIn("L2-layered-memory-comparison", child_ids)
        self.assertNotIn("L2-traditional-rag-baseline", child_ids)
        self.assertNotIn("L2-answer-quality-and-traceability", child_ids)
        self.assertEqual(set(materialized["l3_index"]), {"L1-full", "L1-layered"})

    def test_materialized_child_l2_has_real_topic_state_not_placeholder(self) -> None:
        node = {
            "l2_id": "L2-retrieval-baseline-comparison",
            "label": "retrieval baseline comparison",
            "current_state": "Baseline comparison topic.",
            "linked_obj_ids": ["L1-full", "L1-layered"],
            "meeting_ids": ["0429", "0506"],
            "timeline_digest": [
                {
                    "meeting_id": "0429",
                    "meeting_date": "2026-04-29",
                    "obj_id": "L1-full",
                    "summary": "Full context baseline injects the whole transcript and creates a high token cost.",
                },
                {
                    "meeting_id": "0506",
                    "meeting_date": "2026-05-06",
                    "obj_id": "L1-layered",
                    "summary": "Layered memory answers from L1 evidence plus L2 and L3 navigation context.",
                },
            ],
        }
        promotions = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=10,
            thresholds={"absolute_l1_threshold": 2},
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        materialized = build_l3_materialization_sidecar(
            {"l2_nodes": [node]},
            promotions,
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        child = next(
            child
            for child in materialized["l3_nodes"][0]["child_l2_nodes"]
            if child["l2_id"] == "L2-layered-memory-comparison"
        )
        self.assertNotIn("This child L2 has", child["current_state"])
        self.assertIn("Layered memory", child["current_state"])
        self.assertIn("evolution_summary", child)
        self.assertIn("latest_position", child)
        self.assertIn("key_rationale", child)
        self.assertIn("open_tensions", child)
        self.assertEqual(child["representative_l1_ids"], ["L1-layered"])

    def test_memory_evaluation_validation_metrics_route_to_metrics_child(self) -> None:
        node = {
            "l2_id": "L2-memory-evaluation-strategy",
            "label": "memory evaluation strategy",
            "current_state": "Memory evaluation topic.",
            "linked_obj_ids": ["L1-metrics"],
            "meeting_ids": ["SYN-001"],
            "timeline_digest": [
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": "L1-metrics",
                    "summary": (
                        "The validation report should track L2 hit rate, L3 hit rate, "
                        "context token count, unassigned L1 count, duplicate assignment "
                        "count, and prompt budget pass rate."
                    ),
                }
            ],
        }
        promotions = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=10,
            thresholds={"absolute_l1_threshold": 1},
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        materialized = build_l3_materialization_sidecar(
            {"l2_nodes": [node]},
            promotions,
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        self.assertEqual(
            materialized["l3_index"]["L1-metrics"]["child_l2_id"],
            "L2-memory-mechanism-evaluation-metrics",
        )

    def test_transcript_segmentation_strategy_routes_away_from_tool_calling_child(self) -> None:
        node = {
            "l2_id": "L2-transcript-segmentation-and-idea-unit-coverage",
            "label": "transcript segmentation and idea-unit coverage",
            "current_state": "Transcript segmentation topic.",
            "linked_obj_ids": ["L1-strategy"],
            "meeting_ids": ["SYN-001"],
            "timeline_digest": [
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": "L1-strategy",
                    "summary": (
                        "The transcript segmentation strategy needs validation report "
                        "checks for largest child L2 size, manual review count, and "
                        "prompt budget pass rate."
                    ),
                }
            ],
        }
        promotions = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=10,
            thresholds={"absolute_l1_threshold": 1},
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        materialized = build_l3_materialization_sidecar(
            {"l2_nodes": [node]},
            promotions,
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        self.assertEqual(
            materialized["l3_index"]["L1-strategy"]["child_l2_id"],
            "L2-transcript-segmentation-strategy-and-validation",
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
        unknown["l2_id"] = "L2-memory-retrieval"
        unknown["label"] = "memory retrieval"
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

        self.assertEqual(calls, ["L2-memory-retrieval"])
        records = {record["source_l2_id"]: record for record in sidecar["promotions"]}
        self.assertEqual(records["L2-transcript-segmentation-and-idea-unit-coverage"]["llm_usage"]["used"], False)
        self.assertEqual(records["L2-memory-retrieval"]["status"], "promotion_candidate")
        self.assertEqual(
            records["L2-memory-retrieval"]["mapping"]["new_child_l2_ids"],
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
            llm_source_l2_ids={"L2-memory-retrieval"},
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        self.assertEqual(calls, ["L2-memory-retrieval"])
        records = {record["source_l2_id"]: record for record in sidecar["promotions"]}
        self.assertEqual(records["L2-memory-evaluation-strategy"]["status"], "promotion_candidate")
        self.assertEqual(records["L2-memory-retrieval"]["status"], "promotion_candidate")
        self.assertEqual(records["L2-memory-retrieval"]["llm_usage"]["used"], True)

    def test_llm_supplied_child_taxonomy_materializes_unknown_large_l2(self) -> None:
        node = _l2_node(3, meeting_count=2)
        node["l2_id"] = "L2-custom-evaluation-topic"
        node["label"] = "custom evaluation topic"
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
        self.assertEqual(materialized["l3_nodes"][0]["promoted_from_l2_id"], "L2-custom-evaluation-topic")
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
            "L2-window-and-boundary-selection",
        )
        self.assertEqual(
            materialized["l3_index"]["L1-b"]["child_l2_id"],
            "L2-missing-line-coverage",
        )
        self.assertEqual(
            materialized["l3_index"]["L1-c"]["child_l2_id"],
            "L2-evidence-grounding-and-line-coverage",
        )

    def test_transcript_idea_unit_child_assignments_cover_specific_scenarios(self) -> None:
        node = {
            "l2_id": "L2-transcript-segmentation-and-idea-unit-coverage",
            "label": "transcript segmentation and idea-unit coverage",
            "current_state": "Crowded transcript processing topic.",
            "linked_obj_ids": [
                "L1-method",
                "L1-coverage",
                "L1-granularity",
                "L1-classification",
                "L1-core",
            ],
            "meeting_ids": ["0408", "0429", "0506"],
            "timeline_digest": [
                {
                    "meeting_id": "0506",
                    "meeting_date": "2026-05-06",
                    "obj_id": "L1-method",
                    "summary": (
                        "The top-down pipeline uses a Segment Agent to extract "
                        "idea units from transcript segments."
                    ),
                },
                {
                    "meeting_id": "0506",
                    "meeting_date": "2026-05-06",
                    "obj_id": "L1-coverage",
                    "summary": (
                        "The process can miss transcript gaps, so missed lines "
                        "are added back as low-quality raw text idea units."
                    ),
                },
                {
                    "meeting_id": "0506",
                    "meeting_date": "2026-05-06",
                    "obj_id": "L1-granularity",
                    "summary": (
                        "A segment is a broader topic while an idea unit is a "
                        "smaller semantic unit inside that segment."
                    ),
                },
                {
                    "meeting_id": "0429",
                    "meeting_date": "2026-04-29",
                    "obj_id": "L1-classification",
                    "summary": (
                        "Type agents classify candidate objects and reconcile "
                        "labels before final memory object creation."
                    ),
                },
                {
                    "meeting_id": "0408",
                    "meeting_date": "2026-04-08",
                    "obj_id": "L1-core",
                    "summary": "An atomic unit should contain one standalone idea.",
                },
            ],
        }
        promotions = build_l3_promotion_sidecar(
            {"l2_nodes": [node]},
            total_l1_count=10,
            thresholds={"absolute_l1_threshold": 5},
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        materialized = build_l3_materialization_sidecar(
            {"l2_nodes": [node]},
            promotions,
            generated_at_utc="2026-05-09T00:00:00Z",
        )

        index = materialized["l3_index"]
        self.assertEqual(
            index["L1-method"]["child_l2_id"],
            "L2-idea-unit-generation-methods",
        )
        self.assertEqual(
            index["L1-coverage"]["child_l2_id"],
            "L2-missing-line-coverage",
        )
        self.assertEqual(
            index["L1-granularity"]["child_l2_id"],
            "L2-idea-unit-granularity-and-semantics",
        )
        self.assertEqual(
            index["L1-classification"]["child_l2_id"],
            "L2-idea-unit-candidate-classification",
        )
        self.assertEqual(
            index["L1-core"]["child_l2_id"],
            "L2-idea-unit-generation",
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
            self.assertEqual(len(child_l2_candidates), 12)
            return [
                {
                    "obj_id": "L1-a",
                    "child_l2_id": "L2-window-and-boundary-selection",
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

    def test_tiny_child_l2_is_reported_as_merge_candidate(self) -> None:
        l3_view = {
            "l3_nodes": [
                {
                    "l3_id": "L3-memory-retrieval",
                    "label": "memory retrieval",
                    "child_l2_nodes": [
                        {
                            "l2_id": "L2-benchmark-evaluation",
                            "label": "benchmark evaluation",
                            "assignment_criteria": ["benchmark", "locomo", "memo"],
                            "timeline_digest": [
                                {"obj_id": "L1-a", "summary": "LOCOMO benchmark setup."},
                                {"obj_id": "L1-b", "summary": "MEMO benchmark setup."},
                            ],
                            "linked_obj_ids": ["L1-a", "L1-b"],
                            "meeting_ids": ["0318"],
                            "event_count": 2,
                        },
                        {
                            "l2_id": "L2-dataset-benchmark-evaluation",
                            "label": "dataset benchmark evaluation",
                            "assignment_criteria": ["benchmark", "dataset", "locomo"],
                            "timeline_digest": [
                                {"obj_id": "L1-c", "summary": "Dataset benchmark and LOCOMO quality."},
                                {"obj_id": "L1-d", "summary": "Dataset quality for benchmark scoring."},
                                {"obj_id": "L1-e", "summary": "Benchmark dataset coverage."},
                                {"obj_id": "L1-f", "summary": "Evaluation dataset notes."},
                                {"obj_id": "L1-g", "summary": "Dataset setup."},
                            ],
                            "linked_obj_ids": ["L1-c", "L1-d", "L1-e", "L1-f", "L1-g"],
                            "meeting_ids": ["0318", "0429"],
                            "event_count": 5,
                        },
                    ],
                }
            ]
        }

        review = build_l2_merge_review_sidecar(l3_view, generated_at_utc="2026-05-09T00:00:00Z")

        self.assertEqual(review["schema_version"], 1)
        self.assertEqual(review["merge_review_count"], 1)
        item = review["merge_reviews"][0]
        self.assertEqual(item["source_child_l2_id"], "L2-benchmark-evaluation")
        self.assertEqual(item["recommended_target_child_l2_id"], "L2-dataset-benchmark-evaluation")
        self.assertEqual(item["action"], "merge_candidate")
        self.assertIn("too_few_l1_nodes", item["reason_codes"])

    def test_tiny_child_l2_with_low_sibling_similarity_is_watched_not_merged(self) -> None:
        l3_view = {
            "l3_nodes": [
                {
                    "l3_id": "L3-memory-retrieval",
                    "label": "memory retrieval",
                    "child_l2_nodes": [
                        {
                            "l2_id": "L2-niche-privacy-risk",
                            "label": "privacy risk",
                            "assignment_criteria": ["privacy", "consent", "risk"],
                            "timeline_digest": [
                                {"obj_id": "L1-a", "summary": "A niche privacy consent risk was raised."},
                                {"obj_id": "L1-b", "summary": "The privacy risk still needs follow-up."},
                            ],
                            "linked_obj_ids": ["L1-a", "L1-b"],
                            "meeting_ids": ["0318"],
                            "event_count": 2,
                        },
                        {
                            "l2_id": "L2-benchmark-evaluation",
                            "label": "benchmark evaluation",
                            "assignment_criteria": ["benchmark", "locomo", "metric"],
                            "timeline_digest": [
                                {"obj_id": "L1-c", "summary": "Benchmark setup and scoring metrics."},
                                {"obj_id": "L1-d", "summary": "LOCOMO benchmark comparison."},
                                {"obj_id": "L1-e", "summary": "Evaluation metric notes."},
                                {"obj_id": "L1-f", "summary": "Judge scoring setup."},
                                {"obj_id": "L1-g", "summary": "Dataset benchmark coverage."},
                            ],
                            "linked_obj_ids": ["L1-c", "L1-d", "L1-e", "L1-f", "L1-g"],
                            "meeting_ids": ["0318", "0429"],
                            "event_count": 5,
                        },
                    ],
                }
            ]
        }

        review = build_l2_merge_review_sidecar(l3_view, generated_at_utc="2026-05-09T00:00:00Z")

        self.assertEqual(review["merge_review_count"], 1)
        item = review["merge_reviews"][0]
        self.assertEqual(item["source_child_l2_id"], "L2-niche-privacy-risk")
        self.assertEqual(item["recommended_target_child_l2_id"], "")
        self.assertEqual(item["action"], "watch_until_more_evidence")
        self.assertIn("low_sibling_similarity", item["reason_codes"])


if __name__ == "__main__":
    unittest.main()
