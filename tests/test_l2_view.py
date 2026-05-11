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
    normalized_l2_candidates_from_related_topics,
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
            self.assertTrue((out_root / "l2_secondary_links.json").exists())
            self.assertTrue((out_root / "manifest.json").exists())
            self.assertTrue((out_root / "unlinked_l1_report.json").exists())
            self.assertTrue((out_root / "l2_assignment_review_report.json").exists())
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
            architecture_node = next(
                node
                for node in load_l2_view(out_root)["l2_nodes"]
                if node["l2_id"] == "L2-memory-processing-architecture"
            )
            self.assertNotIn("This L2 topic has", architecture_node["current_state"])
            self.assertIn("Hierarchical memory processing", architecture_node["current_state"])
            self.assertIn("evolution_summary", architecture_node)
            self.assertIn("latest_position", architecture_node)
            self.assertIn("representative_l1_ids", architecture_node)
            unlinked = json.loads((out_root / "unlinked_l1_report.json").read_text(encoding="utf-8"))
            self.assertIn("L1-0318-002", {item["obj_id"] for item in unlinked["unlinked_objects"]})
            review = json.loads(
                (out_root / "l2_assignment_review_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(review["source_l1_count"], 8)
            self.assertEqual(review["linked_l1_count"], manifest["linked_l1_count"])
            self.assertIn("review_items", review)
            self.assertIn("topic_summaries", review)

    def test_build_l2_view_writes_secondary_links_without_changing_primary_l2(self) -> None:
        tree = {
            "tree_version": 3,
            "last_updated_utc": "2026-05-09T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                {
                    "meeting_id": "0429",
                    "timestamp": "2026-04-29T00:00:00Z",
                    "meeting_date": "2026-04-29",
                    "source_file": "0429.txt",
                    "phase_id": "",
                    "memory_objects": [
                        _obj(
                            "L1-baseline",
                            "argument",
                            "RAG baseline comparison should include full transcript and token cost.",
                            importance=0.76,
                            topics=["rag baseline"],
                        ),
                        _obj(
                            "L1-cross-topic",
                            "argument",
                            "L1 L2 L3 hierarchy explains layered context for long-term memory.",
                            importance=0.79,
                            topics=["long term memory architecture", "rag baseline"],
                        ),
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            out_root = Path(tmp) / "long_term" / "l2"
            refresh_share_mem_outputs(root=share_root, tree=tree, source_transcript_dir=Path(tmp))

            manifest = build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            l2_index = load_l2_index(out_root)
            self.assertEqual(
                l2_index["L1-cross-topic"]["l2_label"],
                "memory processing architecture",
            )
            secondary = json.loads((out_root / "l2_secondary_links.json").read_text(encoding="utf-8"))
            bridge_targets = {
                row["secondary_l2_label"]
                for row in secondary["links"]
                if row["obj_id"] == "L1-cross-topic"
            }
            self.assertIn("retrieval baseline comparison", bridge_targets)
            self.assertGreaterEqual(manifest["secondary_l2_link_count"], 1)

    def test_clean_l2_view_does_not_delete_l1_research_logs_when_roots_share_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            refresh_share_mem_outputs(root=share_root, tree=_tree(), source_transcript_dir=Path(tmp))
            l1_log = share_root / "research_logs" / "run" / "api_calls" / "api_calls.jsonl"
            l2_log = share_root / "l2_research_logs" / "old" / "debug.json"
            l1_log.parent.mkdir(parents=True)
            l2_log.parent.mkdir(parents=True)
            l1_log.write_text('{"stage":"l1"}\n', encoding="utf-8")
            l2_log.write_text("{}", encoding="utf-8")

            build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=share_root,
                mode="deterministic",
                clean=True,
            )

            self.assertTrue(l1_log.exists())
            self.assertFalse(l2_log.exists())

    def test_l2_view_keeps_l2_as_topic_layer_not_l1_types(self) -> None:
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
            self.assertIn("transcript segmentation and idea-unit coverage", labels)
            self.assertNotIn("decision", labels)
            self.assertNotIn("design decision", labels)

    def test_related_topics_are_normalized_into_l2_candidates(self) -> None:
        obj = _obj(
            "L1-topic-001",
            "finding",
            "The object only carries topic hints here.",
            topics=[
                "Memory_Retrieval",
                "long-term memory architecture",
                "decision",
                "data",
                "  Evaluation Methodology  ",
            ],
        )

        candidates = normalized_l2_candidates_from_related_topics(obj)

        self.assertEqual(
            [
                (row["label"], row["normalized_topic"], row["specificity"])
                for row in candidates
            ],
            [
                ("memory retrieval", "memory retrieval", "specific"),
                (
                    "memory processing architecture",
                    "long term memory architecture",
                    "broad",
                ),
                ("memory evaluation strategy", "evaluation methodology", "specific"),
            ],
        )

    def test_reviewed_related_topic_aliases_cover_l1_taxonomy_and_workflow(self) -> None:
        cases = [
            (
                ["memory object model", "definitions", "memory item structure"],
                "l1 taxonomy and type agents",
            ),
            (["code_architecture", "development_strategy"], "agentic pipeline control"),
            (["memory update mechanism", "memory management"], "memory update semantics"),
            (["importance", "human-computer interaction"], "memory lifecycle"),
            (["speaker diarization", "experimental design"], "dataset selection"),
        ]

        for topics, expected_label in cases:
            with self.subTest(topics=topics):
                obj = _obj(
                    "L1-reviewed-alias",
                    "decision",
                    "The object only carries reviewed related topic aliases.",
                    importance=0.74,
                    topics=topics,
                )

                assignment = choose_l2_assignment(obj)

                self.assertEqual("assign_l2", assignment["action"])
                self.assertEqual(expected_label, assignment["l2_label"])

    def test_operational_constraints_are_durable_when_about_retrieval_budget(self) -> None:
        obj = _obj(
            "L1-operational-budget",
            "decision",
            (
                "The API budget and operational constraints topic is now treated as "
                "a durable design constraint because offline eval, context token count, "
                "p95 retrieval latency, and no-LLM runs determine whether the memory "
                "retrieval system can scale."
            ),
            importance=0.77,
            topics=[],
        )

        assignment = choose_l2_assignment(obj)

        self.assertEqual("assign_l2", assignment["action"])
        self.assertEqual("operational constraints and resource budget", assignment["l2_label"])

    def test_admin_api_budget_discussion_still_skips_l2(self) -> None:
        obj = _obj(
            "L1-admin-api-budget",
            "finding",
            "The team briefly discussed API usage reimbursement and lab administration billing details.",
            importance=0.71,
            topics=["lab_administration", "expense_reimbursement"],
        )

        assignment = choose_l2_assignment(obj)

        self.assertEqual("skip_l1", assignment["action"])
        self.assertEqual("administrative_or_local_context", assignment["reason"])

    def test_specific_concrete_topic_beats_cross_cutting_evidence_anchor(self) -> None:
        obj = _obj(
            "L1-specific-over-evidence-anchor",
            "finding",
            (
                "Missing-line coverage repair should keep evidence anchors and line "
                "coverage, but the durable topic is transcript segmentation rather "
                "than the cross-cutting evidence anchor."
            ),
            importance=0.74,
            topics=["source linkage", "missing-line coverage and repair"],
        )

        assignment = choose_l2_assignment(obj)

        self.assertEqual("assign_l2", assignment["action"])
        self.assertEqual("transcript segmentation and idea-unit coverage", assignment["l2_label"])

    def test_retrieval_baseline_comparison_is_a_durable_l2_topic(self) -> None:
        obj = _obj(
            "L1-baseline-comparison",
            "argument",
            (
                "The team proposes comparing ordinary RAG with the layered memory "
                "system and full-context baseline, including token cost and retrieved "
                "evidence traceability."
            ),
            topics=[
                "RAG and full-context baseline comparison",
                "rag_baseline",
                "traditional RAG",
                "full context",
                "retrieval evaluation",
                "token cost",
            ],
            importance=0.7,
        )

        assignment = choose_l2_assignment(obj)

        self.assertEqual(assignment["action"], "assign_l2")
        self.assertEqual(assignment["l2_label"], "retrieval baseline comparison")

    def test_memo_rag_multihop_tradeoff_stays_memory_evaluation(self) -> None:
        obj = _obj(
            "L1-memo-rag",
            "finding",
            (
                "MEMO did not outperform the RAG baseline on multi-hop questions, "
                "so the team needs LLM-as-judge evaluation and ground-truth checks."
            ),
            topics=["rag_baseline", "MEMO", "multi-hop evaluation"],
            importance=0.74,
        )

        assignment = choose_l2_assignment(obj)

        self.assertEqual(assignment["action"], "assign_l2")
        self.assertEqual(assignment["l2_label"], "memory evaluation strategy")

    def test_related_topic_seed_takes_priority_over_content_rule_when_specific(self) -> None:
        obj = _obj(
            "L1-topic-002",
            "open_issue",
            "The architecture discussion mentions L2 and L3, but the extracted topic says this is mainly retrieval.",
            importance=0.74,
            topics=["memory_retrieval"],
        )

        assignment = choose_l2_assignment(obj)

        self.assertEqual(assignment["action"], "assign_l2")
        self.assertEqual(assignment["l2_label"], "memory retrieval")
        self.assertEqual(assignment["reason"], "related_topic_seed")

    def test_freeform_related_topics_are_opt_in_for_new_domains(self) -> None:
        obj = _obj(
            "L1-campus-energy-001",
            "open_issue",
            "The campus energy idea unit discussion focuses on meter calibration drift.",
            importance=0.74,
            topics=[
                "meter calibration drift",
                "energy data and sensor pipeline",
                "電表校正漂移",
                "open_issue",
                "synthetic campus energy",
            ],
        )

        default_assignment = choose_l2_assignment(obj)
        freeform_assignment = choose_l2_assignment(
            obj,
            allow_freeform_related_topics=True,
        )

        self.assertNotEqual("meter calibration drift", default_assignment.get("l2_label"))
        self.assertEqual("assign_l2", freeform_assignment["action"])
        self.assertEqual("meter calibration drift", freeform_assignment["l2_label"])
        self.assertEqual("related_topic_seed", freeform_assignment["reason"])

    def test_content_rule_refines_broad_related_topic_seed(self) -> None:
        obj = _obj(
            "L1-topic-003",
            "finding",
            "Prompts should be self-contained and avoid project jargon so the agent understands them.",
            importance=0.72,
            topics=["system architecture", "development workflow"],
        )

        assignment = choose_l2_assignment(obj)

        self.assertEqual(assignment["action"], "assign_l2")
        self.assertEqual(assignment["l2_label"], "prompt design and instruction quality")
        self.assertEqual(assignment["reason"], "related_topic_seed_content_refined")

    def test_assignment_rules_cover_current_chinese_l1_regressions(self) -> None:
        cases = [
            (
                _obj(
                    "L1-0307-006",
                    "open_issue",
                    "在 Demo 中如何清楚地識別被更新的記憶項目是一個問題，這點引起了與會者的疑問。",
                    importance=0.54,
                    topics=["memory update", "demo", "ui"],
                ),
                "memory update semantics",
            ),
            (
                _obj(
                    "L1-0408-030",
                    "argument",
                    (
                        "應讓 LLM 透過 function calling 來決定要查詢短期記憶或長期記憶，"
                        "而非使用固定的系統規則。理由是，選擇記憶體的決策邏輯本身很複雜，"
                        "LLM 能夠處理更細微的查詢，甚至執行多步驟檢索（例如先查 LTM 再查 STM）。"
                    ),
                    importance=0.62,
                    topics=[
                        "agent architecture",
                        "retrieval strategy",
                        "function calling",
                        "short-term memory",
                        "long-term memory",
                    ],
                ),
                "memory retrieval",
            ),
            (
                _obj(
                    "L1-0506-029",
                    "finding",
                    (
                        "長期記憶系統採用三層級結構：L1 是基礎記憶單元，L2 是對 L1 節點的摘要，"
                        "L3 是所有上下文的最高層級摘要。"
                    ),
                    importance=0.62,
                    topics=[
                        "long-term memory",
                        "l1 memory",
                        "l2 memory",
                        "l3 memory",
                        "memory architecture",
                        "hierarchical memory",
                    ],
                ),
                "memory processing architecture",
            ),
            (
                _obj(
                    "L1-0506-038",
                    "finding",
                    (
                        "每個 L1 節點由一組參數描述，包括「importance」、「activation」、"
                        "「relevance」（用於檢索的語義相似度）和「recency」（一個會隨時間衰減的值）。"
                    ),
                    importance=0.65,
                    topics=[
                        "l1 memory",
                        "data structure",
                        "memory model",
                        "importance score",
                        "activation score",
                    ],
                ),
                "memory lifecycle",
            ),
            (
                _obj(
                    "L1-0429-127",
                    "proposal",
                    (
                        "提出一項設計原則：為避免記憶節點因內容過於相似而收斂，"
                        "系統應避免使用單一、未分化的大塊文本來更新多個相關的記憶節點。"
                    ),
                    importance=0.61,
                    topics=["memory update", "data quality", "chunking strategy", "idea units"],
                ),
                "transcript segmentation and idea-unit coverage",
            ),
        ]

        for obj, expected_label in cases:
            with self.subTest(obj_id=obj["obj_id"]):
                assignment = choose_l2_assignment(obj)
                self.assertEqual("assign_l2", assignment["action"])
                self.assertEqual(expected_label, assignment["l2_label"])

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

    def test_validate_l2_view_does_not_warn_for_administrative_unlinked(self) -> None:
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

            unlinked = json.loads((out_root / "unlinked_l1_report.json").read_text(encoding="utf-8"))
            unlinked["unlinked_objects"].append(
                {
                    "obj_id": "L1-admin-budget",
                    "meeting_id": "0429",
                    "importance": 0.82,
                    "reason": "administrative_or_local_context",
                    "review_required": False,
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

            high_unlinked = [
                issue
                for issue in report["issues"]
                if issue["code"] == "high_importance_unlinked"
                and issue.get("obj_id") == "L1-admin-budget"
            ]
            self.assertEqual([], high_unlinked)

    def test_validate_l2_view_suppresses_large_warning_for_materialized_l3(self) -> None:
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
            l2_index = load_l2_index(out_root)
            source_obj_id = next(iter(l2_index))
            source_l2_id = l2_index[source_obj_id]["l2_id"]
            for node in l2_view["l2_nodes"]:
                if node["l2_id"] == source_l2_id:
                    node["linked_obj_ids"] = [source_obj_id] * 61
                    break
            (out_root / "l2_view.json").write_text(
                json.dumps(l2_view, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            l3_root = out_root.parent / "l3"
            l3_root.mkdir(parents=True, exist_ok=True)
            (l3_root / "l3_view.json").write_text(
                json.dumps(
                    {
                        "l3_nodes": [
                            {
                                "l3_id": "L3-promoted",
                                "promoted_from_l2_id": source_l2_id,
                                "child_l2_nodes": [
                                    {"l2_id": "L2-child-a"},
                                    {"l2_id": "L2-child-b"},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            report = validate_l2_view_outputs(
                share_mem_root=share_root,
                root=out_root,
                out=validation_out,
            )

            large_warnings = [
                issue
                for issue in report["issues"]
                if issue["code"] == "large_l2_topic" and issue.get("l2_id") == source_l2_id
            ]
            self.assertEqual([], large_warnings)
            self.assertEqual(report["resolved_large_l2_promotion_count"], 1)

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

    def test_validate_l2_view_flags_known_topic_assignment_regression(self) -> None:
        tree = {
            "tree_version": 3,
            "last_updated_utc": "2026-05-09T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
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
                            "The system will continue to use a fixed chunk size of approximately 20 lines for processing transcripts.",
                            importance=0.69,
                            topics=["model_configuration", "memory_system_implementation", "data_management"],
                        )
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            out_root = Path(tmp) / "long_term" / "l2"
            validation_out = out_root / "validation"
            refresh_share_mem_outputs(root=share_root, tree=tree, source_transcript_dir=Path(tmp))
            build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            l2_index = load_l2_index(out_root)
            l2_index["L1-0429-025"]["l2_label"] = "data fragmentation"
            l2_index["L1-0429-025"]["l2_id"] = "L2-data-fragmentation"
            (out_root / "l2_index.json").write_text(
                json.dumps(l2_index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            report = validate_l2_view_outputs(
                share_mem_root=share_root,
                root=out_root,
                out=validation_out,
            )

            issue_codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("expected_l2_assignment_mismatch", issue_codes)

    def test_validate_l2_view_skips_known_assignment_when_live_rerun_obj_id_drifted(self) -> None:
        tree = {
            "tree_version": 3,
            "last_updated_utc": "2026-05-09T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                {
                    "meeting_id": "0429",
                    "timestamp": "2026-04-29T00:00:00Z",
                    "meeting_date": "2026-04-29",
                    "source_file": "meeting_recording/transcript/grace/0429.txt",
                    "phase_id": "",
                    "memory_objects": [
                        _obj(
                            "L1-0429-025",
                            "approach_change",
                            "A fade in/out mechanism for memory activation will move old or unimportant ideas to inactive state and reactivate them later.",
                            importance=0.8,
                            topics=["memory lifecycle", "activation decay"],
                        )
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            out_root = Path(tmp) / "long_term" / "l2"
            validation_out = out_root / "validation"
            refresh_share_mem_outputs(root=share_root, tree=tree, source_transcript_dir=Path(tmp))
            build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            report = validate_l2_view_outputs(
                share_mem_root=share_root,
                root=out_root,
                out=validation_out,
            )

            issue_codes = {issue["code"] for issue in report["issues"]}
            self.assertNotIn("expected_l2_assignment_mismatch", issue_codes)

    def test_validate_l2_view_skips_expected_assignment_when_object_specific_anchor_does_not_match(self) -> None:
        tree = {
            "tree_version": 3,
            "last_updated_utc": "2026-05-09T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                {
                    "meeting_id": "0429",
                    "timestamp": "2026-04-29T00:00:00Z",
                    "meeting_date": "2026-04-29",
                    "source_file": "meeting_recording/transcript/grace/0429.txt",
                    "phase_id": "",
                    "memory_objects": [
                        _obj(
                            "L1-0429-059",
                            "decision",
                            (
                                "The project will treat forgetting in current AI agents as "
                                "deleting data from an external RAG database rather than "
                                "changing the core LLM weights."
                            ),
                            importance=0.73,
                            topics=["memory lifecycle", "RAG"],
                        )
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            out_root = Path(tmp) / "long_term" / "l2"
            validation_out = out_root / "validation"
            refresh_share_mem_outputs(root=share_root, tree=tree, source_transcript_dir=Path(tmp))
            build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            report = validate_l2_view_outputs(
                share_mem_root=share_root,
                root=out_root,
                out=validation_out,
            )

            issue_codes = {issue["code"] for issue in report["issues"]}
            self.assertNotIn("expected_l2_assignment_mismatch", issue_codes)

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
            (
                {
                    "obj_id": "L1-0429-025",
                    "type": "proposal",
                    "importance": 0.69,
                    "content": "The system will continue to use a fixed chunk size of approximately 20 lines for processing transcripts. This arbitrary initial value was retained because its performance was acceptable and downstream object structuring can handle multiple topics within one chunk.",
                    "related_topics": ["model_configuration", "memory_system_implementation", "data_management"],
                },
                "transcript segmentation and idea-unit coverage",
            ),
            (
                {
                    "obj_id": "L1-0506-009",
                    "type": "open_issue",
                    "importance": 0.68,
                    "content": "The current idea unit extraction process sometimes misses transcript lines, creating gaps that are captured as low-quality raw text. A future prompt version is expected to include a repair mechanism to merge these gaps.",
                    "related_topics": ["data handling", "output quality", "memory system implementation"],
                },
                "transcript segmentation and idea-unit coverage",
            ),
            (
                {
                    "obj_id": "L1-0318-002",
                    "type": "open_issue",
                    "importance": 0.6,
                    "content": "The LOCOMO evaluation did not test unanswerable questions, leaving a gap in evaluating whether the model can handle queries that cannot be answered from context.",
                    "related_topics": ["evaluation"],
                },
                "memory evaluation strategy",
            ),
            (
                {
                    "obj_id": "L1-0325-002",
                    "type": "finding",
                    "importance": 0.69,
                    "content": "Raw recording data will be persistently stored, and extracted memory objects will serve as summaries or indexes that link back to the original source material.",
                    "related_topics": ["source linkage"],
                },
                "memory evidence anchoring",
            ),
            (
                {
                    "obj_id": "L1-0325-003",
                    "type": "argument",
                    "importance": 0.67,
                    "content": "Memory objects will link to specific audio timestamps, enabling the agent to play back the original recording segment. This approach is preferred because users can inspect the source.",
                    "related_topics": ["source linkage", "audio timestamp"],
                },
                "memory evidence anchoring",
            ),
            (
                {
                    "obj_id": "L1-0325-004",
                    "type": "open_issue",
                    "importance": 0.63,
                    "content": "A design decision is needed on whether the source link in a memory object should point to a transcript chunk or a specific timestamp in the audio/video file.",
                    "related_topics": ["memory architecture", "memory retrieval"],
                },
                "memory evidence anchoring",
            ),
            (
                {
                    "obj_id": "L1-0325-018",
                    "type": "action_item",
                    "importance": 0.74,
                    "content": "To address the difficulty of verifying the AI's memory recall from real meeting data, retrieve the original meeting segment and manually assess its relevance to the current discussion.",
                    "related_topics": ["research_methodology", "memory retrieval"],
                },
                "memory evidence anchoring",
            ),
            (
                {
                    "obj_id": "L1-0325-019",
                    "type": "argument",
                    "importance": 0.72,
                    "content": "The difficulty in verifying AI recalled memories can be mitigated by a manual verification process where the original meeting segment is retrieved and its relevance is assessed.",
                    "related_topics": ["research_methodology", "memory retrieval"],
                },
                "memory evidence anchoring",
            ),
            (
                {
                    "obj_id": "L1-0408-052",
                    "type": "approach_change",
                    "importance": 0.87,
                    "content": "Future implementation should preprocess meeting records into finer-grained units such as sentences or ideas instead of extracting from the whole transcript, enabling more precise memory updates.",
                    "related_topics": ["data handling"],
                },
                "transcript segmentation and idea-unit coverage",
            ),
            (
                {
                    "obj_id": "L1-0506-041",
                    "type": "proposal",
                    "importance": 0.7,
                    "content": "Two competing memory hierarchy models are being considered: a time-based model creates new L1 nodes for each mention, while a topic-based model organizes nodes by topic and keeps topic history.",
                    "related_topics": ["memory hierarchy"],
                },
                "memory processing architecture",
            ),
            (
                {
                    "obj_id": "L1-0429-139",
                    "type": "open_issue",
                    "importance": 0.67,
                    "content": "A key design issue was raised regarding the proposed manager-agent architecture: because the process is sequential and the manager waits for each agent response, it is unclear why a separate agent is necessary.",
                    "related_topics": ["system architecture"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0506-024",
                    "type": "approach_change",
                    "importance": 0.65,
                    "content": "A verification workflow was introduced that records each agent step's full prompt and returned result so each input and output can be traced and checked before continuing.",
                    "related_topics": ["development workflow"],
                },
                "pipeline observability and validation",
            ),
            (
                {
                    "obj_id": "L1-0506-038",
                    "type": "open_issue",
                    "importance": 0.65,
                    "content": "The design of a human-in-the-loop system for tuning memory node importance remains open, including how users inspect and adjust scores and how the system suggests related units for tuning.",
                    "related_topics": ["memory lifecycle"],
                },
                "memory lifecycle",
            ),
            (
                {
                    "obj_id": "L1-0307-005",
                    "type": "proposal",
                    "importance": 0.64,
                    "content": "建議實現動態時間追蹤，讓項目的時間參考（例如「本次會議」）在下週會議中自動更新為「一週前」。",
                    "related_topics": ["memory model", "temporal references"],
                },
                "memory update semantics",
            ),
            (
                {
                    "obj_id": "L1-0429-145",
                    "type": "approach_change",
                    "importance": 0.83,
                    "content": "The system architecture will be refactored from a monolithic process to a manager-agent model. A central manager will act as a pure dispatcher, delegating tasks like identifying idea units and updating memory to specialized worker agents via tool calling.",
                    "related_topics": ["system_architecture", "development_workflow"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0506-040",
                    "type": "approach_change",
                    "importance": 0.78,
                    "content": "The long-term memory system will use a three-tier hierarchical structure: L1 nodes are fine-grained idea units, L2 nodes summarize blocks of L1s, and L3 nodes provide the highest-level summary.",
                    "related_topics": ["long-term memory architecture", "memory system architecture"],
                },
                "memory processing architecture",
            ),
            (
                {
                    "obj_id": "L1-0506-036",
                    "type": "decision",
                    "importance": 0.73,
                    "content": "To assist with human-in-the-loop tuning, the system uses similarity search to find and suggest related idea units for a potential importance increase when a user adjusts a given unit.",
                    "related_topics": ["memory lifecycle", "memory_retrieval"],
                },
                "memory lifecycle",
            ),
            (
                {
                    "obj_id": "L1-0325-061",
                    "type": "approach_change",
                    "importance": 0.67,
                    "content": "An initial filtering step is now required before the Retriever can be used, modifying the data retrieval process.",
                    "related_topics": ["retrieval phase", "memory retrieval"],
                },
                "memory retrieval",
            ),
            (
                {
                    "obj_id": "L1-0429-107",
                    "type": "open_issue",
                    "importance": 0.64,
                    "content": 'The current single-prompt, "black box" approach is uncontrollable and unobservable. The model fails to follow instructions, and intermediate outputs cannot be inspected. This raises whether to switch to a more controllable multi-step process, such as sequential prompts or external programming.',
                    "related_topics": ["system_architecture", "development_workflow"],
                },
                "pipeline observability and validation",
            ),
            (
                {
                    "obj_id": "L1-0408-036",
                    "type": "open_issue",
                    "importance": 0.67,
                    "content": "需要為代理建立「短期記憶」和「長期記憶」的定義，因為它們與人類記憶不同。",
                    "related_topics": ["STM-LTM_integration", "short-term memory"],
                },
                "stm ltm integration",
            ),
            (
                {
                    "obj_id": "L1-0429-004",
                    "type": "open_issue",
                    "importance": 0.66,
                    "content": "A concern was raised about whether the accumulated 180 minutes of meeting data is sufficient for the planned large language model experiments.",
                    "related_topics": ["dataset", "dataset_selection", "research_methodology"],
                },
                "dataset selection",
            ),
            (
                {
                    "obj_id": "L1-0307-012",
                    "type": "action_item",
                    "importance": 0.58,
                    "content": "團隊評估了一篇關於「長期記憶」的外部論文，並決定其方法不適用，因為它過於細粒度，且專注於單次會話內的長上下文處理，而非團隊所需的跨時間線資訊追蹤。",
                    "related_topics": ["long-term memory", "alternative approaches"],
                },
                "research methodology",
            ),
            (
                {
                    "obj_id": "L1-0307-047",
                    "type": "open_issue",
                    "importance": 0.69,
                    "content": "「Memory」系統的輸出被認為過於零碎和簡單，部分原因可能是系統在找不到關聯時未能記錄資訊。",
                    "related_topics": ["Memory system", "output quality", "Data fragmentation"],
                },
                "data fragmentation",
            ),
            (
                {
                    "obj_id": "L1-0408-004",
                    "type": "argument",
                    "importance": 0.62,
                    "content": "該資料集適合本專案，因為它之前已被用於 ASR 和會議摘要等相關 NLP 任務，且會議中由同一組人持續討論同一主題，這證明了其品質和追蹤長期資訊的適用性。",
                    "related_topics": ["dataset", "dataset_selection", "research methodology"],
                },
                "dataset selection",
            ),
            (
                {
                    "obj_id": "L1-0408-017",
                    "type": "proposal",
                    "importance": 0.56,
                    "content": "建議將從逐字稿中提取的記憶類別設計為可由使用者配置的參數，讓使用者能自行定義需要追蹤的重要資訊類型。",
                    "related_topics": ["memory system implementation"],
                },
                "memory system implementation",
            ),
            (
                {
                    "obj_id": "L1-0408-030",
                    "type": "open_issue",
                    "importance": 0.67,
                    "content": "The central unresolved architectural question is how the mentor agent should retrieve information from its memory stores and decide whether to access short-term or long-term memory.",
                    "related_topics": ["STM-LTM_integration", "memory_retrieval"],
                },
                "memory retrieval",
            ),
            (
                {
                    "obj_id": "L1-0408-041",
                    "type": "decision",
                    "importance": 0.67,
                    "content": "提議一種基於查詢內容的規則來決定使用哪種記憶體。例如包含「上週的待辦事項」等近期時間詞的查詢將明確指向短期記憶體。",
                    "related_topics": ["memory retrieval", "STM-LTM integration"],
                },
                "memory retrieval",
            ),
            (
                {
                    "obj_id": "L1-0408-043",
                    "type": "argument",
                    "importance": 0.67,
                    "content": "預設工作流程應先搜尋包含所有資訊但解析度較低的長期記憶體，然後再放大到相關的高解析度短期記憶體，除非查詢明確針對近期時間範圍。",
                    "related_topics": ["memory retrieval", "long-term memory", "short-term memory"],
                },
                "memory retrieval",
            ),
            (
                {
                    "obj_id": "L1-0429-033",
                    "type": "approach_change",
                    "importance": 0.65,
                    "content": "系統處理逐字稿時採用固定、非動態的約20行文本區塊。此區塊大小為初始的任意設定，因性能可接受而沿用至今。",
                    "related_topics": ["data handling", "data management"],
                },
                "transcript segmentation and idea-unit coverage",
            ),
            (
                {
                    "obj_id": "L1-0429-037",
                    "type": "open_issue",
                    "importance": 0.64,
                    "content": "需要確定最有效的文本分割策略來處理會議記錄。現有固定大小的區塊準確性不足，團隊提出新的動態分塊方法，但其性能和權衡仍未知。",
                    "related_topics": ["data_management", "experimental_setup"],
                },
                "transcript segmentation and idea-unit coverage",
            ),
            (
                {
                    "obj_id": "L1-0429-058",
                    "type": "proposal",
                    "importance": 0.65,
                    "content": "提出一個評估計劃，包含短期正確性、長期演變和決策推理三種類型的問題，並透過與標準答案比對來衡量正確性。",
                    "related_topics": ["research_methodology", "memory_system_performance"],
                },
                "memory evaluation strategy",
            ),
            (
                {
                    "obj_id": "L1-0429-059",
                    "type": "proposal",
                    "importance": 0.65,
                    "content": "為了解決數據不足的問題，提出兩種數據增強策略：使用大型語言模型人工擴展現有對話，或整合其他學生的會議記錄以創建更豐富的縱向數據集。",
                    "related_topics": ["dataset_acquisition", "research_methodology"],
                },
                "dataset selection",
            ),
            (
                {
                    "obj_id": "L1-0429-127",
                    "type": "argument",
                    "importance": 0.65,
                    "content": "反對 LLM 主導控制流程的一個論點是，簡單的狀態管理會變得複雜且脆弱，因為這需要透過 prompt 明確指示 LLM 來處理。",
                    "related_topics": ["system_architecture", "implementation_strategy"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0506-013",
                    "type": "approach_change",
                    "importance": 0.65,
                    "content": "A new guideline for prompt engineering was adopted: prompts should be more generic and avoid internal project jargon such as L1 agent.",
                    "related_topics": ["development workflow", "model configuration"],
                },
                "prompt design and instruction quality",
            ),
            (
                {
                    "obj_id": "L1-0506-006",
                    "type": "finding",
                    "importance": 0.62,
                    "content": "Prepare a slide deck of all important prompts for presentations and refine them to be more generic, avoiding internal jargon.",
                    "related_topics": ["development workflow", "model configuration"],
                },
                "prompt design and instruction quality",
            ),
            (
                {
                    "obj_id": "L1-0318-003",
                    "type": "proposal",
                    "importance": 0.65,
                    "content": "To address the risk of error propagation and lack of global context in sequential agent processing, a shared blackboard architecture is suggested as an alternative approach.",
                    "related_topics": ["system architecture", "alternative approaches"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0408-054",
                    "type": "action_item",
                    "importance": 0.7,
                    "content": "Formally define the long-term memory architecture, including its update rules and the relationships between memory stores, and then conduct an experiment to prove its value.",
                    "related_topics": ["long-term memory architecture", "STM-LTM integration"],
                },
                "memory processing architecture",
            ),
            (
                {
                    "obj_id": "L1-0506-028",
                    "type": "argument",
                    "importance": 0.61,
                    "content": "由於系統平行地將 idea units 發送給多個專門的 agent，同一個 idea unit 可能會被多個 agent 捕獲，從而產生重複的 candidate，後續需要比對、區分或合併。",
                    "related_topics": ["memory system architecture", "development workflow"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0506-029",
                    "type": "proposal",
                    "importance": 0.55,
                    "content": "提議一種用於組織對話內容的層級式資料結構：idea units、segments、topics，topics 是相關主題或 segment 的更高級別分組。",
                    "related_topics": ["data handling", "memory architecture"],
                },
                "l2 topic grouping",
            ),
            (
                {
                    "obj_id": "L1-0506-032",
                    "type": "finding",
                    "importance": 0.6,
                    "content": "確立了資料的層級結構：最底層是 idea units，多個相關的 idea units 組成 segment，而多個 segment 可歸於一個更大的 topic 之下。",
                    "related_topics": ["memory system architecture", "data handling"],
                },
                "l2 topic grouping",
            ),
            (
                {
                    "obj_id": "L1-0422-015",
                    "type": "proposal",
                    "importance": 0.52,
                    "content": "提出一個假設機制：系統首先將句子分組，如果這些組構成一個單一的想法單元，則將其合併，並可能檢查遠處區塊的關係，以創建可變大小的輸出。",
                    "related_topics": ["data handling"],
                },
                "transcript segmentation and idea-unit coverage",
            ),
            (
                {
                    "obj_id": "L1-0429-032",
                    "type": "approach_change",
                    "importance": 0.71,
                    "content": "系統採用由物件（Objects）和議題（Issues）組成的兩層式架構來追蹤重複出現的話題。一個物件可以連結到多個議題。",
                    "related_topics": ["memory system architecture"],
                },
                "l2 topic grouping",
            ),
            (
                {
                    "obj_id": "L1-0422-046",
                    "type": "argument",
                    "importance": 0.62,
                    "content": "保留短期記憶（STM）而非將所有資訊統一存入長期記憶（LTM）結構的理由是，較為簡潔的 LTM 可能無法保留近期互動中那些瑣碎但必要的細節。",
                    "related_topics": ["STM-LTM_integration"],
                },
                "stm ltm integration",
            ),
            (
                {
                    "obj_id": "L1-0429-057",
                    "type": "proposal",
                    "importance": 0.65,
                    "content": "提出一項新的評估標準：測試模型遺忘或淡化不相關長期資訊的能力。模型不應在對話中呈現非活躍資訊，但需保留其可檢索狀態。",
                    "related_topics": ["forgetting mechanism", "memory retrieval"],
                },
                "memory evaluation strategy",
            ),
            (
                {
                    "obj_id": "L1-0422-053",
                    "type": "argument",
                    "importance": 0.67,
                    "content": "A key demonstration of the memory system's value is its ability to fade out old, irrelevant topics so outdated information does not appear in dialogue.",
                    "related_topics": ["forgetting mechanism", "long-term memory"],
                },
                "memory lifecycle",
            ),
            (
                {
                    "obj_id": "L1-0408-057",
                    "type": "proposal",
                    "importance": 0.65,
                    "content": "提出一種基於頻率的記憶鞏固模型：當一個主題被提及達到一定次數後，就從短期記憶轉移到長期記憶。",
                    "related_topics": ["STM-LTM_integration", "forgetting mechanism"],
                },
                "stm ltm integration",
            ),
            (
                {
                    "obj_id": "L1-0506-042",
                    "type": "open_issue",
                    "importance": 0.64,
                    "content": "長期記憶系統的架構存在一個根本性的權衡：是採用基於會議時間順序的時間結構，還是採用基於語義主題的主題結構。",
                    "related_topics": ["long-term memory architecture", "memory system architecture"],
                },
                "memory processing architecture",
            ),
            (
                {
                    "obj_id": "L1-0429-101",
                    "type": "finding",
                    "importance": 0.64,
                    "content": "在短期記憶處理流程中，Gemini 根據提示自行決定讀取文本的起訖行數，但此方法導致讀取區塊重疊，團隊討論是否將控制權轉移到系統程式碼以實現可預測且無重疊的文本分塊處理。",
                    "related_topics": ["data handling", "system architecture"],
                },
                "transcript segmentation and idea-unit coverage",
            ),
        ]

        for obj, expected_label in cases:
            with self.subTest(obj_id=obj["obj_id"]):
                assignment = choose_l2_assignment(obj)
                self.assertEqual("assign_l2", assignment["action"])
                self.assertEqual(expected_label, assignment["l2_label"])

    def test_assignment_rules_cover_live_quality_sample_regressions(self) -> None:
        cases = [
            (
                {
                    "obj_id": "L1-0325-086",
                    "type": "argument",
                    "importance": 0.7,
                    "content": "簡單的 RAG 方法不足以追蹤主題的演變，例如一個主題何時被放棄以及原因。RAG 只能找到所有相關的提及，但無法捕捉到關鍵的時間順序和最終決定。",
                    "related_topics": [
                        "rag",
                        "topic lifecycle",
                        "memory retrieval",
                        "temporal reasoning",
                        "memory representation",
                        "memory system",
                        "evaluation",
                    ],
                },
                "memory lifecycle",
            ),
            (
                {
                    "obj_id": "L1-0408-044",
                    "type": "argument",
                    "importance": 0.62,
                    "content": "長期記憶的價值在於能夠追蹤專案主題隨時間的演變。例如，記錄一年中所有討論過的主題歷史，便能清晰地展示長期記憶的功用。",
                    "related_topics": [
                        "long-term memory",
                        "topic lifecycle",
                        "evaluation",
                        "agent architecture",
                    ],
                },
                "memory lifecycle",
            ),
            (
                {
                    "obj_id": "L1-0429-004",
                    "type": "finding",
                    "importance": 0.62,
                    "content": "The project's current dataset consists of approximately 180 minutes of audio from 5 meetings, but the corresponding transcripts have quality issues due to overlapping speech, requiring manual correction.",
                    "related_topics": ["LOCOMO dataset", "data-quality finding", "evaluation methodology"],
                },
                "dataset selection",
            ),
            (
                {
                    "obj_id": "L1-0429-057",
                    "type": "argument",
                    "importance": 0.62,
                    "content": "An ablation study should compare the full short-term plus long-term memory system against RAG-only, short-term-only, and long-term-only baselines.",
                    "related_topics": ["evaluation methodology", "RAG"],
                },
                "memory evaluation strategy",
            ),
            (
                {
                    "obj_id": "L1-0408-004",
                    "type": "argument",
                    "importance": 0.63,
                    "content": "The dataset is justified by prior use in academic research for Automatic Speech Recognition (ASR) and meeting summarization, indicating established value for this work.",
                    "related_topics": ["dataset_selection", "research_methodology", "benchmarking"],
                },
                "dataset selection",
            ),
            (
                {
                    "obj_id": "L1-0408-054",
                    "type": "proposal",
                    "importance": 0.72,
                    "content": "An alternative memory consolidation model based on discussion density stores a topic in long-term memory when it is discussed intensely over a short period, even if not mentioned again.",
                    "related_topics": ["long-term memory management", "memory architecture"],
                },
                "memory lifecycle",
            ),
            (
                {
                    "obj_id": "L1-0422-015",
                    "type": "argument",
                    "importance": 0.68,
                    "content": "A counter-argument against the iterative method is that a single-pass approach could group non-adjacent ideas by maintaining a global vector across generated nodes.",
                    "related_topics": ["memory architecture", "experimental design"],
                },
                "transcript segmentation and idea-unit coverage",
            ),
            (
                {
                    "obj_id": "L1-0429-058",
                    "type": "argument",
                    "importance": 0.68,
                    "content": "Due to a deadline, an experiment comparing three long-term memory update strategies, fixed chunking, iterative merging, and the incremental method, has been postponed.",
                    "related_topics": ["experimental design", "long-term memory management"],
                },
                "memory evaluation strategy",
            ),
            (
                {
                    "obj_id": "L1-0429-107",
                    "type": "argument",
                    "importance": 0.74,
                    "content": "As an alternative to an LLM-orchestrated workflow, a code-driven architecture was proposed where the main workflow is defined in the application's logic and the LLM is used for specific sub-tasks within that fixed flow.",
                    "related_topics": ["code_architecture", "development_strategy"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0429-145",
                    "type": "open_issue",
                    "importance": 0.67,
                    "content": "An unresolved architectural decision is whether to continue with the current single-prompt approach or refactor the system into a multi-agent architecture.",
                    "related_topics": ["code_architecture", "development_strategy"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0506-009",
                    "type": "argument",
                    "importance": 0.64,
                    "content": "System prompts should be self-contained and avoid jargon that the agent itself would not understand, because internal phrases such as downstream L1 agents can lead to unreliable outputs.",
                    "related_topics": ["LLM usage modes", "system architecture", "debugging"],
                },
                "prompt design and instruction quality",
            ),
            (
                {
                    "obj_id": "L1-0506-028",
                    "type": "approach_change",
                    "importance": 0.7,
                    "content": "A process has been implemented to log every prompt and its corresponding result for each agent interaction, enabling step-by-step verification of agent behavior.",
                    "related_topics": ["debugging", "process control", "agent-based systems"],
                },
                "pipeline observability and validation",
            ),
            (
                {
                    "obj_id": "L1-0506-042",
                    "type": "approach_change",
                    "importance": 0.81,
                    "content": "The initial importance of a memory unit is assigned by an LLM, with frequency of mention within a single meeting increasing the importance of all related idea units.",
                    "related_topics": ["long-term memory", "data handling", "system architecture"],
                },
                "memory lifecycle",
            ),
            (
                {
                    "obj_id": "L1-0429-086",
                    "type": "approach_change",
                    "importance": 0.78,
                    "content": "To address the lack of control and opacity in the current single-pass agent process, a new multi-step, externally controlled workflow will break tasks into smaller prompts and allow external checking throughout the process.",
                    "related_topics": ["LLM usage modes", "human-computer interaction"],
                },
                "pipeline observability and validation",
            ),
            (
                {
                    "obj_id": "L1-0429-128",
                    "type": "argument",
                    "importance": 0.7,
                    "content": "The specialized agent model is useful because each task-specific agent encapsulates its own knowledge, preventing the manager memory from becoming cluttered.",
                    "related_topics": ["LLM usage modes"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0429-148",
                    "type": "finding",
                    "importance": 0.72,
                    "content": "The current manager skill is a monolithic, single-pass process, making it impossible to test individual components in isolation and difficult to debug after cascading errors.",
                    "related_topics": ["LLM features"],
                },
                "pipeline observability and validation",
            ),
            (
                {
                    "obj_id": "L1-0429-160",
                    "type": "open_issue",
                    "importance": 0.72,
                    "content": "When updating a memory node from a large text block, the system must filter relevant input first; otherwise information bleeding can contaminate distinct nodes.",
                    "related_topics": ["RAG"],
                },
                "memory update semantics",
            ),
            (
                {
                    "obj_id": "L1-0429-088",
                    "type": "proposal",
                    "importance": 0.7,
                    "content": "An external program can track which sentences have already been processed with a boolean variable and call the agent only for the next unprocessed sentence.",
                    "related_topics": ["LLM usage modes"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0429-094",
                    "type": "action_item",
                    "importance": 0.7,
                    "content": "The second workflow step calls a transcript overview function that returns the total line count and a content preview so the agent understands the input size.",
                    "related_topics": ["LLM features"],
                },
                "agentic pipeline control",
            ),
            (
                {
                    "obj_id": "L1-0429-173",
                    "type": "approach_change",
                    "importance": 0.71,
                    "content": "為了解決關於記憶更新過程的困惑，將創建一個詳細的逐步演練，說明如何選擇相關句子來更新特定的記憶節點。",
                    "related_topics": ["RAG", "evaluation methodology"],
                },
                "memory update semantics",
            ),
        ]

        for obj, expected_label in cases:
            with self.subTest(obj_id=obj["obj_id"]):
                assignment = choose_l2_assignment(obj)
                self.assertEqual("assign_l2", assignment["action"])
                self.assertEqual(expected_label, assignment["l2_label"])

    def test_full_build_keeps_known_grace_topic_regressions_together(self) -> None:
        tree = {
            "tree_version": 3,
            "last_updated_utc": "2026-05-09T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
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
                            "The system will continue to use a fixed chunk size of approximately 20 lines for processing transcripts. The downstream object structuring logic can handle multiple topics within one chunk.",
                            importance=0.69,
                            topics=["model_configuration", "memory_system_implementation", "data_management"],
                        ),
                        _obj(
                            "L1-0429-139",
                            "open_issue",
                            "A key design issue was raised regarding the proposed manager-agent architecture: because the process is sequential, it is unclear why a separate agent is necessary.",
                            importance=0.67,
                            topics=["system architecture"],
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
                            "open_issue",
                            "The current idea unit extraction process sometimes misses transcript lines, creating gaps that are captured as low-quality raw text. A repair mechanism should merge these gaps.",
                            importance=0.68,
                            topics=["data handling", "output quality", "memory system implementation"],
                        ),
                        _obj(
                            "L1-0506-024",
                            "approach_change",
                            "A verification workflow records each agent step's full prompt and returned result so each input and output can be traced and checked before continuing.",
                            importance=0.65,
                            topics=["development workflow"],
                        ),
                    ],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            share_root = Path(tmp) / "share_mem"
            out_root = Path(tmp) / "long_term" / "l2"
            refresh_share_mem_outputs(root=share_root, tree=tree, source_transcript_dir=Path(tmp))

            build_l2_view_outputs(
                share_mem_root=share_root,
                output_root=out_root,
                mode="deterministic",
                clean=True,
            )

            l2_index = load_l2_index(out_root)
            self.assertEqual(
                "transcript segmentation and idea-unit coverage",
                l2_index["L1-0429-025"]["l2_label"],
            )
            self.assertEqual(
                l2_index["L1-0429-025"]["l2_id"],
                l2_index["L1-0506-009"]["l2_id"],
            )
            self.assertEqual("agentic pipeline control", l2_index["L1-0429-139"]["l2_label"])
            self.assertEqual(
                "pipeline observability and validation",
                l2_index["L1-0506-024"]["l2_label"],
            )

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
            {
                "obj_id": "L1-admin-003",
                "type": "finding",
                "importance": 0.56,
                "content": "在收到指導老師提供的 API 預算後，團隊需要追蹤 API 的使用情況。",
                "related_topics": ["lab_administration", "expense_reimbursement"],
            },
            {
                "obj_id": "L1-admin-004",
                "type": "finding",
                "importance": 0.71,
                "content": "To receive project funds, a student with a school work-study account must provide fund transfer details.",
                "related_topics": ["project_administration", "billing", "lab_administration"],
            },
        ]

        for obj in cases:
            with self.subTest(obj_id=obj["obj_id"]):
                assignment = choose_l2_assignment(obj)
                self.assertEqual("skip_l1", assignment["action"])
                if obj["obj_id"].startswith("L1-admin"):
                    self.assertFalse(assignment["review_required"])


if __name__ == "__main__":
    unittest.main()
