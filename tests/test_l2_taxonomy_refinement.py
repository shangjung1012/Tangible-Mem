from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"

import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

from share_mem.store import refresh_share_mem_outputs  # noqa: E402
from build_l2_view import build_l2_view_outputs  # noqa: E402
from taxonomy_refinement import (  # noqa: E402
    build_unknown_large_l2_split_proposal_sidecar,
    build_gold_topic_mapping_report,
    compare_l2_assignment_runs,
)


def _write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _share_tree() -> dict:
    return {
        "tree_version": 1,
        "last_updated_utc": "2026-05-11T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [
            {
                "meeting_id": "0506",
                "timestamp": "2026-05-06T00:00:00Z",
                "meeting_date": "2026-05-06",
                "source_file": "0506.txt",
                "phase_id": "",
                "memory_objects": [
                    {
                        "obj_id": "L1-a",
                        "type": "decision",
                        "legacy_type": "decision",
                        "content": "The team adopted layered memory comparison against full context.",
                        "importance": 0.84,
                        "evidence": "line 1",
                        "related_topics": ["retrieval baseline comparison"],
                        "related_obj_ids": [],
                    },
                    {
                        "obj_id": "L1-b",
                        "type": "finding",
                        "legacy_type": "result",
                        "content": "Idea-unit generation stayed linked to segmentation.",
                        "importance": 0.72,
                        "evidence": "line 2",
                        "related_topics": ["idea units"],
                        "related_obj_ids": [],
                    },
                    {
                        "obj_id": "L1-c",
                        "type": "finding",
                        "legacy_type": "result",
                        "content": "A new candidate-only note appeared.",
                        "importance": 0.55,
                        "evidence": "line 3",
                        "related_topics": ["new topic"],
                        "related_obj_ids": [],
                    },
                ],
            }
        ],
    }


