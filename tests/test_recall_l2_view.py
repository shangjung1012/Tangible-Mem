from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

import recall  # noqa: E402


def _tree() -> dict:
    return {
        "meetings": [
            {
                "meeting_id": "0307",
                "meeting_date": "2026-03-07",
                "memory_objects": [
                    {
                        "obj_id": "L1-0307-001",
                        "type": "decision",
                        "content": "Use L1 semantic hits as the recall entrypoint.",
                        "evidence": "The team agreed recall should start from concrete L1 evidence.",
                        "importance": 0.9,
                        "related_topics": ["memory retrieval"],
                    }
                ],
            }
        ]
    }


def _l1_hit() -> dict:
    return {
        "source": "long_term_l1",
        "meeting_id": "0307",
        "meeting_date": "2026-03-07",
        "obj_id": "L1-0307-001",
        "type": "decision",
        "content": "Use L1 semantic hits as the recall entrypoint.",
        "evidence": "The team agreed recall should start from concrete L1 evidence.",
        "importance": 0.9,
        "related_topics": ["memory retrieval"],
        "score": 0.94,
    }


def _l2_index() -> dict:
    return {
        "L1-0307-001": {
            "obj_id": "L1-0307-001",
            "l2_id": "L2-memory-retrieval",
            "l2_label": "memory retrieval",
            "confidence": 0.91,
            "assignment_reason": "concept_rule",
        }
    }


def _l2_view() -> dict:
    return {
        "l2_nodes": [
            {
                "l2_id": "L2-memory-retrieval",
                "label": "memory retrieval",
                "current_state": "Recall starts from semantic L1 evidence and expands upward.",
                "timeline_digest": [
                    {
                        "meeting_id": "0307",
                        "meeting_date": "2026-03-07",
                        "obj_id": "L1-0307-001",
                        "summary": "The team chose L1 evidence as the recall entrypoint.",
                    },
                    {
                        "meeting_id": "0408",
                        "meeting_date": "2026-04-08",
                        "obj_id": "L1-0408-001",
                        "summary": "Later discussion refined upward L2 context.",
                    },
                ],
                "linked_obj_ids": ["L1-0307-001", "L1-0408-001"],
                "meeting_ids": ["0307", "0408"],
            }
        ]
    }


def _promoted_l3_view() -> dict:
    return {
        "l3_nodes": [
            {
                "l3_id": "L3-memory-retrieval",
                "label": "memory retrieval",
                "promoted_from_l2_id": "L2-memory-retrieval",
                "child_l2_nodes": [
                    {
                        "l2_id": "L2-semantic-l1-search",
                        "label": "semantic L1 search",
                        "current_state": "Search starts from concrete semantic L1 hits.",
                        "linked_obj_ids": ["L1-0307-001"],
                        "timeline_digest": [
                            {
                                "meeting_id": "0307",
                                "meeting_date": "2026-03-07",
                                "obj_id": "L1-0307-001",
                                "summary": "The team chose L1 evidence as the recall entrypoint.",
                            }
                        ],
                        "event_count": 1,
                    }
                ],
            }
        ]
    }


def _promoted_l3_index() -> dict:
    return {
        "L1-0307-001": {
            "obj_id": "L1-0307-001",
            "source_l2_id": "L2-memory-retrieval",
            "l3_id": "L3-memory-retrieval",
            "child_l2_id": "L2-semantic-l1-search",
            "child_l2_label": "semantic L1 search",
        }
    }


