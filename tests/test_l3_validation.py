from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

from share_mem.store import refresh_share_mem_outputs  # noqa: E402
from validate_l3_view import validate_l3_view_outputs  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _share_tree(obj_ids: list[str]) -> dict:
    return {
        "tree_version": 1,
        "last_updated_utc": "2026-05-11T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [
            {
                "meeting_id": "SYN-001",
                "timestamp": "2026-06-01T00:00:00Z",
                "meeting_date": "2026-06-01",
                "source_file": "SYN-001.txt",
                "phase_id": "",
                "memory_objects": [
                    {
                        "obj_id": obj_id,
                        "type": "finding",
                        "legacy_type": "result",
                        "content": "Evidence-first layered retrieval uses L1 seeds before summary context.",
                        "importance": 0.72,
                        "evidence": "synthetic line",
                        "related_topics": ["evidence-first layered retrieval"],
                        "related_obj_ids": [],
                    }
                    for obj_id in obj_ids
                ],
            }
        ],
    }


def _materialized_l3(child_summary: str, *, criteria: list[str]) -> tuple[dict, dict, dict]:
    obj_ids = [f"L1-{index:03d}" for index in range(40)]
    timeline = [
        {
            "meeting_id": "SYN-001",
            "meeting_date": "2026-06-01",
            "obj_id": obj_id,
            "summary": child_summary,
        }
        for obj_id in obj_ids
    ]
    l2_view = {
        "schema_version": 1,
        "l2_nodes": [
            {
                "l2_id": "L2-memory-processing-architecture",
                "label": "memory processing architecture",
                "linked_obj_ids": obj_ids,
                "meeting_ids": ["SYN-001"],
                "timeline_digest": timeline,
                "event_count": len(obj_ids),
            }
        ],
    }
    l3_view = {
        "schema_version": 1,
        "materialized_l3_count": 1,
        "l3_nodes": [
            {
                "l3_id": "L3-memory-processing-architecture",
                "label": "memory processing architecture",
                "promoted_from_l2_id": "L2-memory-processing-architecture",
                "child_l2_nodes": [
                    {
                        "l2_id": "L2-evidence-first-layered-retrieval",
                        "label": "evidence-first layered retrieval",
                        "assignment_criteria": criteria,
                        "linked_obj_ids": obj_ids,
                        "meeting_ids": ["SYN-001"],
                        "timeline_digest": timeline,
                        "event_count": len(obj_ids),
                    }
                ],
            }
        ],
    }
    l3_index = {
        obj_id: {
            "obj_id": obj_id,
            "source_l2_id": "L2-memory-processing-architecture",
            "parent_l3_id": "L3-memory-processing-architecture",
            "child_l2_id": "L2-evidence-first-layered-retrieval",
        }
        for obj_id in obj_ids
    }
    return l2_view, l3_view, l3_index