class L2TaxonomyRefinementTests(unittest.TestCase):
    def test_compare_l2_assignment_runs_flags_changed_lost_and_gained_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share_root = root / "share_mem"
            old_root = root / "old" / "l2"
            new_root = root / "new" / "l2"
            refresh_share_mem_outputs(root=share_root, tree=_share_tree(), source_transcript_dir=root)
            _write_json(
                old_root / "l2_index.json",
                """
{
  "L1-a": {"obj_id": "L1-a", "l2_id": "L2-memory-processing-architecture", "l2_label": "memory processing architecture"},
  "L1-b": {"obj_id": "L1-b", "l2_id": "L2-transcript-segmentation-and-idea-unit-coverage", "l2_label": "transcript segmentation and idea-unit coverage"}
}
""".strip(),
            )
            _write_json(
                new_root / "l2_index.json",
                """
{
  "L1-a": {"obj_id": "L1-a", "l2_id": "L2-retrieval-baseline-comparison", "l2_label": "retrieval baseline comparison"},
  "L1-c": {"obj_id": "L1-c", "l2_id": "L2-new-topic", "l2_label": "new topic"}
}
""".strip(),
            )

            report = compare_l2_assignment_runs(
                baseline_l2_root=old_root,
                candidate_l2_root=new_root,
                share_mem_root=share_root,
                generated_at_utc="2026-05-11T00:00:00Z",
            )

            self.assertEqual(report["baseline_linked_count"], 2)
            self.assertEqual(report["candidate_linked_count"], 2)
            self.assertEqual(report["changed_assignment_count"], 1)
            self.assertEqual(report["lost_assignment_count"], 1)
            self.assertEqual(report["gained_assignment_count"], 1)
            self.assertEqual(report["manual_review_count"], 2)
            review_codes = {item["reason_code"] for item in report["manual_review_queue"]}
            self.assertIn("high_importance_changed_assignment", review_codes)
            self.assertIn("lost_assignment", review_codes)

    def test_unknown_large_l2_split_proposals_are_sidecar_only_and_reviewable(self) -> None:
        l2_view = {
            "schema_version": 1,
            "l2_nodes": [
                {
                    "l2_id": "L2-speaker-and-owner-attribution",
                    "label": "speaker and owner attribution",
                    "linked_obj_ids": [f"L1-{i:03d}" for i in range(12)],
                    "meeting_ids": ["SYN-001", "SYN-002"],
                    "timeline_digest": [
                        {
                            "meeting_id": "SYN-001",
                            "meeting_date": "2026-06-01",
                            "obj_id": "L1-001",
                            "summary": "Speaker diarization and role mapping should remain cautious.",
                        },
                        {
                            "meeting_id": "SYN-001",
                            "meeting_date": "2026-06-01",
                            "obj_id": "L1-002",
                            "summary": "Owner attribution depends on speaker diarization confidence.",
                        },
                        {
                            "meeting_id": "SYN-002",
                            "meeting_date": "2026-06-08",
                            "obj_id": "L1-003",
                            "summary": "Role mapping errors can mislead action owner retrieval.",
                        },
                        {
                            "meeting_id": "SYN-002",
                            "meeting_date": "2026-06-08",
                    "obj_id": "L1-004",
                    "summary": "Speaker identity evidence should be shown with uncertainty.",
                        },
                        {
                            "meeting_id": "SYN-002",
                            "meeting_date": "2026-06-08",
                            "obj_id": "L1-005",
                            "summary": "Token latency and context cost should be tracked in retrieval experiments.",
                        },
                        {
                            "meeting_id": "SYN-002",
                            "meeting_date": "2026-06-08",
                            "obj_id": "L1-006",
                            "summary": "Latency budget comparisons need token cost and wall-clock timing.",
                        },
                    ],
                },
                {
                    "l2_id": "L2-reviewed-large-topic",
                    "label": "reviewed large topic",
                    "linked_obj_ids": [f"L1-reviewed-{i:03d}" for i in range(12)],
                    "meeting_ids": ["SYN-001"],
                    "timeline_digest": [],
                },
            ],
        }
        l3_promotions = {
            "schema_version": 1,
            "promotions": [
                {
                    "source_l2_id": "L2-speaker-and-owner-attribution",
                    "source_l2_label": "speaker and owner attribution",
                    "status": "needs_split_review",
                    "metrics": {"linked_l1_count": 12},
                    "child_l2_candidates": [],
                },
                {
                    "source_l2_id": "L2-reviewed-large-topic",
                    "source_l2_label": "reviewed large topic",
                    "status": "promotion_candidate",
                    "metrics": {"linked_l1_count": 12},
                    "child_l2_candidates": [
                        {"child_l2_id": "L2-reviewed-child", "label": "reviewed child"}
                    ],
                },
            ],
        }

        sidecar = build_unknown_large_l2_split_proposal_sidecar(
            l2_view,
            l3_promotions,
            generated_at_utc="2026-05-11T00:00:00Z",
            min_event_count=10,
            max_child_proposals=3,
        )

        self.assertEqual(sidecar["schema_version"], 1)
        self.assertEqual(sidecar["proposal_count"], 1)
        proposal = sidecar["split_proposals"][0]
        self.assertEqual(proposal["source_l2_id"], "L2-speaker-and-owner-attribution")
        self.assertTrue(proposal["manual_review_required"])
        self.assertEqual(proposal["proposal_mode"], "deterministic_keyword_clusters")
        self.assertGreaterEqual(len(proposal["candidate_child_l2"]), 2)
        self.assertTrue(
            any(
                "speaker" in child["label"] or "diarization" in child["label"]
                for child in proposal["candidate_child_l2"]
            )
        )
        self.assertEqual(proposal["source_event_count"], 12)
        self.assertNotIn("L2-reviewed-large-topic", sidecar["source_l2_ids"])

    def test_split_proposals_prune_nested_duplicate_terms(self) -> None:
        l2_view = {
            "l2_nodes": [
                {
                    "l2_id": "L2-dataset-selection",
                    "label": "dataset selection",
                    "linked_obj_ids": [f"L1-{index:03d}" for index in range(24)],
                    "meeting_ids": ["SYN-001"],
                    "event_count": 24,
                    "timeline_digest": [
                        {
                            "obj_id": f"L1-{index:03d}",
                            "summary": "Speaker diarization and role identity affect dataset ownership.",
                        }
                        for index in range(24)
                    ],
                }
            ],
        }
        l3_promotions = {
            "promotions": [
                {
                    "source_l2_id": "L2-dataset-selection",
                    "source_l2_label": "dataset selection",
                    "status": "needs_split_review",
                    "metrics": {"linked_l1_count": 24},
                    "child_l2_candidates": [],
                }
            ]
        }

        sidecar = build_unknown_large_l2_split_proposal_sidecar(
            l2_view,
            l3_promotions,
            generated_at_utc="2026-05-11T00:00:00Z",
        )

        labels = [
            child["label"]
            for child in sidecar["split_proposals"][0]["candidate_child_l2"]
        ]
        self.assertIn("speaker diarization", labels)
        self.assertNotIn("speaker", labels)
        self.assertNotIn("diarization", labels)
        self.assertIn(
            "insufficient_distinct_keyword_clusters",
            sidecar["split_proposals"][0]["diagnostics"]["reason_codes"],
        )

    def test_split_proposals_reject_non_topic_label_fragments(self) -> None:
        l2_view = {
            "l2_nodes": [
                {
                    "l2_id": "L2-memory-processing-architecture",
                    "label": "memory processing architecture",
                    "linked_obj_ids": [f"L1-{index:03d}" for index in range(30)],
                    "meeting_ids": ["SYN-001"],
                    "event_count": 30,
                    "timeline_digest": [
                        {
                            "obj_id": "L1-001",
                            "summary": "Layered retrieval architecture should compare full context and RAG baselines.",
                        },
                        {
                            "obj_id": "L1-002",
                            "summary": "Layered retrieval architecture gives evidence-first context.",
                        },
                        {
                            "obj_id": "L1-003",
                            "summary": "The team said 180 LLM rather than retrieval architecture should not become a topic.",
                        },
                        {
                            "obj_id": "L1-004",
                            "summary": "The phrase rather than appears in several notes rather than as a topic.",
                        },
                        {
                            "obj_id": "L1-005",
                            "summary": "Long term and LTM alone are broad memory vocabulary, not child topic labels.",
                        },
                        {
                            "obj_id": "L1-006",
                            "summary": "Term integration appears as a lexical fragment, but STM LTM integration is the real topic.",
                        },
                        {
                            "obj_id": "L1-007",
                            "summary": "Tokens and retrieve are implementation words, not child topic labels.",
                        },
                        {
                            "obj_id": "L1-008",
                            "summary": "The word floor is a repeated artifact and should not become a topic.",
                        },
                        {
                            "obj_id": "L1-009",
                            "summary": "Tokens repeated in implementation notes should be filtered.",
                        },
                        {
                            "obj_id": "L1-010",
                            "summary": "Retrieve repeated as a verb should not be a topic label.",
                        },
                        {
                            "obj_id": "L1-011",
                            "summary": "Floor repeated in notes is an artifact rather than a topic label.",
                        },
                    ],
                }
            ]
        }
        l3_promotions = {
            "promotions": [
                {
                    "source_l2_id": "L2-memory-processing-architecture",
                    "source_l2_label": "memory processing architecture",
                    "status": "needs_split_review",
                    "metrics": {"linked_l1_count": 30},
                    "child_l2_candidates": [],
                }
            ]
        }

        sidecar = build_unknown_large_l2_split_proposal_sidecar(
            l2_view,
            l3_promotions,
            generated_at_utc="2026-05-11T00:00:00Z",
            min_event_count=10,
        )

        labels = {
            child["label"]
            for child in sidecar["split_proposals"][0]["candidate_child_l2"]
        }
        self.assertTrue(any("retrieval" in label for label in labels))
        self.assertNotIn("180 llm", labels)
        self.assertNotIn("rather than", labels)
        self.assertNotIn("long term", labels)
        self.assertNotIn("ltm", labels)
        self.assertNotIn("term integration", labels)
        self.assertNotIn("tokens", labels)
        self.assertNotIn("retrieve", labels)
        self.assertNotIn("floor", labels)
        diagnostics = sidecar["split_proposals"][0]["diagnostics"]
        self.assertGreaterEqual(diagnostics["rejected_term_count"], 1)

    def test_build_l2_view_writes_split_proposals_for_unknown_large_l2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share_root = root / "share_mem"
            out_root = root / "long_term" / "l2"
            tree = _share_tree()
            tree["meetings"][0]["memory_objects"] = [
                {
                    "obj_id": f"L1-dataset-{index:03d}",
                    "type": "finding",
                    "legacy_type": "result",
                    "content": (
                        "Speaker diarization and role mapping affect dataset owner "
                        "attribution in retrieval evaluation."
                    ),
                    "importance": 0.72,
                    "evidence": "line",
                    "related_topics": ["dataset selection"],
                    "related_obj_ids": [],
                }
                for index in range(24)
            ]
            refresh_share_mem_outputs(root=share_root, tree=tree, source_transcript_dir=root)

            build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            proposal_path = out_root.parent / "l3" / "l2_split_proposals.json"
            self.assertTrue(proposal_path.exists())
            sidecar = __import__("json").loads(proposal_path.read_text(encoding="utf-8"))
            self.assertEqual(sidecar["proposal_count"], 1)
            self.assertEqual(sidecar["split_proposals"][0]["source_l2_id"], "L2-dataset-selection")

    def test_gold_topic_mapping_report_flags_unlinked_and_impure_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share_root = root / "share_mem"
            l2_root = root / "l2"
            l3_root = root / "l3"
            out_root = root / "report"
            refresh_share_mem_outputs(root=share_root, tree=_share_tree(), source_transcript_dir=root)
            _write_json(
                l2_root / "l2_index.json",
                """
{
  "L1-a": {"obj_id": "L1-a", "l2_id": "L2-retrieval-baseline-comparison", "l2_label": "retrieval baseline comparison"},
  "L1-b": {"obj_id": "L1-b", "l2_id": "L2-transcript-segmentation-and-idea-unit-coverage", "l2_label": "transcript segmentation and idea-unit coverage"}
}
""".strip(),
            )
            _write_json(
                l3_root / "l3_index.json",
                """
{
  "L1-a": {"obj_id": "L1-a", "l3_id": "L3-retrieval-baseline-comparison", "child_l2_id": "L2-layered-memory-comparison", "child_l2_label": "layered-memory comparison"}
}
""".strip(),
            )
            gold_path = root / "obj_id_to_expected_topic.json"
            _write_json(
                gold_path,
                """
{
  "L1-a": "baseline comparison",
  "L1-b": "baseline comparison",
  "L1-c": "api budget"
}
""".strip(),
            )

            report = build_gold_topic_mapping_report(
                share_mem_root=share_root,
                l2_root=l2_root,
                l3_root=l3_root,
                gold_path=gold_path,
                out=out_root,
                generated_at_utc="2026-05-11T00:00:00Z",
            )

            self.assertEqual(report["gold_topic_count"], 2)
            self.assertEqual(report["gold_obj_count"], 3)
            self.assertEqual(report["unlinked_gold_obj_count"], 1)
            self.assertEqual(report["fully_linked_topic_count"], 1)
            self.assertEqual(report["low_purity_topic_count"], 1)
            self.assertTrue((out_root / "gold_topic_to_l2_l3_mapping.json").exists())
            self.assertTrue((out_root / "gold_topic_to_l2_l3_mapping.md").exists())


if __name__ == "__main__":
    unittest.main()
