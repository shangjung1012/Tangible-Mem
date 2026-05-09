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

        self.assertIn("=== L2 主題脈絡 ===", formatted)
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


if __name__ == "__main__":
    unittest.main()