class L3ValidationTests(unittest.TestCase):
    def test_related_topic_family_l3_validates_against_child_l2_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj_ids = ["L1-001", "L1-002", "L1-003"]
            share_root = root / "share_mem"
            l2_root = root / "long_term" / "l2"
            l3_root = root / "long_term" / "l3"
            refresh_share_mem_outputs(root=share_root, tree=_share_tree(obj_ids), source_transcript_dir=root)
            timeline = [
                {
                    "meeting_id": "SYN-001",
                    "meeting_date": "2026-06-01",
                    "obj_id": obj_id,
                    "summary": "Meter calibration drift evidence.",
                }
                for obj_id in obj_ids
            ]
            _write_json(
                l2_root / "l2_view.json",
                {
                    "schema_version": 1,
                    "l2_nodes": [
                        {
                            "l2_id": "L2-meter-calibration-drift",
                            "label": "meter calibration drift",
                            "linked_obj_ids": obj_ids,
                            "meeting_ids": ["SYN-001"],
                            "timeline_digest": timeline,
                            "event_count": len(obj_ids),
                        }
                    ],
                },
            )
            _write_json(
                l3_root / "l3_view.json",
                {
                    "schema_version": 1,
                    "source": "synthetic_related_topics_family_materialization",
                    "materialized_l3_count": 1,
                    "l3_nodes": [
                        {
                            "l3_id": "L3-energy-data-and-sensor-pipeline",
                            "label": "energy data and sensor pipeline",
                            "source": "related_topics_family_sidecar",
                            "child_l2_nodes": [
                                {
                                    "l2_id": "L2-meter-calibration-drift",
                                    "label": "meter calibration drift",
                                    "linked_obj_ids": obj_ids,
                                    "timeline_digest": timeline,
                                    "event_count": len(obj_ids),
                                    "assignment_criteria": ["meter calibration drift"],
                                }
                            ],
                        }
                    ],
                },
            )
            _write_json(
                l3_root / "l3_index.json",
                {
                    obj_id: {
                        "obj_id": obj_id,
                        "l3_id": "L3-energy-data-and-sensor-pipeline",
                        "child_l2_id": "L2-meter-calibration-drift",
                    }
                    for obj_id in obj_ids
                },
            )
            _write_json(l3_root / "l2_merge_review.json", {"merge_reviews": []})

            report = validate_l3_view_outputs(
                share_mem_root=share_root,
                l2_root=l2_root,
                l3_root=l3_root,
                out=l3_root / "validation",
            )

            self.assertEqual(report["severe_count"], 0)
            self.assertEqual(report["promotion_coverage"]["invalid_l3_index_count"], 0)

    def test_coherent_large_child_needs_slice_not_split_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj_ids = [f"L1-{index:03d}" for index in range(40)]
            share_root = root / "share_mem"
            l2_root = root / "long_term" / "l2"
            l3_root = root / "long_term" / "l3"
            refresh_share_mem_outputs(root=share_root, tree=_share_tree(obj_ids), source_transcript_dir=root)
            l2_view, l3_view, l3_index = _materialized_l3(
                "Evidence-first layered retrieval uses L1 evidence seeds before L2 evolution context.",
                criteria=["evidence-first layered retrieval", "L1 evidence seeds"],
            )
            _write_json(l2_root / "l2_view.json", l2_view)
            _write_json(l3_root / "l3_view.json", l3_view)
            _write_json(l3_root / "l3_index.json", l3_index)
            _write_json(l3_root / "l2_merge_review.json", {"merge_reviews": []})

            report = validate_l3_view_outputs(
                share_mem_root=share_root,
                l2_root=l2_root,
                l3_root=l3_root,
                out=l3_root / "validation",
                prompt_context_char_threshold=200,
            )

            issue_codes = [issue["code"] for issue in report["issues"]]
            self.assertIn("needs_retrieval_slice", issue_codes)
            self.assertNotIn("oversized_child_l2", issue_codes)
            self.assertEqual(report["manual_review_count"], 0)
            child_report = report["child_l2_reports"][0]
            self.assertEqual(child_report["size_bucket"], "needs_split_review")
            self.assertEqual(child_report["scale_assessment"], "large_coherent_needs_retrieval_slice")

    def test_low_coherence_large_child_still_needs_split_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj_ids = [f"L1-{index:03d}" for index in range(40)]
            share_root = root / "share_mem"
            l2_root = root / "long_term" / "l2"
            l3_root = root / "long_term" / "l3"
            refresh_share_mem_outputs(root=share_root, tree=_share_tree(obj_ids), source_transcript_dir=root)
            l2_view, l3_view, l3_index = _materialized_l3(
                "This row discusses unrelated dataset ownership and meeting logistics.",
                criteria=["evidence-first layered retrieval", "L1 evidence seeds"],
            )
            _write_json(l2_root / "l2_view.json", l2_view)
            _write_json(l3_root / "l3_view.json", l3_view)
            _write_json(l3_root / "l3_index.json", l3_index)
            _write_json(l3_root / "l2_merge_review.json", {"merge_reviews": []})

            report = validate_l3_view_outputs(
                share_mem_root=share_root,
                l2_root=l2_root,
                l3_root=l3_root,
                out=l3_root / "validation",
                prompt_context_char_threshold=200,
            )

            issue_codes = [issue["code"] for issue in report["issues"]]
            self.assertIn("oversized_child_l2", issue_codes)
            self.assertIn("needs_retrieval_slice", issue_codes)
            self.assertEqual(report["manual_review_count"], 1)
            child_report = report["child_l2_reports"][0]
            self.assertEqual(child_report["scale_assessment"], "large_low_coherence_needs_split_review")


if __name__ == "__main__":
    unittest.main()
