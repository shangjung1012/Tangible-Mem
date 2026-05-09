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


def _obj(obj_id: str, content: str) -> dict:
    return {
        "obj_id": obj_id,
        "type": "finding",
        "legacy_type": "result",
        "content": content,
        "evidence": content,
        "importance": 0.7,
        "related_topics": ["memory evaluation"],
    }


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class L3ValidationTests(unittest.TestCase):
    def test_validation_checks_exact_child_assignment_and_merge_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share_root = root / "share_mem"
            l2_root = root / "long_term" / "l2"
            l3_root = root / "long_term" / "l3"
            out_root = l3_root / "validation"
            tree = {
                "meetings": [
                    {
                        "meeting_id": "0318",
                        "meeting_date": "2026-03-18",
                        "memory_objects": [
                            _obj("L1-a", "LOCOMO benchmark setup."),
                            _obj("L1-b", "MEMO benchmark setup."),
                            _obj("L1-c", "LLM-as-judge scoring."),
                            _obj("L1-d", "Evaluation metric scoring."),
                        ],
                    }
                ],
                "phases": [],
                "project_profile": {},
            }
            refresh_share_mem_outputs(root=share_root, tree=tree, source_transcript_dir=root)
            _write_json(
                l2_root / "l2_view.json",
                {
                    "l2_nodes": [
                        {
                            "l2_id": "L2-memory-evaluation-strategy",
                            "label": "memory evaluation strategy",
                            "linked_obj_ids": ["L1-a", "L1-b", "L1-c", "L1-d"],
                            "timeline_digest": [
                                {
                                    "meeting_id": "0318",
                                    "meeting_date": "2026-03-18",
                                    "obj_id": "L1-a",
                                    "summary": "LOCOMO benchmark setup.",
                                },
                                {
                                    "meeting_id": "0318",
                                    "meeting_date": "2026-03-18",
                                    "obj_id": "L1-b",
                                    "summary": "MEMO benchmark setup.",
                                },
                                {
                                    "meeting_id": "0318",
                                    "meeting_date": "2026-03-18",
                                    "obj_id": "L1-c",
                                    "summary": "LLM-as-judge scoring.",
                                },
                                {
                                    "meeting_id": "0318",
                                    "meeting_date": "2026-03-18",
                                    "obj_id": "L1-d",
                                    "summary": "Evaluation metric scoring.",
                                },
                            ],
                        }
                    ]
                },
            )
            _write_json(
                l3_root / "l3_view.json",
                {
                    "l3_nodes": [
                        {
                            "l3_id": "L3-memory-evaluation-strategy",
                            "label": "memory evaluation strategy",
                            "promoted_from_l2_id": "L2-memory-evaluation-strategy",
                            "child_l2_nodes": [
                                {
                                    "l2_id": "L2-benchmark-evaluation",
                                    "label": "benchmark evaluation",
                                    "assignment_criteria": ["benchmark", "locomo", "memo"],
                                    "linked_obj_ids": ["L1-a", "L1-b"],
                                    "timeline_digest": [
                                        {"obj_id": "L1-a", "summary": "LOCOMO benchmark setup."},
                                        {"obj_id": "L1-b", "summary": "MEMO benchmark setup."},
                                    ],
                                    "event_count": 2,
                                },
                                {
                                    "l2_id": "L2-llm-as-judge-scoring",
                                    "label": "LLM-as-judge scoring",
                                    "assignment_criteria": ["llm-as-judge", "scoring", "metric"],
                                    "linked_obj_ids": ["L1-c", "L1-d"],
                                    "timeline_digest": [
                                        {"obj_id": "L1-c", "summary": "LLM-as-judge scoring."},
                                        {"obj_id": "L1-d", "summary": "Evaluation metric scoring."},
                                    ],
                                    "event_count": 2,
                                },
                            ],
                        }
                    ]
                },
            )
            _write_json(
                l3_root / "l3_index.json",
                {
                    "L1-a": {"source_l2_id": "L2-memory-evaluation-strategy", "l3_id": "L3-memory-evaluation-strategy", "child_l2_id": "L2-benchmark-evaluation"},
                    "L1-b": {"source_l2_id": "L2-memory-evaluation-strategy", "l3_id": "L3-memory-evaluation-strategy", "child_l2_id": "L2-benchmark-evaluation"},
                    "L1-c": {"source_l2_id": "L2-memory-evaluation-strategy", "l3_id": "L3-memory-evaluation-strategy", "child_l2_id": "L2-llm-as-judge-scoring"},
                    "L1-d": {"source_l2_id": "L2-memory-evaluation-strategy", "l3_id": "L3-memory-evaluation-strategy", "child_l2_id": "L2-llm-as-judge-scoring"},
                },
            )
            _write_json(
                l3_root / "l2_merge_review.json",
                {
                    "schema_version": 1,
                    "merge_reviews": [
                        {
                            "parent_l3_id": "L3-memory-evaluation-strategy",
                            "source_child_l2_id": "L2-benchmark-evaluation",
                            "action": "merge_candidate",
                        },
                        {
                            "parent_l3_id": "L3-memory-evaluation-strategy",
                            "source_child_l2_id": "L2-llm-as-judge-scoring",
                            "action": "merge_candidate",
                        },
                    ],
                },
            )

            report = validate_l3_view_outputs(
                share_mem_root=share_root,
                l2_root=l2_root,
                l3_root=l3_root,
                out=out_root,
            )

            self.assertEqual(report["severe_count"], 0)
            self.assertEqual(report["promotion_coverage"]["unassigned_l1_count"], 0)
            self.assertEqual(report["promotion_coverage"]["duplicate_assignment_count"], 0)
            self.assertEqual(report["child_size_distribution"]["needs_merge_review"], 2)
            self.assertTrue((out_root / "l3_validation_report.json").exists())
            self.assertTrue((out_root / "l3_validation_report.md").exists())
            self.assertTrue((out_root / "manual_l3_review_queue.json").exists())


if __name__ == "__main__":
    unittest.main()
