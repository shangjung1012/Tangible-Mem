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

from build_l2_view import (  # noqa: E402
    build_l2_view_outputs,
    choose_l2_assignment,
    load_l2_index,
    load_l2_view,
)
from share_mem.store import refresh_share_mem_outputs  # noqa: E402
from validate_l2_view import validate_l2_view_outputs  # noqa: E402


def _obj(
    obj_id: str,
    obj_type: str,
    content: str,
    *,
    importance: float = 0.7,
    evidence: str = "evidence",
    topics: list[str] | None = None,
) -> dict:
    return {
        "obj_id": obj_id,
        "type": obj_type,
        "legacy_type": obj_type,
        "content": content,
        "importance": importance,
        "evidence": evidence,
        "related_topics": topics or [],
        "related_obj_ids": [],
    }


def _tree() -> dict:
    return {
        "tree_version": 3,
        "last_updated_utc": "2026-05-09T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [
            {
                "meeting_id": "0318",
                "timestamp": "2026-03-18T00:00:00Z",
                "meeting_date": "2026-03-18",
                "source_file": "meeting_recording/transcript/grace/0318.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj(
                        "L1-0318-001",
                        "finding",
                        "LOCOMO and MEMO evaluations require multi-hop memory reasoning and LLM-as-judge checks.",
                        importance=0.74,
                    ),
                    _obj(
                        "L1-0318-002",
                        "finding",
                        "The group briefly noted a meeting setup detail that has no long-term memory relevance.",
                        importance=0.31,
                    ),
                ],
            },
            {
                "meeting_id": "0429",
                "timestamp": "2026-04-29T00:00:00Z",
                "meeting_date": "2026-04-29",
                "source_file": "meeting_recording/transcript/grace/0429.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj(
                        "L1-0429-025",
                        "proposal",
                        "Hierarchical memory processing should use bottom-up L1 retrieval before pulling L2 and L3 context.",
                        importance=0.82,
                    ),
                    _obj(
                        "L1-0429-030",
                        "open_issue",
                        "Fixed transcript chunks can fragment a design issue across segment boundaries.",
                        importance=0.76,
                    ),
                ],
            },
            {
                "meeting_id": "0506",
                "timestamp": "2026-05-06T00:00:00Z",
                "meeting_date": "2026-05-06",
                "source_file": "meeting_recording/transcript/grace/0506.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj(
                        "L1-0506-009",
                        "argument",
                        "Top-down RAG processing was debated against the bottom-up L1 to L2 memory architecture.",
                        importance=0.79,
                    ),
                    _obj(
                        "L1-0506-010",
                        "approach_change",
                        "Dynamic segment boundary repair should reduce data fragmentation before L1 extraction.",
                        importance=0.77,
                    ),
                    _obj(
                        "L1-0506-038",
                        "open_issue",
                        "The team still needs to decide whether discard-as-L1 and importance thresholds affect memory lifecycle updates.",
                        importance=0.68,
                    ),
                    _obj(
                        "L1-0506-099",
                        "finding",
                        "A local aside about the meeting room was mentioned once.",
                        importance=0.2,
                    ),
                ],
            },
        ],
    }