class RecallL2ViewTests(unittest.TestCase):
    def test_l1_hit_expands_to_l2_view_context(self) -> None:
        with patch.object(recall, "embed_text", return_value=[1.0]), patch.object(
            recall,
            "search_l1_semantic",
            return_value=[_l1_hit()],
        ):
            result = recall.recall(
                query="How should recall use L1 evidence?",
                plan={
                    "complexity": "simple",
                    "search_targets": ["long_term_l1", "long_term_l2"],
                    "keywords": [],
                },
                tree=_tree(),
                api_key="test-key",
                l2_index=_l2_index(),
                l2_view=_l2_view(),
                relations_index={},
            )

        self.assertEqual(result["long_term_l1"][0]["evidence"], _l1_hit()["evidence"])
        self.assertEqual(len(result["long_term_l2"]), 1)
        l2 = result["long_term_l2"][0]
        self.assertEqual(l2["source"], "long_term_l2")
        self.assertEqual(l2["l2_id"], "L2-memory-retrieval")
        self.assertEqual(l2["label"], "memory retrieval")
        self.assertEqual(l2["matched_l1_ids"], ["L1-0307-001"])
        self.assertIn("semantic L1 evidence", l2["current_state"])

    def test_missing_l2_index_entry_does_not_crash(self) -> None:
        with patch.object(recall, "embed_text", return_value=[1.0]), patch.object(
            recall,
            "search_l1_semantic",
            return_value=[_l1_hit()],
        ):
            result = recall.recall(
                query="What if L2 is missing?",
                plan={
                    "complexity": "simple",
                    "search_targets": ["long_term_l1", "long_term_l2"],
                    "keywords": [],
                },
                tree=_tree(),
                api_key="test-key",
                l2_index={},
                l2_view=_l2_view(),
                relations_index={},
            )

        self.assertEqual(len(result["long_term_l1"]), 1)
        self.assertEqual(result["long_term_l2"], [])

    def test_prompt_context_includes_compact_l2_view_information(self) -> None:
        formatted = recall.format_recall_for_prompt(
            {
                "project_profile": None,
                "long_term_l2": [
                    {
                        "source": "long_term_l2",
                        "l2_id": "L2-memory-retrieval",
                        "label": "memory retrieval",
                        "current_state": "Recall starts from semantic L1 evidence and expands upward.",
                        "matched_l1_ids": ["L1-0307-001"],
                        "timeline_digest": [
                            {
                                "meeting_id": "0307",
                                "meeting_date": "2026-03-07",
                                "obj_id": "L1-0307-001",
                                "summary": "The team chose L1 evidence as the recall entrypoint.",
                            }
                        ],
                    }
                ],
                "long_term_l1": [_l1_hit()],
                "short_term_results": [],
            }
        )

        self.assertIn("=== L2 / Child-L2 Evolution Context ===", formatted)
        self.assertIn("[L2-memory-retrieval] memory retrieval", formatted)
        self.assertIn("Recall starts from semantic L1 evidence", formatted)
        self.assertIn("matched L1: L1-0307-001", formatted)
        self.assertIn("The team chose L1 evidence", formatted)

    def test_l2_context_includes_l3_promotion_when_sidecar_exists(self) -> None:
        promotions = {
            "promotions": [
                {
                    "source_l2_id": "L2-memory-retrieval",
                    "proposed_l3_id": "L3-memory-retrieval",
                    "source_l2_label": "memory retrieval",
                    "status": "ready_for_materialization",
                    "child_l2_candidates": [
                        {
                            "child_l2_id": "L2-semantic-l1-search",
                            "label": "semantic L1 search",
                            "split_reason": "separates the entrypoint search behavior",
                        },
                        {
                            "child_l2_id": "L2-upward-l2-expansion",
                            "label": "upward L2 expansion",
                            "split_reason": "separates topic expansion behavior",
                        },
                    ],
                    "mapping": {
                        "old_l2_id": "L2-memory-retrieval",
                        "new_l3_id": "L3-memory-retrieval",
                        "new_child_l2_ids": [
                            "L2-semantic-l1-search",
                            "L2-upward-l2-expansion",
                        ],
                    },
                }
            ]
        }

        expanded = recall.expand_l2_view_context(
            [_l1_hit()],
            _l2_index(),
            _l2_view(),
            l3_promotions=promotions,
        )
        formatted = recall.format_recall_for_prompt(
            {
                "project_profile": None,
                "long_term_l2": expanded,
                "long_term_l1": [_l1_hit()],
                "short_term_results": [],
            }
        )

        self.assertEqual(expanded[0]["promoted_to_l3"]["l3_id"], "L3-memory-retrieval")
        self.assertIn("promoted L3: L3-memory-retrieval", formatted)
        self.assertIn("child L2: L2-semantic-l1-search semantic L1 search", formatted)

    def test_l2_context_includes_materialized_l3_child_context(self) -> None:
        l3_view = {
            "l3_index": {
                "L1-0307-001": {
                    "obj_id": "L1-0307-001",
                    "source_l2_id": "L2-memory-retrieval",
                    "l3_id": "L3-memory-retrieval",
                    "child_l2_id": "L2-semantic-l1-search",
                    "child_l2_label": "semantic L1 search",
                }
            },
            "l3_nodes": [
                {
                    "l3_id": "L3-memory-retrieval",
                    "label": "memory retrieval",
                    "promoted_from_l2_id": "L2-memory-retrieval",
                    "child_l2_nodes": [
                        {
                            "l2_id": "L2-semantic-l1-search",
                            "label": "semantic L1 search",
                            "current_state": "Search starts from concrete semantic L1 hits.",
                            "linked_obj_ids": ["L1-0307-001"],
                            "timeline_digest": [
                                {
                                    "meeting_id": "0307",
                                    "meeting_date": "2026-03-07",
                                    "obj_id": "L1-0307-001",
                                    "summary": "The team chose L1 evidence as the recall entrypoint.",
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        expanded = recall.expand_l2_view_context(
            [_l1_hit()],
            _l2_index(),
            _l2_view(),
            l3_view=l3_view,
        )
        formatted = recall.format_recall_for_prompt(
            {
                "project_profile": None,
                "long_term_l2": expanded,
                "long_term_l1": [_l1_hit()],
                "short_term_results": [],
            }
        )

        child_context = expanded[0]["materialized_l3"]["child_l2_contexts"][0]
        self.assertEqual(child_context["l2_id"], "L2-semantic-l1-search")
        self.assertEqual(child_context["matched_l1_ids"], ["L1-0307-001"])
        self.assertIn("materialized L3: L3-memory-retrieval", formatted)
        self.assertIn("materialized child L2: L2-semantic-l1-search semantic L1 search", formatted)

    def test_recall_prefers_materialized_child_l2_over_old_source_l2(self) -> None:
        with patch.object(recall, "embed_text", return_value=[1.0]), patch.object(
            recall,
            "search_l1_semantic",
            return_value=[_l1_hit()],
        ):
            result = recall.recall(
                query="How should recall use L1 evidence?",
                plan={
                    "complexity": "simple",
                    "search_targets": ["long_term_l1", "long_term_l2", "long_term_l3"],
                    "keywords": [],
                },
                tree=_tree(),
                api_key="test-key",
                l2_index=_l2_index(),
                l2_view=_l2_view(),
                l3_view=_promoted_l3_view(),
                l3_index=_promoted_l3_index(),
                relations_index={},
                include_retrieval_debug=True,
            )

        self.assertIn("global_topic_map", result)
        self.assertEqual(result["long_term_l2"][0]["source"], "long_term_child_l2")
        self.assertEqual(result["long_term_l2"][0]["l2_id"], "L2-semantic-l1-search")
        self.assertEqual(result["long_term_l2"][0]["parent_l3_id"], "L3-memory-retrieval")
        self.assertEqual(result["retrieval_debug"]["selected_child_l2_count"], 1)

    def test_recall_falls_back_to_l2_when_l3_index_has_no_seed(self) -> None:
        with patch.object(recall, "embed_text", return_value=[1.0]), patch.object(
            recall,
            "search_l1_semantic",
            return_value=[_l1_hit()],
        ):
            result = recall.recall(
                query="How should recall use L1 evidence?",
                plan={
                    "complexity": "simple",
                    "search_targets": ["long_term_l1", "long_term_l2"],
                    "keywords": [],
                },
                tree=_tree(),
                api_key="test-key",
                l2_index=_l2_index(),
                l2_view=_l2_view(),
                l3_view=_promoted_l3_view(),
                l3_index={},
                relations_index={},
                include_retrieval_debug=True,
            )

        self.assertEqual(result["long_term_l2"][0]["source"], "long_term_l2")
        self.assertEqual(result["long_term_l2"][0]["l2_id"], "L2-memory-retrieval")

    def test_lexical_recall_does_not_call_embedding_api(self) -> None:
        with patch.object(recall, "embed_text", side_effect=AssertionError("embedding called")):
            result = recall.recall(
                query="semantic L1 evidence recall",
                plan={
                    "complexity": "simple",
                    "search_targets": ["long_term_l1", "long_term_l2"],
                    "keywords": ["semantic", "evidence"],
                },
                tree=_tree(),
                api_key="",
                l2_index=_l2_index(),
                l2_view=_l2_view(),
                l3_view={},
                l3_index={},
                relations_index={},
                include_retrieval_debug=True,
                retrieval_mode="lexical",
            )

        self.assertEqual(result["long_term_l1"][0]["obj_id"], "L1-0307-001")
        self.assertEqual(result["retrieval_debug"]["retrieval_mode"], "lexical")

    def test_formatter_orders_l1_evidence_before_l2_context(self) -> None:
        formatted = recall.format_recall_for_prompt(
            {
                "global_topic_map": {
                    "l3_families": [
                        {
                            "l3_id": "L3-memory-retrieval",
                            "label": "memory retrieval",
                            "child_l2": [
                                {
                                    "l2_id": "L2-semantic-l1-search",
                                    "label": "semantic L1 search",
                                }
                            ],
                        }
                    ],
                    "l2_topics": [],
                },
                "long_term_l1": [_l1_hit()],
                "long_term_l2": [
                    {
                        "source": "long_term_child_l2",
                        "parent_l3_id": "L3-memory-retrieval",
                        "parent_l3_label": "memory retrieval",
                        "l2_id": "L2-semantic-l1-search",
                        "label": "semantic L1 search",
                        "matched_l1_ids": ["L1-0307-001"],
                        "topic_size": 1,
                        "selected_event_count": 1,
                        "omitted_event_count": 0,
                        "current_state": "Search starts from concrete semantic L1 hits.",
                        "timeline_digest": [
                            {
                                "meeting_id": "0307",
                                "meeting_date": "2026-03-07",
                                "obj_id": "L1-0307-001",
                                "summary": "The team chose L1 evidence as the recall entrypoint.",
                            }
                        ],
                    }
                ],
                "long_term_l3": [
                    {"l3_id": "L3-memory-retrieval", "label": "memory retrieval"}
                ],
                "retrieval_debug": {"selected_l1_count": 1},
            },
            include_debug=True,
        )

        self.assertIn("=== Global Topic Map ===", formatted)
        self.assertIn("=== L1 Evidence Seeds ===", formatted)
        self.assertIn("=== L2 / Child-L2 Evolution Context ===", formatted)
        self.assertLess(
            formatted.index("=== L1 Evidence Seeds ==="),
            formatted.index("=== L2 / Child-L2 Evolution Context ==="),
        )
        self.assertIn("evidence: The team agreed recall should start", formatted)
        self.assertIn("parent L3: L3-memory-retrieval memory retrieval", formatted)

    def test_global_topic_map_uses_event_count_when_linked_ids_are_absent(self) -> None:
        global_map = recall.build_global_topic_map(
            {
                "l2_nodes": [
                    {
                        "l2_id": "L2-unpromoted",
                        "label": "unpromoted topic",
                        "event_count": 7,
                    }
                ]
            },
            {
                "l3_nodes": [
                    {
                        "l3_id": "L3-memory-retrieval",
                        "label": "memory retrieval",
                        "promoted_from_l2_id": "L2-memory-retrieval",
                        "child_l2_nodes": [
                            {
                                "l2_id": "L2-semantic-l1-search",
                                "label": "semantic L1 search",
                                "event_count": 5,
                            }
                        ],
                    }
                ]
            },
        )

        self.assertEqual(global_map["l3_families"][0]["child_l2"][0]["event_count"], 5)
        self.assertEqual(global_map["l2_topics"][0]["event_count"], 7)

    def test_global_topic_map_prioritizes_query_relevant_child_l2_navigation(self) -> None:
        global_map = recall.build_global_topic_map(
            {"l2_nodes": []},
            {
                "l3_nodes": [
                    {
                        "l3_id": "L3-memory-evaluation-strategy",
                        "label": "memory evaluation strategy",
                        "promoted_from_l2_id": "L2-memory-evaluation-strategy",
                        "child_l2_nodes": [
                            {
                                "l2_id": "L2-overall-memory-system-evaluation",
                                "label": "overall memory system evaluation",
                                "event_count": 8,
                            }
                        ],
                    },
                    {
                        "l3_id": "L3-transcript-segmentation-and-idea-unit-coverage",
                        "label": "transcript segmentation and idea-unit coverage",
                        "promoted_from_l2_id": "L2-transcript-segmentation-and-idea-unit-coverage",
                        "child_l2_nodes": [
                            {
                                "l2_id": "L2-window-and-boundary-selection",
                                "label": "window and boundary selection",
                                "event_count": 9,
                            },
                            {
                                "l2_id": "L2-idea-unit-generation-methods",
                                "label": "idea-unit generation methods",
                                "event_count": 20,
                            },
                            {
                                "l2_id": "L2-missing-line-coverage",
                                "label": "missing-line coverage",
                                "event_count": 7,
                            },
                        ],
                    },
                ]
            },
            query="transcript segmentation 這個大主題被拆成哪些 child L2?",
            max_chars=120,
        )

        self.assertEqual(
            global_map["l3_families"][0]["l3_id"],
            "L3-transcript-segmentation-and-idea-unit-coverage",
        )
        self.assertEqual(
            [child["l2_id"] for child in global_map["l3_families"][0]["child_l2"]],
            [
                "L2-window-and-boundary-selection",
                "L2-idea-unit-generation-methods",
                "L2-missing-line-coverage",
            ],
        )

    def test_l2_ranking_prefers_query_label_match_over_generic_seed_majority(self) -> None:
        l1_results = [
            {"obj_id": f"L1-life-{index}", "score": 0.90, "importance": 0.8}
            for index in range(5)
        ] + [
            {"obj_id": f"L1-retrieval-{index}", "score": 0.88, "importance": 0.8}
            for index in range(2)
        ]
        l2_index = {
            **{
                row["obj_id"]: {"l2_id": "L2-memory-lifecycle"}
                for row in l1_results[:5]
            },
            **{
                row["obj_id"]: {"l2_id": "L2-memory-retrieval"}
                for row in l1_results[5:]
            },
        }
        l2_view = {
            "l2_nodes": [
                {
                    "l2_id": "L2-memory-lifecycle",
                    "label": "memory lifecycle",
                    "current_state": "Forgetting, importance decay, and lifecycle rules.",
                    "event_count": 31,
                    "timeline_digest": [{"obj_id": row["obj_id"]} for row in l1_results[:5]],
                },
                {
                    "l2_id": "L2-memory-retrieval",
                    "label": "memory retrieval",
                    "current_state": "Retrieval starts from L1 evidence and expands topic context.",
                    "event_count": 31,
                    "timeline_digest": [{"obj_id": row["obj_id"]} for row in l1_results[5:]],
                },
            ]
        }

        selected, _, _ = recall.select_layered_l2_context(
            "long-term memory retrieval current behavior",
            l1_results,
            l2_index,
            l2_view,
            max_relevant_l2_summaries=1,
            max_expanded_l2_topics=1,
        )

        self.assertEqual(selected[0]["l2_id"], "L2-memory-retrieval")

    def test_l2_ranking_does_not_let_tiny_off_topic_node_beat_query_match(self) -> None:
        l1_results = [
            {"obj_id": "L1-agent-1", "score": 0.53, "importance": 0.52},
            {"obj_id": "L1-agent-2", "score": 0.52, "importance": 0.52},
            {"obj_id": "L1-demo", "score": 0.51, "importance": 0.78},
            {"obj_id": "L1-other-1", "score": 0.50, "importance": 0.7},
            {"obj_id": "L1-other-2", "score": 0.49, "importance": 0.7},
            {"obj_id": "L1-other-3", "score": 0.48, "importance": 0.7},
            {"obj_id": "L1-other-4", "score": 0.47, "importance": 0.7},
            {"obj_id": "L1-other-5", "score": 0.46, "importance": 0.7},
        ]
        l2_index = {
            "L1-agent-1": {"l2_id": "L2-agentic-pipeline-control"},
            "L1-agent-2": {"l2_id": "L2-agentic-pipeline-control"},
            "L1-demo": {"l2_id": "L2-project-demo-strategy"},
            "L1-other-1": {"l2_id": "L2-other-a"},
            "L1-other-2": {"l2_id": "L2-other-b"},
            "L1-other-3": {"l2_id": "L2-other-c"},
            "L1-other-4": {"l2_id": "L2-other-d"},
            "L1-other-5": {"l2_id": "L2-other-e"},
        }
        l2_nodes = [
            {
                "l2_id": "L2-agentic-pipeline-control",
                "label": "agentic pipeline control",
                "current_state": "The agent-based architecture separates manager dispatch from workers.",
                "event_count": 60,
                "timeline_digest": [{"obj_id": "L1-agent-1"}, {"obj_id": "L1-agent-2"}],
            },
            {
                "l2_id": "L2-project-demo-strategy",
                "label": "project demo strategy",
                "current_state": "Demo planning and visualization strategy.",
                "event_count": 6,
                "timeline_digest": [{"obj_id": "L1-demo"}],
            },
        ]
        for index in range(1, 6):
            l2_nodes.append(
                {
                    "l2_id": f"L2-other-{chr(96 + index)}",
                    "label": f"other topic {index}",
                    "current_state": "Unrelated context.",
                    "event_count": 25,
                    "timeline_digest": [{"obj_id": f"L1-other-{index}"}],
                }
            )

        selected, _, _ = recall.select_layered_l2_context(
            "manager-agent 架構是怎麼演變出來的？",
            l1_results,
            l2_index,
            {"l2_nodes": l2_nodes},
            max_relevant_l2_summaries=1,
            max_expanded_l2_topics=1,
        )

        self.assertEqual(selected[0]["l2_id"], "L2-agentic-pipeline-control")

    def test_chinese_evolution_query_is_detected(self) -> None:
        self.assertTrue(recall._is_evolution_query("這個設計從 0307 到 0506 是怎麼演進的？"))
        self.assertTrue(recall._is_evolution_query("後來 retrieve 的設計變成什麼樣子？"))
        self.assertTrue(recall._is_evolution_query("為什麼最後沒有採用 adaptive segmentation？"))

    def test_evolution_timeline_slice_covers_mentioned_meeting_endpoints(self) -> None:
        timeline = [
            {
                "meeting_id": "0307",
                "meeting_date": "2026-03-07",
                "obj_id": "L1-0307-start",
                "summary": "Early update-first memory design.",
            },
            {
                "meeting_id": "0325",
                "meeting_date": "2026-03-25",
                "obj_id": "L1-0325-middle",
                "summary": "Object-based memory direction became more concrete.",
            },
            {
                "meeting_id": "0429",
                "meeting_date": "2026-04-29",
                "obj_id": "L1-0429-match",
                "summary": "Retrieval evaluation and topic lifecycle discussion.",
            },
            {
                "meeting_id": "0506",
                "meeting_date": "2026-05-06",
                "obj_id": "L1-0506-latest",
                "summary": "Latest inspector and visualization retrieve design.",
            },
        ]

        selected, omitted = recall._select_timeline_slice(
            timeline,
            ["L1-0429-match"],
            max_events=3,
            max_event_chars=200,
            query="從 0307 到 0506 retrieve 設計怎麼演進？",
        )

        selected_ids = [row["obj_id"] for row in selected]
        self.assertIn("L1-0307-start", selected_ids)
        self.assertIn("L1-0506-latest", selected_ids)
        self.assertIn("L1-0429-match", selected_ids)
        self.assertEqual(omitted, 1)

    def test_lexical_query_expansion_finds_parallel_stm_ltm_update_evidence(self) -> None:
        tree = {
            "meetings": [
                {
                    "meeting_id": "0422",
                    "meeting_date": "2026-04-22",
                    "memory_objects": [
                        {
                            "obj_id": "L1-0422-parallel",
                            "type": "decision",
                            "content": "短期記憶和長期記憶會平行更新，避免同時具有近期細節與長期脈絡價值的資訊被過早丟棄。",
                            "evidence": "團隊決定不要先把 idea unit 路由到單一 memory。",
                            "importance": 0.86,
                            "related_topics": ["short-term memory", "long-term memory"],
                        }
                    ],
                }
            ]
        }

        results = recall.search_l1_lexical(
            tree,
            "Why not route transcript units to only STM or LTM?",
            top_k=5,
        )

        self.assertEqual(results[0]["obj_id"], "L1-0422-parallel")

    def test_deep_layered_profile_allows_more_context_than_default(self) -> None:
        from retrieval_profiles import get_retrieval_budget_profile

        default = get_retrieval_budget_profile("default")
        deep = get_retrieval_budget_profile("deep_layered")

        self.assertGreater(deep["max_l1_seeds_for_prompt"], default["max_l1_seeds_for_prompt"])
        self.assertGreater(deep["max_events_per_child_l2"], default["max_events_per_child_l2"])
        self.assertGreater(deep["max_event_chars"], default["max_event_chars"])


if __name__ == "__main__":
    unittest.main()