class L2ViewTests(unittest.TestCase):
    def test_build_l2_view_writes_subset_index_manifest_and_unlinked_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            out_root = Path(tmp) / "long_term" / "l2"
            refresh_share_mem_outputs(root=share_root, tree=_tree(), source_transcript_dir=Path(tmp))

            manifest = build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            self.assertTrue((out_root / "l2_view.json").exists())
            self.assertTrue((out_root / "l2_index.json").exists())
            self.assertTrue((out_root / "manifest.json").exists())
            self.assertTrue((out_root / "unlinked_l1_report.json").exists())
            self.assertTrue((out_root / "l2_updates" / "0506.json").exists())
            self.assertEqual(manifest["source_l1_count"], 8)
            self.assertLess(manifest["linked_l1_count"], manifest["source_l1_count"])

            l2_index = load_l2_index(out_root)
            self.assertIn("L1-0429-025", l2_index)
            self.assertIn("L1-0506-009", l2_index)
            self.assertNotIn("L1-0318-002", l2_index)
            self.assertEqual(
                l2_index["L1-0429-025"]["l2_id"],
                l2_index["L1-0506-009"]["l2_id"],
            )
            self.assertEqual(
                l2_index["L1-0506-009"]["l2_label"],
                "memory processing architecture",
            )

            unlinked = json.loads((out_root / "unlinked_l1_report.json").read_text(encoding="utf-8"))
            self.assertIn("L1-0318-002", {item["obj_id"] for item in unlinked["unlinked_objects"]})

    def test_l2_view_keeps_clusters_as_l2_directions_not_l1_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            out_root = Path(tmp) / "long_term" / "l2"
            refresh_share_mem_outputs(root=share_root, tree=_tree(), source_transcript_dir=Path(tmp))

            build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            l2_view = load_l2_view(out_root)
            labels = {node["label"] for node in l2_view["l2_nodes"]}
            self.assertIn("memory evaluation strategy", labels)
            self.assertIn("memory processing architecture", labels)
            self.assertIn("data fragmentation", labels)
            self.assertNotIn("decision", labels)
            self.assertNotIn("design decision", labels)

    def test_validate_l2_view_flags_generic_label_and_high_importance_unlinked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            out_root = Path(tmp) / "long_term" / "l2"
            validation_out = out_root / "validation"
            refresh_share_mem_outputs(root=share_root, tree=_tree(), source_transcript_dir=Path(tmp))
            build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            l2_view = load_l2_view(out_root)
            l2_view["l2_nodes"].append(
                {
                    "l2_id": "L2-memory",
                    "label": "memory",
                    "current_state": "Generic bucket.",
                    "timeline_digest": [],
                    "linked_obj_ids": [],
                    "meeting_ids": [],
                    "event_count": 0,
                    "confidence": 0.2,
                }
            )
            (out_root / "l2_view.json").write_text(
                json.dumps(l2_view, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            unlinked = json.loads((out_root / "unlinked_l1_report.json").read_text(encoding="utf-8"))
            unlinked["review_queue"] = []
            unlinked["unlinked_objects"].append(
                {
                    "obj_id": "L1-0318-002",
                    "meeting_id": "0318",
                    "importance": 0.82,
                    "reason": "forced_test_gap",
                    "review_required": True,
                }
            )
            (out_root / "unlinked_l1_report.json").write_text(
                json.dumps(unlinked, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            report = validate_l2_view_outputs(
                share_mem_root=share_root,
                root=out_root,
                out=validation_out,
            )

            issue_codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("generic_l2_label", issue_codes)
            self.assertIn("high_importance_unlinked", issue_codes)
            self.assertTrue((validation_out / "l2_validation_report.json").exists())
            self.assertTrue((validation_out / "manual_l2_review_queue.json").exists())

    def test_validate_l2_view_flags_index_view_and_unlinked_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            out_root = Path(tmp) / "long_term" / "l2"
            validation_out = out_root / "validation"
            refresh_share_mem_outputs(root=share_root, tree=_tree(), source_transcript_dir=Path(tmp))
            build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            l2_index = load_l2_index(out_root)
            obj_id = "L1-0429-025"
            l2_id = l2_index[obj_id]["l2_id"]
            l2_view = load_l2_view(out_root)
            for node in l2_view["l2_nodes"]:
                if node["l2_id"] == l2_id:
                    node["linked_obj_ids"].remove(obj_id)
                    break
            (out_root / "l2_view.json").write_text(
                json.dumps(l2_view, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            unlinked = json.loads((out_root / "unlinked_l1_report.json").read_text(encoding="utf-8"))
            unlinked["unlinked_objects"].pop(0)
            unlinked["unlinked_objects"].append(
                {
                    "obj_id": obj_id,
                    "meeting_id": "0429",
                    "importance": 0.82,
                    "reason": "forced_overlap",
                    "review_required": True,
                }
            )
            (out_root / "unlinked_l1_report.json").write_text(
                json.dumps(unlinked, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            report = validate_l2_view_outputs(
                share_mem_root=share_root,
                root=out_root,
                out=validation_out,
            )

            issue_codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("index_obj_missing_from_view_node", issue_codes)
            self.assertIn("unlinked_obj_also_indexed", issue_codes)
            self.assertIn("l1_missing_from_l2_outputs", issue_codes)

    def test_assignment_rules_cover_early_grace_l2_directions(self) -> None:
        cases = [
            (
                {
                    "obj_id": "L1-0307-003",
                    "type": "decision",
                    "importance": 0.72,
                    "content": 'Implement dynamic time tracking, where "this meeting" updates to "one week ago".',
                    "evidence": "Meeting ID references are updated when the item is mentioned again.",
                },
                "memory update semantics",
            ),
            (
                {
                    "obj_id": "L1-0307-023",
                    "type": "approach_change",
                    "importance": 0.78,
                    "content": "The goal is not full paper replication but a minimum viable architecture that demonstrates different agent behavior and perception.",
                    "evidence": "Show the added value of long-term memory rather than copying the whole paper.",
                },
                "project demo strategy",
            ),
            (
                {
                    "obj_id": "L1-0307-029",
                    "type": "open_issue",
                    "importance": 0.72,
                    "content": "A key challenge is evaluating the memory-enhanced agent and proving its superiority over a standard LLM.",
                    "evidence": "The surrounding transcript also mentions 取用 and memory retrieval, but the object itself is an evaluation issue.",
                },
                "memory evaluation strategy",
            ),
            (
                {
                    "obj_id": "L1-0429-181",
                    "type": "open_issue",
                    "importance": 0.73,
                    "content": "The memory update process may duplicate the same core idea into multiple memory nodes, such as adding Precision/Recall to unrelated nodes.",
                    "evidence": "The update function needs constraints so only the correct memory node is updated.",
                },
                "memory update semantics",
            ),
            (
                {
                    "obj_id": "L1-0307-014",
                    "type": "open_issue",
                    "importance": 0.69,
                    "content": "The integration between short-term memory, which holds the last three sessions, and long-term memory remains undefined.",
                    "evidence": "STM and LTM need a clear interaction contract.",
                },
                "stm ltm integration",
            ),
            (
                {
                    "obj_id": "L1-0307-015",
                    "type": "open_issue",
                    "importance": 0.66,
                    "content": "The retrieve phase has not been designed, and recalling information beyond three sessions requires a distance definition.",
                    "evidence": "Retrieval is harder than updating because memory structure affects what can be recalled.",
                },
                "memory retrieval",
            ),
            (
                {
                    "obj_id": "L1-0307-050",
                    "type": "argument",
                    "importance": 0.78,
                    "content": "The Memory system output is fragmented and simplistic, and missing relationship logs cause information to be skipped.",
                    "evidence": "The extracted memory is too fragmented and many records are omitted.",
                },
                "data fragmentation",
            ),
        ]

        for obj, expected_label in cases:
            with self.subTest(obj_id=obj["obj_id"]):
                assignment = choose_l2_assignment(obj)
                self.assertEqual("assign_l2", assignment["action"])
                self.assertEqual(expected_label, assignment["l2_label"])

    def test_assignment_rejects_incidental_related_topic_labels(self) -> None:
        cases = [
            {
                "obj_id": "L1-admin-001",
                "type": "decision",
                "importance": 0.82,
                "content": "The Academia Sinica internship application needs a resume and transcript.",
                "related_topics": ["academia sinica internship"],
            },
            {
                "obj_id": "L1-admin-002",
                "type": "action_item",
                "importance": 0.71,
                "content": "Lab expenses paid by personal credit card are reimbursable.",
                "related_topics": ["expense reimbursement"],
            },
            {
                "obj_id": "L1-incidental-001",
                "type": "finding",
                "importance": 0.73,
                "content": "This is a data quality finding label, but the object does not describe a long-term memory direction.",
                "related_topics": ["data quality finding"],
            },
        ]

        for obj in cases:
            with self.subTest(obj_id=obj["obj_id"]):
                assignment = choose_l2_assignment(obj)
                self.assertEqual("skip_l1", assignment["action"])


if __name__ == "__main__":
    unittest.main()
