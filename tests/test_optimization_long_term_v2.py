from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.build_view import build_view  # noqa: E402
from optimization.long_term_v2.calibrate_profile import calibrate_profile  # noqa: E402
from optimization.long_term_v2.curate_v2_native_queries import curate_v2_native_queries  # noqa: E402
from optimization.long_term_v2.assign_l2 import assign_l2_topics  # noqa: E402
from optimization.long_term_v2.extract_semantic_keys import (  # noqa: E402
    build_semantic_key_index,
)
from optimization.long_term_v2.evaluate_retrieval import evaluate_retrieval, _rank_l1, _semantic_topic_hit  # noqa: E402
from optimization.long_term_v2.evaluate_answer_quality import evaluate_answer_quality  # noqa: E402
from optimization.long_term_v2.effective_view import load_effective_topic_surface  # noqa: E402
from optimization.long_term_v2.finalize_active_l2_review import finalize_active_l2_review  # noqa: E402
from optimization.long_term_v2.finalize_manual_review import finalize_manual_review  # noqa: E402
from optimization.long_term_v2.io_utils import load_json  # noqa: E402
from optimization.long_term_v2.apply_split_review_candidates import apply_split_review_candidates  # noqa: E402
from optimization.long_term_v2.export_runtime_view import export_runtime_view  # noqa: E402
from optimization.long_term_v2.run_answer_quality_eval import _build_v2_context, _context_token_usage  # noqa: E402
from optimization.long_term_v2.maturity_certification import (  # noqa: E402
    _suite_focused_split_review_summary,
    certify_maturity,
    create_related_topics_ablation_root,
    generate_manual_review_protocol,
)
from optimization.long_term_v2.llm_induction_proposals import propose_induction_review  # noqa: E402
from optimization.long_term_v2.llm_split_review import propose_focused_split_review  # noqa: E402
from optimization.long_term_v2.llm_topic_refinement import _extract_json, refine_l2_result_with_llm  # noqa: E402
from optimization.long_term_v2.make_retrieval_pressure_queries import (  # noqa: E402
    build_retrieval_pressure_queries,
)
from optimization.long_term_v2.make_professor_delivery_report import (  # noqa: E402
    build_professor_delivery_report,
)
from optimization.long_term_v2.profiles import load_profile  # noqa: E402
from optimization.long_term_v2.promote_l3 import build_l3_view  # noqa: E402
from optimization.long_term_v2.retrieval_split_pressure import build_retrieval_split_pressure_report  # noqa: E402
from optimization.long_term_v2.run_maturity_suite import load_datasets_config, run_maturity_suite  # noqa: E402
from optimization.long_term_v2.validate_llm_proposals import validate_llm_proposals  # noqa: E402
from optimization.long_term_v2.validate_view import validate_run  # noqa: E402


def _obj(
    obj_id: str,
    obj_type: str,
    content: str,
    *,
    evidence: str | None = None,
    importance: float = 0.72,
    topics: list[str] | None = None,
) -> dict:
    return {
        "obj_id": obj_id,
        "type": obj_type,
        "legacy_type": obj_type,
        "content": content,
        "importance": importance,
        "evidence": evidence or content,
        "related_topics": topics or [],
        "related_obj_ids": [],
    }


def _meeting(meeting_id: str, date: str, objects: list[dict]) -> dict:
    return {
        "meeting_id": meeting_id,
        "timestamp": f"{date}T00:00:00Z",
        "meeting_date": date,
        "source_file": f"{meeting_id}.txt",
        "phase_id": "",
        "memory_objects": objects,
    }


def _share_tree() -> dict:
    segmentation_objects = [
        _obj(
            f"L1-0422-{idx:03d}",
            "argument" if idx % 2 else "proposal",
            (
                "Transcript processing should preserve evidence coverage while "
                "splitting long mentor discussion into stable semantic units."
            ),
            evidence=(
                "The mentor said the transcript should be split into evidence-backed "
                "semantic units, with line coverage validation before memory update."
            ),
            importance=0.76,
        )
        for idx in range(1, 7)
    ]
    evaluation_objects = [
        _obj(
            f"L1-0429-{idx:03d}",
            "finding",
            (
                "The team needs evaluation questions, baseline comparison, and "
                "answer quality scoring to check whether memory retrieval is useful."
            ),
            evidence=(
                "They discussed evaluation questions, baseline comparison, token cost, "
                "and answer quality scoring for the mentor memory system."
            ),
            importance=0.74,
        )
        for idx in range(1, 7)
    ]
    admin_objects = [
        _obj(
            "L1-0506-001",
            "finding",
            "The group briefly mentioned the meeting room and schedule.",
            importance=0.22,
        )
    ]
    oversized_objects = [
        _obj(
            f"L1-0506-{idx + 2:03d}",
            "approach_change",
            (
                "Memory update workflow should connect evidence objects, topic state, "
                "retrieval context, and reviewer feedback without rewriting raw L1."
            ),
            evidence=(
                "The mentor and mentee discussed evidence object linking, topic state, "
                "retrieval context, feedback review, and raw L1 immutability."
            ),
            importance=0.78,
        )
        for idx in range(12)
    ]
    return {
        "tree_version": 1,
        "last_updated_utc": "2026-05-28T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [
            _meeting("0422", "2026-04-22", segmentation_objects),
            _meeting("0429", "2026-04-29", evaluation_objects),
            _meeting("0506", "2026-05-06", admin_objects + oversized_objects),
        ],
    }


def _write_share_root(root: Path, tree: dict | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = tree or _share_tree()
    (root / "tree.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_effective_surface_fixture(run_root: Path, *, profile_path: Path | None = None) -> None:
    raw_l2_view = {
        "l2_nodes": [
            {
                "l2_id": "L2-keep",
                "label": "recording setup",
                "linked_obj_ids": ["L1-KEEP"],
                "timeline_digest": [
                    {
                        "obj_id": "L1-KEEP",
                        "meeting_id": "BMR-001",
                        "meeting_date": "2026-01-01",
                        "summary": "The team discussed recording setup and headset microphone placement.",
                    }
                ],
                "current_state": "Recording setup remains an active equipment topic.",
                "evolution_summary": "The discussion links headset microphone placement to recording reliability.",
            },
            {
                "l2_id": "L2-suppress",
                "label": "go ahead",
                "linked_obj_ids": ["L1-SUPPRESS"],
                "timeline_digest": [
                    {
                        "obj_id": "L1-SUPPRESS",
                        "meeting_id": "BMR-001",
                        "meeting_date": "2026-01-01",
                        "summary": "The team said go ahead before moving to an unrelated item.",
                    }
                ],
                "current_state": "This is not a durable topic.",
                "evolution_summary": "This phrase is a discourse transition.",
            },
        ]
    }
    raw_l2_index = {
        "L1-KEEP": {"l2_id": "L2-keep", "l2_label": "recording setup"},
        "L1-SUPPRESS": {"l2_id": "L2-suppress", "l2_label": "go ahead"},
    }
    (run_root / "l2").mkdir(parents=True)
    (run_root / "l3").mkdir(parents=True)
    (run_root / "topic_review").mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps({"profile_path": str(profile_path)} if profile_path else {}),
        encoding="utf-8",
    )
    (run_root / "l2" / "l2_view.json").write_text(json.dumps(raw_l2_view), encoding="utf-8")
    (run_root / "l2" / "l2_index.json").write_text(json.dumps(raw_l2_index), encoding="utf-8")
    (run_root / "l3" / "l3_view.json").write_text(json.dumps({"l3_parents": []}), encoding="utf-8")
    (run_root / "l3" / "l3_index.json").write_text(json.dumps({}), encoding="utf-8")
    (run_root / "topic_review" / "effective_topic_index.json").write_text(
        json.dumps({"suppressed_l2_ids": ["L2-suppress"]}),
        encoding="utf-8",
    )


class _FakeResponse:
    text = json.dumps(
        {
            "topics": [
                {
                    "l2_id": "L2-manager-agent",
                    "recommended_label": "manager agent orchestration",
                    "definition": "Evidence about manager-agent orchestration and worker coordination.",
                    "inclusion_criteria": ["manager routes work to specialized agents"],
                    "exclusion_criteria": ["generic architecture discussion without manager-agent evidence"],
                    "confidence": 0.91,
                    "rationale": "The representative L1 evidence repeatedly mentions manager agent orchestration.",
                }
            ]
        }
    )


class _FakeModels:
    def generate_content(self, **_kwargs):
        return _FakeResponse()


class _FakeClient:
    models = _FakeModels()


class _FakeProposalResponse:
    text = json.dumps(
        {
            "merge_candidates": [
                {
                    "source_l2_id": "L2-manager-agent",
                    "target_l2_id": "L2-agent-routing",
                    "confidence": 0.72,
                    "rationale": "Both topics describe manager-agent routing.",
                    "representative_l1_ids": ["L1-001"],
                }
            ],
            "split_candidates": [
                {
                    "source_l2_id": "L2-manager-agent",
                    "proposed_child_labels": ["agent routing", "worker coordination"],
                    "confidence": 0.81,
                    "rationale": "The linked evidence separates routing from worker coordination.",
                    "representative_l1_ids": ["L1-001"],
                }
            ],
            "assignment_concerns": [
                {
                    "obj_id": "L1-001",
                    "l2_id": "L2-manager-agent",
                    "confidence": 0.64,
                    "rationale": "The object may fit a more specific routing topic.",
                }
            ],
        }
    )


class _FakeProposalModels:
    def generate_content(self, **_kwargs):
        return _FakeProposalResponse()


class _FakeProposalClient:
    models = _FakeProposalModels()


class _FakeSplitReviewResponse:
    text = json.dumps(
        {
            "split_candidates": [
                {
                    "source_l2_id": "L2-large-topic",
                    "proposed_child_labels": ["routing policy", "worker coordination"],
                    "confidence": 0.82,
                    "rationale": "The sample evidence separates routing policy from worker coordination.",
                    "representative_l1_ids": ["L1-LARGE-001", "L1-LARGE-002"],
                }
            ],
            "review_only": [
                {
                    "source_l2_id": "L2-single-concept",
                    "reason": "The sample is one repeated concept and should stay review-only.",
                    "representative_l1_ids": ["L1-SINGLE-001"],
                }
            ],
        }
    )


class _FakeSplitReviewModels:
    def generate_content(self, **_kwargs):
        return _FakeSplitReviewResponse()


class _FakeSplitReviewClient:
    models = _FakeSplitReviewModels()


class _FakeChildSpecificSplitReviewResponse:
    text = json.dumps(
        {
            "split_candidates": [
                {
                    "source_l2_id": "L2-large-topic",
                    "child_candidates": [
                        {
                            "label": "routing policy",
                            "assignment_criteria": ["routing policy"],
                            "representative_l1_ids": ["L1-LARGE-001"],
                        },
                        {
                            "label": "worker coordination",
                            "assignment_criteria": ["worker coordination"],
                            "representative_l1_ids": ["L1-LARGE-002"],
                        },
                    ],
                    "confidence": 0.82,
                    "rationale": "Child-specific evidence separates routing from coordination.",
                }
            ],
            "review_only": [
                {
                    "source_l2_id": "L2-single-concept",
                    "reason": "Single repeated concept.",
                    "representative_l1_ids": ["L1-SINGLE-001"],
                }
            ],
        }
    )
    usage_metadata = {"prompt_token_count": 11, "total_token_count": 20}


class _FakeChildSpecificSplitReviewModels:
    def generate_content(self, **_kwargs):
        return _FakeChildSpecificSplitReviewResponse()


class _FakeChildSpecificSplitReviewClient:
    models = _FakeChildSpecificSplitReviewModels()


class OptimizationLongTermV2Tests(unittest.TestCase):
    def test_effective_topic_surface_filters_suppressed_l2_and_index_without_mutating_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "effective_surface"
            raw_l2_view = {
                "l2_nodes": [
                    {"l2_id": "L2-keep", "label": "recording setup", "linked_obj_ids": ["L1-001"]},
                    {"l2_id": "L2-suppress", "label": "go ahead", "linked_obj_ids": ["L1-002"]},
                ]
            }
            raw_l2_index = {
                "L1-001": {"l2_id": "L2-keep", "l2_label": "recording setup"},
                "L1-002": {"l2_id": "L2-suppress", "l2_label": "go ahead"},
            }
            (run_root / "l2").mkdir(parents=True)
            (run_root / "l3").mkdir(parents=True)
            (run_root / "topic_review").mkdir(parents=True)
            (run_root / "l2" / "l2_view.json").write_text(json.dumps(raw_l2_view), encoding="utf-8")
            (run_root / "l2" / "l2_index.json").write_text(json.dumps(raw_l2_index), encoding="utf-8")
            (run_root / "l3" / "l3_view.json").write_text(json.dumps({"l3_parents": []}), encoding="utf-8")
            (run_root / "l3" / "l3_index.json").write_text(json.dumps({}), encoding="utf-8")
            (run_root / "topic_review" / "effective_topic_index.json").write_text(
                json.dumps({"suppressed_l2_ids": ["L2-suppress"]}),
                encoding="utf-8",
            )

            surface = load_effective_topic_surface(run_root)

            self.assertEqual([node["l2_id"] for node in surface["l2_view"]["l2_nodes"]], ["L2-keep"])
            self.assertEqual(set(surface["l2_index"]), {"L1-001"})
            self.assertEqual(surface["suppressed_l2_ids"], ["L2-suppress"])
            self.assertEqual(set(surface["suppressed_l2_index"]), {"L1-002"})
            self.assertEqual(load_json(run_root / "l2" / "l2_view.json"), raw_l2_view)

    def test_evaluate_retrieval_uses_effective_topic_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share = root / "share"
            _write_share_root(
                share,
                {
                    "tree_version": 1,
                    "last_updated_utc": "2026-01-01T00:00:00Z",
                    "project_profile": {},
                    "phases": [],
                    "meetings": [
                        _meeting(
                            "BMR-001",
                            "2026-01-01",
                            [
                                _obj(
                                    "L1-KEEP",
                                    "finding",
                                    "The team discussed recording setup and headset microphone placement.",
                                    topics=["recording setup"],
                                ),
                                _obj(
                                    "L1-SUPPRESS",
                                    "finding",
                                    "The team said go ahead before moving to an unrelated item.",
                                    topics=["go ahead"],
                                ),
                            ],
                        )
                    ],
                },
            )
            run_root = root / "optimization" / "runs" / "effective_retrieval"
            (run_root / "l2").mkdir(parents=True)
            (run_root / "l3").mkdir(parents=True)
            (run_root / "topic_review").mkdir(parents=True)
            (run_root / "manifest.json").write_text(json.dumps({}), encoding="utf-8")
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {"l2_id": "L2-keep", "label": "recording setup", "linked_obj_ids": ["L1-KEEP"]},
                            {"l2_id": "L2-suppress", "label": "go ahead", "linked_obj_ids": ["L1-SUPPRESS"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_index.json").write_text(
                json.dumps(
                    {
                        "L1-KEEP": {"l2_id": "L2-keep", "l2_label": "recording setup"},
                        "L1-SUPPRESS": {"l2_id": "L2-suppress", "l2_label": "go ahead"},
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l3" / "l3_view.json").write_text(json.dumps({"l3_parents": []}), encoding="utf-8")
            (run_root / "l3" / "l3_index.json").write_text(json.dumps({}), encoding="utf-8")
            (run_root / "topic_review" / "effective_topic_index.json").write_text(
                json.dumps({"suppressed_l2_ids": ["L2-suppress"]}),
                encoding="utf-8",
            )
            queries = run_root / "queries.jsonl"
            queries.write_text(
                json.dumps(
                    {
                        "query": "go ahead recording setup",
                        "expected_obj_ids": ["L1-KEEP", "L1-SUPPRESS"],
                        "expected_l2_ids": ["L2-suppress"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = evaluate_retrieval(
                run_root=run_root,
                queries_path=queries,
                share_mem_root=share,
                top_k_l1=10,
            )

            row = report["queries"][0]
            self.assertIn("L1-SUPPRESS", {seed["obj_id"] for seed in row["selected_l1"]})
            self.assertNotIn("L2-suppress", row["selected_l2_ids"])
            self.assertFalse(row["expected_l2_hit"])

    def test_retrieval_report_records_suppressed_topic_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share = root / "share"
            _write_share_root(
                share,
                {
                    "tree_version": 1,
                    "last_updated_utc": "2026-01-01T00:00:00Z",
                    "project_profile": {},
                    "phases": [],
                    "meetings": [
                        _meeting(
                            "BMR-001",
                            "2026-01-01",
                            [
                                _obj("L1-KEEP", "finding", "The team discussed recording setup.", topics=["recording setup"]),
                                _obj("L1-SUPPRESS", "finding", "The team said go ahead before changing topic.", topics=["go ahead"]),
                            ],
                        )
                    ],
                },
            )
            run_root = root / "optimization" / "runs" / "suppressed_metadata"
            _write_effective_surface_fixture(run_root)
            queries = run_root / "queries.jsonl"
            queries.write_text(
                json.dumps({"query": "go ahead recording setup", "expected_obj_ids": ["L1-KEEP", "L1-SUPPRESS"]}) + "\n",
                encoding="utf-8",
            )

            report = evaluate_retrieval(run_root=run_root, queries_path=queries, share_mem_root=share, top_k_l1=10)

            row = report["queries"][0]
            self.assertEqual(report["effective_topic_surface"]["suppressed_l2_count"], 1)
            self.assertEqual(row["suppressed_l2_ids_available"], ["L2-suppress"])
            self.assertEqual(row["suppressed_selected_l1_count"], 1)
            self.assertEqual(row["selected_suppressed_l1_ids"], ["L1-SUPPRESS"])
            self.assertEqual(row["selected_suppressed_l2_ids"], ["L2-suppress"])

    def test_answer_quality_v2_context_uses_effective_topic_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share = root / "share"
            _write_share_root(
                share,
                {
                    "tree_version": 1,
                    "last_updated_utc": "2026-01-01T00:00:00Z",
                    "project_profile": {},
                    "phases": [],
                    "meetings": [
                        _meeting(
                            "BMR-001",
                            "2026-01-01",
                            [
                                _obj(
                                    "L1-KEEP",
                                    "finding",
                                    "The team discussed recording setup and headset microphone placement.",
                                    topics=["recording setup"],
                                ),
                                _obj(
                                    "L1-SUPPRESS",
                                    "finding",
                                    "The team said go ahead before moving to an unrelated item.",
                                    topics=["go ahead"],
                                ),
                            ],
                        )
                    ],
                },
            )
            run_root = root / "optimization" / "runs" / "effective_context"
            _write_effective_surface_fixture(
                run_root,
                profile_path=REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml",
            )

            context, trace = _build_v2_context(
                query="go ahead recording setup",
                run_root=run_root,
                share_mem_root=share,
                max_l1=10,
            )

            self.assertIn("L1-SUPPRESS", {seed["obj_id"] for seed in trace["selected_l1"]})
            self.assertIn("[L2-keep]", context)
            self.assertNotIn("[L2-suppress]", context)
            self.assertNotIn("go ahead\n  matched_l1_ids", context)

    def test_runtime_export_uses_effective_topic_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "runtime_effective"
            _write_effective_surface_fixture(run_root)
            (run_root / "input_snapshot").mkdir(parents=True)
            (run_root / "input_snapshot" / "tree.json").write_text(
                json.dumps({"meetings": []}),
                encoding="utf-8",
            )

            manifest = export_runtime_view(run_root, clean=True)

            runtime_l2 = load_json(run_root / "runtime" / "l2" / "l2_view.json")
            runtime_index = load_json(run_root / "runtime" / "l2" / "l2_index.json")
            self.assertEqual([node["l2_id"] for node in runtime_l2["l2_nodes"]], ["L2-keep"])
            self.assertEqual(set(runtime_index), {"L1-KEEP"})
            self.assertEqual(manifest["l2_topic_count"], 1)
            self.assertEqual(manifest["effective_topic_surface"]["suppressed_l2_count"], 1)

    def test_curate_icsi_queries_uses_effective_active_topics(self) -> None:
        from optimization.long_term_v2.curate_icsi_eval_queries import curate_icsi_eval_queries

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share = root / "share"
            _write_share_root(
                share,
                {
                    "tree_version": 1,
                    "last_updated_utc": "2026-01-01T00:00:00Z",
                    "project_profile": {},
                    "phases": [],
                    "meetings": [
                        _meeting(
                            "BMR-001",
                            "2026-01-01",
                            [
                                _obj("L1-AUDIO", "finding", "Audio channel quality affected transcription confidence.", topics=["audio channel quality"]),
                                _obj("L1-ROOM", "finding", "Room recording setup used headset microphones.", topics=["recording setup"]),
                                _obj("L1-GO", "finding", "The team said go ahead before moving to an unrelated item.", topics=["go ahead"]),
                            ],
                        ),
                        _meeting(
                            "BMR-002",
                            "2026-01-02",
                            [
                                _obj("L1-AUDIO-2", "finding", "Audio channel calibration was checked again.", topics=["audio channel quality"]),
                                _obj("L1-ROOM-2", "finding", "Recording setup changed participant microphone placement.", topics=["recording setup"]),
                            ],
                        ),
                    ],
                },
            )
            run_root = root / "optimization" / "runs" / "query_curator"
            (run_root / "l2").mkdir(parents=True)
            (run_root / "l3").mkdir(parents=True)
            (run_root / "topic_review").mkdir(parents=True)
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-audio-channel-quality",
                                "label": "audio channel quality",
                                "linked_obj_ids": ["L1-AUDIO", "L1-AUDIO-2"],
                                "timeline_digest": [
                                    {"obj_id": "L1-AUDIO", "meeting_id": "BMR-001", "meeting_date": "2026-01-01", "summary": "Audio channel quality affected transcription confidence."},
                                    {"obj_id": "L1-AUDIO-2", "meeting_id": "BMR-002", "meeting_date": "2026-01-02", "summary": "Audio channel calibration was checked again."},
                                ],
                            },
                            {
                                "l2_id": "L2-recording-setup",
                                "label": "recording setup",
                                "linked_obj_ids": ["L1-ROOM", "L1-ROOM-2"],
                                "timeline_digest": [
                                    {"obj_id": "L1-ROOM", "meeting_id": "BMR-001", "meeting_date": "2026-01-01", "summary": "Room recording setup used headset microphones."},
                                    {"obj_id": "L1-ROOM-2", "meeting_id": "BMR-002", "meeting_date": "2026-01-02", "summary": "Recording setup changed participant microphone placement."},
                                ],
                            },
                            {
                                "l2_id": "L2-go-ahead",
                                "label": "go ahead",
                                "linked_obj_ids": ["L1-GO"],
                                "timeline_digest": [
                                    {"obj_id": "L1-GO", "meeting_id": "BMR-001", "meeting_date": "2026-01-01", "summary": "The team said go ahead before moving to an unrelated item."},
                                ],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_index.json").write_text(
                json.dumps(
                    {
                        "L1-AUDIO": {"l2_id": "L2-audio-channel-quality", "l2_label": "audio channel quality"},
                        "L1-AUDIO-2": {"l2_id": "L2-audio-channel-quality", "l2_label": "audio channel quality"},
                        "L1-ROOM": {"l2_id": "L2-recording-setup", "l2_label": "recording setup"},
                        "L1-ROOM-2": {"l2_id": "L2-recording-setup", "l2_label": "recording setup"},
                        "L1-GO": {"l2_id": "L2-go-ahead", "l2_label": "go ahead"},
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l3" / "l3_view.json").write_text(json.dumps({"l3_parents": []}), encoding="utf-8")
            (run_root / "l3" / "l3_index.json").write_text(json.dumps({}), encoding="utf-8")
            (run_root / "topic_review" / "effective_topic_index.json").write_text(
                json.dumps({"suppressed_l2_ids": ["L2-go-ahead"]}),
                encoding="utf-8",
            )

            out = root / "queries.jsonl"
            report = curate_icsi_eval_queries(run_root=run_root, share_mem_root=share, out=out, max_queries=5)

            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
            labels = {label for row in rows for label in row.get("expected_l2_labels", [])}
            self.assertIn("audio channel quality", labels)
            self.assertIn("recording setup", labels)
            self.assertNotIn("go ahead", labels)
            self.assertTrue(all(row.get("query") for row in rows))
            self.assertTrue(all(row.get("expected_obj_ids") for row in rows))
            self.assertEqual(report["suppressed_l2_count"], 1)

    def test_manual_review_active_l2_writes_effective_review_sections(self) -> None:
        from optimization.long_term_v2.manual_review_active_l2 import build_active_l2_manual_review

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share = root / "share"
            _write_share_root(
                share,
                {
                    "tree_version": 1,
                    "last_updated_utc": "2026-01-01T00:00:00Z",
                    "project_profile": {},
                    "phases": [],
                    "meetings": [
                        _meeting(
                            "BMR-001",
                            "2026-01-01",
                            [
                                _obj("L1-KEEP", "finding", "The team discussed recording setup.", importance=0.91, topics=["recording setup"]),
                                _obj("L1-SUPPRESS", "finding", "The team said go ahead before changing topic.", importance=0.88, topics=["go ahead"]),
                            ],
                        )
                    ],
                },
            )
            run_root = root / "optimization" / "runs" / "manual_review"
            _write_effective_surface_fixture(run_root)

            report = build_active_l2_manual_review(
                run_root=run_root,
                share_mem_root=share,
                out=root / "review",
                top_l2_limit=10,
                random_l1_limit=5,
                high_importance_limit=5,
            )

            self.assertIn("top_largest_active_l2", report)
            self.assertIn("suppressed_l2", report)
            self.assertIn("random_linked_l1", report)
            self.assertIn("high_importance_l1_sample", report)
            self.assertIn("review_schema", report)
            self.assertEqual([row["l2_id"] for row in report["top_largest_active_l2"]], ["L2-keep"])
            self.assertEqual([row["l2_id"] for row in report["suppressed_l2"]], ["L2-suppress"])
            self.assertIn("correct", report["review_schema"]["allowed_decisions"])
            self.assertTrue((root / "review" / "active_l2_manual_review.json").exists())
            self.assertTrue((root / "review" / "active_l2_manual_review.md").exists())

    def test_active_l2_review_finalizer_counts_warnings_and_known_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = root / "review"
            review_dir.mkdir(parents=True)
            (review_dir / "active_l2_manual_review.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "top_largest_active_l2": [
                            {"l2_id": "L2-keep", "label": "recording setup", "linked_l1_count": 12},
                            {"l2_id": "L2-label", "label": "ti digit", "linked_l1_count": 8},
                        ],
                        "suppressed_l2": [
                            {"l2_id": "L2-go", "label": "go ahead", "linked_l1_count": 5},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            decisions = root / "decisions.jsonl"
            decisions.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "review_id": "AR-0001",
                                "item_type": "active_l2",
                                "item_id": "L2-keep",
                                "decision": "correct",
                                "severity": "none",
                                "reason": "Representative evidence is coherent.",
                                "reviewer": "agent",
                                "created_at_utc": "2026-06-09T00:00:00Z",
                            }
                        ),
                        json.dumps(
                            {
                                "review_id": "AR-0002",
                                "item_type": "active_l2",
                                "item_id": "L2-label",
                                "decision": "needs_label_review",
                                "severity": "warning",
                                "reason": "The label is too abbreviated for a review audience.",
                                "reviewer": "agent",
                                "created_at_utc": "2026-06-09T00:00:00Z",
                            }
                        ),
                        json.dumps(
                            {
                                "review_id": "AR-0003",
                                "item_type": "suppressed_l2",
                                "item_id": "L2-go",
                                "decision": "correct_suppressed",
                                "severity": "none",
                                "reason": "This is a discourse transition, not a durable topic.",
                                "reviewer": "agent",
                                "created_at_utc": "2026-06-09T00:00:00Z",
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            report = finalize_active_l2_review(review_path=review_dir / "active_l2_manual_review.json", decisions_path=decisions, out=root / "out")

            self.assertEqual(report["status"], "warning")
            self.assertEqual(report["decision_count"], 3)
            self.assertEqual(report["warning_issue_count"], 1)
            self.assertEqual(report["known_item_decision_count"], 3)
            self.assertEqual(report["by_decision"]["needs_label_review"], 1)
            self.assertTrue((root / "out" / "active_l2_review_decisions_summary.json").exists())
            self.assertTrue((root / "out" / "active_l2_review_decisions_summary.md").exists())

    def test_active_l2_review_finalizer_rejects_unknown_item_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_path = root / "active_l2_manual_review.json"
            review_path.write_text(
                json.dumps({"top_largest_active_l2": [{"l2_id": "L2-known"}], "suppressed_l2": []}),
                encoding="utf-8",
            )
            decisions = root / "decisions.jsonl"
            decisions.write_text(
                json.dumps(
                    {
                        "review_id": "AR-0001",
                        "item_type": "active_l2",
                        "item_id": "L2-missing",
                        "decision": "correct",
                        "severity": "none",
                        "reason": "Bad reference.",
                        "reviewer": "agent",
                        "created_at_utc": "2026-06-09T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            report = finalize_active_l2_review(review_path=review_path, decisions_path=decisions, out=root / "out")

            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["unknown_item_count"], 1)

    def test_active_l2_review_finalizer_rejects_invalid_decision_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_path = root / "active_l2_manual_review.json"
            review_path.write_text(
                json.dumps({"top_largest_active_l2": [{"l2_id": "L2-known"}], "suppressed_l2": []}),
                encoding="utf-8",
            )
            decisions = root / "decisions.jsonl"
            decisions.write_text(
                json.dumps(
                    {
                        "review_id": "AR-0001",
                        "item_type": "active_l2",
                        "item_id": "L2-known",
                        "decision": "custom_rule",
                        "severity": "none",
                        "reason": "Bad decision.",
                        "reviewer": "agent",
                        "created_at_utc": "2026-06-09T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            report = finalize_active_l2_review(review_path=review_path, decisions_path=decisions, out=root / "out")

            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["validation_error_count"], 1)

    def test_label_refinement_proposals_require_representative_l1(self) -> None:
        from optimization.long_term_v2.propose_topic_label_refinements import propose_label_refinements

        review = {
            "decisions": [
                {
                    "item_type": "active_l2",
                    "item_id": "L2-ti-digit",
                    "decision": "needs_label_review",
                    "reason": "Representative L1 concerns TI-digits benchmark comparison set.",
                }
            ]
        }
        l2_nodes = {
            "L2-ti-digit": {
                "l2_id": "L2-ti-digit",
                "label": "ti digit",
                "linked_obj_ids": ["L1-A", "L1-B"],
                "timeline_digest": [{"obj_id": "L1-A", "summary": "Compare against TI-digits benchmark."}],
                "top_semantic_terms": [{"term": "ti digit benchmark", "object_count": 2}],
            }
        }

        report = propose_label_refinements(review=review, l2_nodes=l2_nodes)

        self.assertEqual(report["proposal_count"], 1)
        proposal = report["proposals"][0]
        self.assertEqual(proposal["source_l2_id"], "L2-ti-digit")
        self.assertNotEqual(proposal["proposed_label"], "ti digit")
        self.assertTrue(proposal["representative_l1_ids"])
        self.assertEqual(proposal["application_policy"], "sidecar_review_required")

    def test_effective_topic_run_comparison_reports_label_and_metric_changes(self) -> None:
        from optimization.long_term_v2.compare_effective_topic_runs import compare_effective_topic_runs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "optimization" / "runs" / "baseline"
            candidate = root / "optimization" / "runs" / "candidate"
            for run_root, label in [(baseline, "ti digit"), (candidate, "TI-digits benchmark comparison")]:
                _write_json(
                    run_root / "manifest.json",
                    {"source_l1_count": 2, "linked_l1_count": 2, "l2_topic_count": 1, "l3_parent_count": 0},
                )
                _write_json(
                    run_root / "l2" / "l2_view.json",
                    {"l2_nodes": [{"l2_id": "L2-ti-digit", "label": label, "linked_obj_ids": ["L1-A", "L1-B"]}]},
                )
                _write_json(run_root / "l2" / "l2_index.json", {"L1-A": {"l2_id": "L2-ti-digit", "l2_label": label}})
                _write_json(run_root / "l3" / "l3_view.json", {"l3_parents": []})
                _write_json(run_root / "l3" / "l3_index.json", {})
            _write_json(
                baseline / "retrieval_eval_icsi_effective" / "retrieval_eval_report.json",
                {"summary": {"avg_expected_obj_recall_at_context": 0.5, "expected_l2_semantic_hit_rate": 1.0}},
            )
            _write_json(
                candidate / "retrieval_eval_icsi_effective" / "retrieval_eval_report.json",
                {"summary": {"avg_expected_obj_recall_at_context": 0.6, "expected_l2_semantic_hit_rate": 1.0}},
            )

            report = compare_effective_topic_runs(baseline=baseline, candidate=candidate, out=root / "optimization" / "reports" / "comparison")

            self.assertEqual(report["changed_label_count"], 1)
            self.assertGreaterEqual(report["retrieval_metric_deltas"]["avg_expected_obj_recall_at_context"], 0)
            self.assertEqual(report["decision"], "candidate_kept_isolated")

    def test_effective_topic_run_comparison_reports_applied_splits_as_improvement(self) -> None:
        from optimization.long_term_v2.compare_effective_topic_runs import compare_effective_topic_runs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "optimization" / "runs" / "baseline"
            candidate = root / "optimization" / "runs" / "candidate"
            for run_root in (baseline, candidate):
                _write_json(
                    run_root / "manifest.json",
                    {"source_l1_count": 6, "linked_l1_count": 6, "l2_topic_count": 1, "l3_parent_count": 0},
                )
                _write_json(
                    run_root / "l2" / "l2_view.json",
                    {"l2_nodes": [{"l2_id": "L2-large", "label": "large topic", "linked_obj_ids": ["L1-A"]}]},
                )
                _write_json(run_root / "l2" / "l2_index.json", {"L1-A": {"l2_id": "L2-large", "l2_label": "large topic"}})
                _write_json(run_root / "l3" / "l3_view.json", {"l3_parents": []})
                _write_json(run_root / "l3" / "l3_index.json", {})
                _write_json(
                    run_root / "retrieval_eval_icsi_effective" / "retrieval_eval_report.json",
                    {"summary": {"avg_expected_obj_recall_at_context": 0.6, "expected_l2_semantic_hit_rate": 1.0}},
                )
            _write_json(
                candidate / "l3" / "applied_split_review_candidates.json",
                {
                    "applied_split_count": 1,
                    "skipped_split_count": 0,
                    "applied_splits": [{"source_l2_id": "L2-large", "child_count": 2}],
                },
            )

            report = compare_effective_topic_runs(baseline=baseline, candidate=candidate)

            self.assertEqual(report["applied_split_count"], 1)
            self.assertIn("applied_focused_l2_splits", report["improvements"])
            self.assertEqual(report["decision"], "candidate_shadow_ready")

    def test_icsi_answer_quality_proxy_compares_candidate_context_quality(self) -> None:
        from optimization.long_term_v2.evaluate_icsi_answer_quality import evaluate_icsi_answer_quality_proxy

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "optimization" / "runs" / "baseline"
            candidate = root / "optimization" / "runs" / "candidate"
            _write_json(
                baseline / "retrieval_eval_icsi_effective" / "retrieval_eval_report.json",
                {
                    "summary": {"avg_expected_obj_recall_at_context": 0.6, "expected_l2_semantic_hit_rate": 1.0},
                    "queries": [{"query_id": "q1", "expected_l2_labels": ["ti digit"], "selected_l1": [{"obj_id": "L1-A"}]}],
                },
            )
            _write_json(
                candidate / "retrieval_eval_icsi_effective" / "retrieval_eval_report.json",
                {
                    "summary": {"avg_expected_obj_recall_at_context": 0.7, "expected_l2_semantic_hit_rate": 1.0},
                    "queries": [
                        {
                            "query_id": "q1",
                            "expected_l2_labels": ["TI-digits benchmark comparison"],
                            "selected_l1": [{"obj_id": "L1-A"}, {"obj_id": "L1-B"}],
                        }
                    ],
                },
            )

            report = evaluate_icsi_answer_quality_proxy(
                baseline_run_root=baseline,
                candidate_run_root=candidate,
                out=root / "optimization" / "reports" / "answer_quality",
            )

            self.assertEqual(report["strategy_count"], 2)
            self.assertIn("baseline", report["strategies"])
            self.assertIn("candidate", report["strategies"])
            self.assertGreaterEqual(
                report["strategies"]["candidate"]["proxy_overall_score"],
                report["strategies"]["baseline"]["proxy_overall_score"],
            )

    def test_icsi_full_context_uses_requested_line_scope(self) -> None:
        from optimization.long_term_v2.run_icsi_answer_quality_comparison import build_first360_full_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript_dir = root / "transcripts"
            transcript_dir.mkdir()
            (transcript_dir / "Bmr001.txt").write_text("\n".join(f"line {idx}" for idx in range(1, 8)), encoding="utf-8")
            (transcript_dir / "Bmr002.txt").write_text("\n".join(f"other {idx}" for idx in range(1, 8)), encoding="utf-8")
            share_root = root / "share_mem_effective"
            _write_json(
                share_root / "tree.json",
                {
                    "meetings": [
                        {"meeting_id": "Bmr001_first360", "memory_objects": []},
                    ]
                },
            )

            context, meta = build_first360_full_context(
                share_mem_root=share_root,
                transcript_dir=transcript_dir,
                max_lines_per_meeting=3,
            )

            self.assertIn("--- meeting Bmr001_first360 ---", context)
            self.assertIn("line 1", context)
            self.assertIn("line 3", context)
            self.assertNotIn("line 4", context)
            self.assertNotIn("other 1", context)
            self.assertEqual(meta["included_meeting_count"], 1)
            self.assertFalse(meta["token_truncated"])

    def test_icsi_expected_answer_brief_uses_gold_l1_content(self) -> None:
        from optimization.long_term_v2.run_icsi_answer_quality_comparison import build_expected_answer_brief

        share_tree = {
            "meetings": [
                {
                    "meeting_id": "Bmr001_first360",
                    "meeting_date": "2026-06-01",
                    "memory_objects": [
                        {
                            "obj_id": "L1-Bmr001-001",
                            "content": "The team discussed microphone placement for recording setup.",
                            "evidence": "speaker evidence about microphone placement",
                            "type": "finding",
                        }
                    ],
                }
            ]
        }
        query = {
            "expected_obj_ids": ["L1-Bmr001-001"],
            "expected_l2_labels": ["recording equipment and setup"],
        }

        brief = build_expected_answer_brief(query, share_tree)

        self.assertIn("recording equipment and setup", brief)
        self.assertIn("L1-Bmr001-001", brief)
        self.assertIn("microphone placement", brief)

    def test_icsi_answer_quality_runner_uses_gate_compatible_strategy_names(self) -> None:
        from optimization.long_term_v2.run_icsi_answer_quality_comparison import STRATEGY_NAMES

        self.assertEqual(STRATEGY_NAMES["full_context"], "full_context")
        self.assertEqual(STRATEGY_NAMES["rag_baseline"], "rag_baseline")
        self.assertEqual(STRATEGY_NAMES["optimization_v2"], "optimization_v2_deterministic")

    def test_icsi_compact_report_marks_v2_win_against_available_baselines(self) -> None:
        from optimization.long_term_v2.run_icsi_answer_quality_comparison import _compact_report

        report = {
            "status": "warning",
            "gate_reasons": ["missing_canonical_layered"],
            "summary": {
                "full_context": {"average_overall_score": 0.5, "average_context_tokens": 1000},
                "rag_baseline": {"average_overall_score": 0.6, "average_context_tokens": 600},
                "optimization_v2_deterministic": {"average_overall_score": 0.75, "average_context_tokens": 300},
            },
            "failure_case_count": 0,
            "dimensions": [],
        }

        compact = _compact_report(report, raw_run_root=Path("optimization") / "runs" / "demo")

        self.assertEqual(compact["icsi_available_baseline_decision"], "optimization_v2_wins_available_baselines")
        self.assertGreater(compact["pairwise_overall_delta"]["optimization_v2_minus_rag"], 0)
        self.assertLess(compact["pairwise_context_token_delta"]["optimization_v2_minus_full_context"], 0)

    def test_shadow_qa_backend_specs_are_explicit(self) -> None:
        from optimization.long_term_v2.shadow_mode_qa_config import default_backend_specs

        specs = default_backend_specs(
            optimization_run_root=Path("optimization/runs/demo"),
        )

        self.assertEqual(specs["canonical"]["backend_name"], "canonical")
        self.assertEqual(specs["canonical"]["env"], {})
        self.assertEqual(specs["optimization_v2"]["backend_name"], "optimization_v2")
        self.assertEqual(specs["optimization_v2"]["env"]["LONG_TERM_BACKEND"], "optimization_v2")
        self.assertEqual(
            specs["optimization_v2"]["env"]["OPTIMIZATION_V2_RUN_ROOT"],
            "optimization/runs/demo",
        )

    def test_shadow_qa_extracts_trace_features(self) -> None:
        from optimization.long_term_v2.shadow_mode_qa import extract_trace_features

        context = """
=== Global Topic Map ===
- L3 L3-data-quality: data quality
  - child L2 L2-data-quality-audio: audio data quality

=== L1 Evidence Seeds ===
- [Bmr001_first360 | 2026-06-04 | L1-Bmr001_first360-001] type=finding importance=0.7 score=0.8
  content: The group discussed audio quality.

=== L2 / Child-L2 Evolution Context ===
[L2-data-quality] data quality
  parent L3: L3-data-quality data quality
""".strip()

        features = extract_trace_features(context)

        self.assertTrue(features["has_global_topic_map"])
        self.assertTrue(features["has_l1_evidence_seeds"])
        self.assertTrue(features["has_l2_evolution_context"])
        self.assertEqual(features["l1_ids"], ["L1-Bmr001_first360-001"])
        self.assertIn("L2-data-quality", features["l2_ids"])
        self.assertIn("L3-data-quality", features["l3_ids"])
        self.assertGreater(features["context_char_count"], 100)
        self.assertGreater(features["estimated_context_tokens"], 0)

    def test_shadow_qa_pairwise_comparison_marks_shadow_trace_ready(self) -> None:
        from optimization.long_term_v2.shadow_mode_qa import compare_backend_traces

        canonical = {
            "status": "ok",
            "resolved_backend": "canonical",
            "features": {
                "has_global_topic_map": True,
                "has_l1_evidence_seeds": True,
                "has_l2_evolution_context": False,
                "l1_ids": ["L1-A"],
                "l2_ids": [],
                "l3_ids": [],
                "estimated_context_tokens": 2000,
            },
        }
        shadow = {
            "status": "ok",
            "resolved_backend": "optimization_v2",
            "features": {
                "has_global_topic_map": True,
                "has_l1_evidence_seeds": True,
                "has_l2_evolution_context": True,
                "l1_ids": ["L1-A", "L1-B"],
                "l2_ids": ["L2-topic"],
                "l3_ids": ["L3-family"],
                "estimated_context_tokens": 1800,
            },
        }

        comparison = compare_backend_traces(canonical, shadow)

        self.assertEqual(comparison["decision"], "shadow_trace_ready")
        self.assertEqual(comparison["l1_overlap_count"], 1)
        self.assertGreater(comparison["shadow_l2_count"], 0)

    def test_shadow_qa_summary_decision_requires_all_queries_ready(self) -> None:
        from optimization.long_term_v2.shadow_mode_qa import summarize_shadow_qa

        summary = summarize_shadow_qa(
            query_results=[
                {"comparison": {"decision": "shadow_trace_ready"}},
                {"comparison": {"decision": "needs_review", "reason_codes": ["shadow_missing_l2_context"]}},
            ]
        )

        self.assertEqual(summary["decision"], "needs_review")
        self.assertEqual(summary["query_count"], 2)
        self.assertEqual(summary["shadow_trace_ready_count"], 1)
        self.assertEqual(summary["needs_review_count"], 1)
        self.assertIn("shadow_missing_l2_context", summary["reason_code_counts"])

    def test_profile_and_calibration_write_only_to_requested_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            out_root = base / "optimization" / "runs" / "calibration"
            canonical_before = json.dumps(_share_tree(), ensure_ascii=False, sort_keys=True)
            _write_share_root(share_root)

            profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
            report = calibrate_profile(share_mem_root=share_root, profile=profile, out_dir=out_root)

            self.assertEqual(report["meeting_count"], 3)
            self.assertEqual(report["l1_count"], 25)
            self.assertTrue((out_root / "profile_calibration.json").exists())
            self.assertFalse((share_root / "profile_calibration.json").exists())
            canonical_after = json.dumps(load_json(share_root / "tree.json"), ensure_ascii=False, sort_keys=True)
            self.assertEqual(canonical_after, canonical_before)

    def test_semantic_keys_do_not_require_related_topics(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = _share_tree()
        for meeting in tree["meetings"]:
            for obj in meeting["memory_objects"]:
                obj["related_topics"] = []

        index = build_semantic_key_index(tree, profile)

        first = index["objects"]["L1-0422-001"]
        self.assertGreater(first["confidence"], 0.0)
        flattened = {
            value
            for values in first["semantic_facets"].values()
            for value in values
        }
        self.assertTrue(any("transcript" in value or "evidence" in value for value in flattened))
        self.assertEqual(first["source_signals"]["related_topics"], [])

    def test_related_topics_do_not_dominate_l2_label_when_content_disagrees(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "M01",
                    "2026-05-01",
                    [
                        _obj(
                            f"L1-M01-{idx:03d}",
                            "finding",
                            "The mentor discussed transcript evidence coverage and reviewable source spans.",
                            evidence="Transcript evidence coverage, source spans, and reviewability were the durable issue.",
                            topics=["agent architecture"],
                            importance=0.76,
                        )
                        for idx in range(1, 6)
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)

        labels = {node["label"] for node in l2["l2_nodes"]}
        self.assertNotIn("agent architecture", labels)
        self.assertTrue(
            any("evidence" in label or "transcript" in label or "coverage" in label or "source span" in label for label in labels),
            labels,
        )

    def test_frequent_related_topic_does_not_override_repeated_evidence_term(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "M01",
                    "2026-05-01",
                    [
                        _obj(
                            f"L1-M01-{idx:03d}",
                            "finding",
                            "The manager agent coordinates worker agents and reconciles their outputs.",
                            evidence="Manager agent orchestration is the repeated evidence term.",
                            topics=["architecture design"],
                            importance=0.76,
                        )
                        for idx in range(1, 7)
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)

        labels = {node["label"] for node in l2["l2_nodes"]}
        self.assertIn("manager agent", labels)
        self.assertNotIn("architecture design", labels)

    def test_generic_single_words_do_not_become_l2_topics(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "M01",
                    "2026-05-01",
                    [
                        _obj(
                            f"L1-M01-{idx:03d}",
                            "finding",
                            "Long term memory update should preserve evidence state during retrieval.",
                            evidence="Long term memory update was the repeated durable evidence, not the isolated word term.",
                            importance=0.76,
                        )
                        for idx in range(1, 7)
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)

        labels = {node["label"] for node in l2["l2_nodes"]}
        self.assertFalse({"long", "term", "memory", "update"} & labels, labels)
        self.assertTrue(any("long term memory" in label or "memory update" in label for label in labels), labels)

    def test_artifact_single_words_do_not_become_l2_topics_without_related_topics(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "M01",
                    "2026-05-01",
                    [
                        _obj(
                            f"L1-M01-{idx:03d}",
                            "finding",
                            "The segment window boundary should preserve source evidence while creating idea units.",
                            evidence="Segment, turn, function, and item are implementation artifacts; source evidence preservation is the durable topic.",
                            importance=0.76,
                        )
                        for idx in range(1, 7)
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)

        labels = {node["label"] for node in l2["l2_nodes"]}
        self.assertFalse({"segment", "turn", "function", "item"} & labels, labels)
        self.assertTrue(any("source evidence" in label or "evidence preservation" in label for label in labels), labels)

    def test_l2_assignment_rescues_related_medium_importance_singletons(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        recurring = [
            _obj(
                f"L1-EVAL-{index}",
                "finding",
                "The evaluation framework uses benchmark questions, retrieval baselines, and answer quality scoring.",
                evidence="The mentor discussed benchmark questions and retrieval baselines for answer quality evaluation.",
                importance=0.72,
                topics=[],
            )
            for index in range(1, 5)
        ]
        related_singleton = _obj(
            "L1-EVAL-SINGLE",
            "argument",
            "A LOCOMO benchmark result should be used in the answer quality evaluation baseline for multi-hop questions.",
            evidence="The team used this prior paper benchmark to reason about answer quality evaluation and baseline tradeoffs.",
            importance=0.63,
            topics=[],
        )
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [_meeting("M1", "2026-05-01", recurring + [related_singleton])],
        }
        semantic_index = build_semantic_key_index(tree, profile)
        result = assign_l2_topics(tree=tree, semantic_key_index=semantic_index, profile=profile)

        self.assertIn("L1-EVAL-SINGLE", result["l2_index"])
        self.assertEqual(result["l2_index"]["L1-EVAL-SINGLE"]["assignment_mode"], "semantic_rescue")
        self.assertFalse(any(row["obj_id"] == "L1-EVAL-SINGLE" for row in result["unlinked_objects"]))

    def test_l2_semantic_rescue_leaves_weak_overlap_for_manual_review(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        recurring = [
            _obj(
                f"L1-EVAL-WEAK-{index}",
                "finding",
                "The evaluation framework uses benchmark questions, retrieval baselines, and answer quality scoring.",
                evidence="The mentor discussed benchmark questions and retrieval baselines for answer quality evaluation.",
                importance=0.72,
                topics=[],
            )
            for index in range(1, 5)
        ]
        weak_singleton = _obj(
            "L1-EVAL-WEAK-SINGLE",
            "argument",
            "A benchmark result mentions a baseline but mainly discusses unrelated token cost tradeoffs.",
            evidence="The prior result has benchmark and baseline terms but does not clearly share the topic state.",
            importance=0.63,
            topics=[],
        )
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [_meeting("M1", "2026-05-01", recurring + [weak_singleton])],
        }
        semantic_index = build_semantic_key_index(tree, profile)
        result = assign_l2_topics(tree=tree, semantic_key_index=semantic_index, profile=profile)

        self.assertNotIn("L1-EVAL-WEAK-SINGLE", result["l2_index"])
        review_rows = [row for row in result["unlinked_objects"] if row["obj_id"] == "L1-EVAL-WEAK-SINGLE"]
        self.assertEqual(review_rows[0]["reason"], "semantic_rescue_low_confidence_review")

    def test_l2_semantic_rescue_ignores_cjk_filler_overlap_for_english_profile(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        recurring = [
            _obj(
                f"L1-EVAL-FILLER-{index}",
                "finding",
                "就是 那個 這個 The evaluation framework uses benchmark questions and answer quality scoring.",
                evidence="就是 那個 benchmark questions and answer quality evaluation.",
                importance=0.72,
                topics=[],
            )
            for index in range(1, 5)
        ]
        unrelated_singleton = _obj(
            "L1-UNRELATED-FILLER",
            "argument",
            "就是 那個 這個 The students should prepare internship application materials.",
            evidence="就是 那個 the professor may contact Academia Sinica for an internship application.",
            importance=0.63,
            topics=[],
        )
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [_meeting("M1", "2026-05-01", recurring + [unrelated_singleton])],
        }
        semantic_index = build_semantic_key_index(tree, profile)
        result = assign_l2_topics(tree=tree, semantic_key_index=semantic_index, profile=profile)

        self.assertNotIn("L1-UNRELATED-FILLER", result["l2_index"])

    def test_l2_topic_state_is_evidence_based_not_count_placeholder(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = _share_tree()
        semantic_index = build_semantic_key_index(tree, profile)
        result = assign_l2_topics(tree=tree, semantic_key_index=semantic_index, profile=profile)

        states = [node["current_state"] for node in result["l2_nodes"]]
        self.assertTrue(states)
        self.assertFalse(any("is supported by" in state for state in states))
        self.assertTrue(any("latest" in state.lower() or "current position" in state.lower() for state in states))

    def test_broad_engineering_bucket_does_not_swallow_specific_phrase(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "M01",
                    "2026-05-01",
                    [
                        _obj(
                            f"L1-M01-{idx:03d}",
                            "finding",
                            "Manager agent orchestration separates routing from specialist worker execution.",
                            evidence="Manager agent orchestration and specialist worker execution were the durable evidence.",
                            topics=["architecture design", "agent architecture"],
                            importance=0.76,
                        )
                        for idx in range(1, 7)
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)

        labels = {node["label"] for node in l2["l2_nodes"]}
        self.assertNotIn("architecture design", labels)
        self.assertNotIn("agent architecture", labels)
        self.assertTrue(
            any(
                "manager agent" in label
                or "orchestration" in label
                or "specialist worker" in label
                or "worker execution" in label
                for label in labels
            ),
            labels,
        )

    def test_high_frequency_broad_term_does_not_swallow_specific_subtopics(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        persona = [
            _obj(
                f"L1-PER-{idx:03d}",
                "finding",
                "Agent architecture includes persona memory style adaptation for mentor dialogue.",
                evidence="Persona memory style adaptation was the durable design issue inside the agent architecture.",
                importance=0.75,
            )
            for idx in range(1, 7)
        ]
        audio = [
            _obj(
                f"L1-AUD-{idx:03d}",
                "finding",
                "Agent architecture includes audio retrieval with source timestamp playback.",
                evidence="Audio retrieval and source timestamp playback were the durable design issue inside the agent architecture.",
                importance=0.75,
            )
            for idx in range(1, 7)
        ]
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting("M01", "2026-05-01", persona),
                _meeting("M02", "2026-05-08", audio),
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)

        labels = {node["label"] for node in l2["l2_nodes"]}
        self.assertNotEqual(labels, {"agent architecture"})
        self.assertTrue(
            any("persona" in label or "memory style" in label or "adaptation" in label for label in labels),
            labels,
        )
        self.assertTrue(any("audio" in label or "timestamp" in label for label in labels), labels)

    def test_low_importance_singleton_l1_does_not_create_durable_l2(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        durable = [
            _obj(
                f"L1-DUR-{idx:03d}",
                "finding",
                "Persona memory style adaptation should be validated across mentor meetings.",
                evidence="Persona memory style adaptation is the recurring durable topic.",
                topics=["agent"],
                importance=0.74,
            )
            for idx in range(1, 6)
        ]
        singleton = _obj(
            "L1-SING-001",
            "finding",
            "A minor one-off API detail was mentioned briefly.",
            evidence="The API detail was not a recurring design topic.",
            topics=["agent"],
            importance=0.42,
        )
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting("M01", "2026-05-01", durable),
                _meeting("M02", "2026-05-08", [singleton]),
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)

        labels = {node["label"] for node in l2["l2_nodes"]}
        self.assertTrue(labels, labels)
        self.assertNotIn("agent", labels)
        self.assertIn("L1-SING-001", {row["obj_id"] for row in l2["unlinked_objects"]})

    def test_semantic_key_terms_filter_speaker_numbers_and_long_cjk_fragments(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "M01",
                    "2026-05-01",
                    [
                        _obj(
                            "L1-M01-001",
                            "decision",
                            "長期記憶採用 L1 L2 L3 hierarchy，讓 evidence-first retrieval 可以往上取得 topic context。",
                            evidence="[SPEAKER_00]: 你是說 0307 裡面有很多 object，然後 L1 往上總結成 L2 和 L3 嗎？",
                            importance=0.8,
                        )
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        terms = semantic["objects"]["L1-M01-001"]["candidate_terms"]

        self.assertFalse(any(term.startswith("00 ") or "speaker" in term for term in terms), terms)
        self.assertFalse(any(len(term) > 80 for term in terms), terms)
        self.assertTrue(any("l1 l2" in term or "hierarchy" in term for term in terms), terms)

    def test_topic_key_language_en_prefers_clean_technical_terms(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "M01",
                    "2026-05-01",
                    [
                        _obj(
                            "L1-M01-001",
                            "finding",
                            (
                                "團隊討論 dynamic chunking 與 fixed window boundary selection。"
                                "同時列出 decision、todo、method change、result、open question、argument。"
                            ),
                            evidence=(
                                "[SPEAKER_00]: agent 可能會為同一個 idea 產生重複候選，"
                                "所以我們比較 dynamic chunking and fixed window boundary selection."
                            ),
                            importance=0.76,
                        )
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        terms = semantic["objects"]["L1-M01-001"]["candidate_terms"]

        self.assertTrue(any("dynamic chunking" in term for term in terms), terms)
        self.assertTrue(any("window boundary" in term or "boundary selection" in term for term in terms), terms)
        self.assertFalse(any(any("\u4e00" <= char <= "\u9fff" for char in term) for term in terms), terms)
        self.assertFalse(any("decision todo" in term or "method change result" in term for term in terms), terms)

    def test_transcript_fillers_and_speaker_codes_do_not_become_terms(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "isci_meeting.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "SYN",
                    "2026-05-01",
                    [
                        _obj(
                            "L1-SYN-001",
                            "finding",
                            "uh ME003 and FE004 discuss annotation data model for corpus design",
                            evidence="ME003: uh the annotation data model and corpus design should be documented",
                            importance=0.75,
                        )
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        terms = semantic["objects"]["L1-SYN-001"]["candidate_terms"]

        self.assertTrue(any("annotation data model" in term or "corpus design" in term for term in terms), terms)
        self.assertFalse(
            any(term in {"uh", "be", "in", "you", "we", "so", "of", "it", "which", "ok", "mm", "hmm"} for term in terms),
            terms,
        )
        self.assertFalse(any("me003" in term or "fe004" in term for term in terms), terms)

    def test_function_words_do_not_become_icsi_l2_labels(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "isci_meeting.yaml")
        objects = [
            _obj(
                f"L1-SYN-{idx:03d}",
                "finding",
                (
                    "ME003 says uh you know we should document the annotation data model "
                    "and corpus design for reusable meeting research data."
                ),
                evidence=(
                    "FE004: so it is useful if the annotation data model and corpus design "
                    "are documented for the project."
                ),
                importance=0.75,
            )
            for idx in range(1, 7)
        ]
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [_meeting("SYN", "2026-05-01", objects)],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)
        labels = {node["label"] for node in l2["l2_nodes"]}

        self.assertFalse(labels & {"you", "we", "so", "of", "it", "is", "in", "which", "ok"}, labels)
        self.assertTrue(any("annotation data" in label or "corpus design" in label for label in labels), labels)

    def test_weak_conversation_phrases_do_not_become_l2_labels(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "isci_meeting.yaml")
        objects = [
            _obj(
                f"L1-SYN-{idx:03d}",
                "finding",
                "gonna gonna gonna read read allow allow",
                evidence="gonna gonna read read allow allow",
                importance=0.75,
                topics=["gonna", "read different line", "allow participant"],
            )
            for idx in range(1, 7)
        ]
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [_meeting("SYN", "2026-05-01", objects)],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)
        labels = {node["label"] for node in l2["l2_nodes"]}

        self.assertFalse(labels, labels)

    def test_icsi_profile_keeps_singletons_as_review_not_durable_l2(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "isci_meeting.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "SYN",
                    "2026-05-01",
                    [
                        _obj(
                            "L1-SYN-001",
                            "decision",
                            "The team selected a specialized feature file format for this pilot.",
                            evidence="A specialized feature file format was selected for this one pilot.",
                            importance=0.82,
                        )
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        l2 = assign_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)

        self.assertEqual(l2["l2_nodes"], [])
        self.assertEqual(l2["unlinked_objects"][0]["reason"], "singleton_l2_not_durable_enough")

    def test_l3_child_labels_use_clean_semantic_terms_not_summary_fragments(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        timeline = [
            {
                "meeting_id": "M01",
                "meeting_date": "2026-05-01",
                "obj_id": f"L1-M01-{idx:03d}",
                "summary": "agent 可能會為同一個 idea 產生重複候選，後續比較 dynamic chunking。",
                "importance": 0.76,
            }
            for idx in range(1, 15)
        ]
        l2_result = {
            "l2_nodes": [
                {
                    "l2_id": "L2-chunking-strategy",
                    "label": "chunking strategy",
                    "linked_obj_ids": [row["obj_id"] for row in timeline],
                    "timeline_digest": timeline,
                    "top_semantic_terms": [
                        {"term": "dynamic chunking", "object_count": 8},
                        {"term": "fixed window boundary", "object_count": 6},
                        {"term": "agent 可能會為同一個 idea", "object_count": 9},
                        {"term": "decision todo method", "object_count": 7},
                        {"term": "agent agent agent", "object_count": 7},
                    ],
                }
            ]
        }

        l3 = build_l3_view(l2_result=l2_result, profile=profile)
        child_labels = [
            child["label"]
            for parent in l3["l3_parents"]
            for child in parent["child_l2_nodes"]
        ]

        self.assertIn("dynamic chunking", child_labels)
        self.assertIn("fixed window boundary", child_labels)
        self.assertFalse(any(any("\u4e00" <= char <= "\u9fff" for char in label) for label in child_labels), child_labels)
        self.assertFalse(any("decision" in label or "todo" in label for label in child_labels), child_labels)
        self.assertFalse(any(len(set(label.split())) == 1 for label in child_labels), child_labels)

    def test_l3_child_labels_do_not_cross_stopword_boundaries(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "isci_meeting.yaml")
        timeline = [
            {
                "meeting_id": "SYN",
                "meeting_date": "2026-05-01",
                "obj_id": f"L1-SYN-{idx:03d}",
                "summary": "The group discussed annotation data model and corpus design for reusable meeting data.",
                "importance": 0.76,
            }
            for idx in range(1, 13)
        ]
        l2_result = {
            "l2_nodes": [
                {
                    "l2_id": "L2-annotation-planning",
                    "label": "annotation planning",
                    "linked_obj_ids": [row["obj_id"] for row in timeline],
                    "timeline_digest": timeline,
                    "top_semantic_terms": [],
                }
            ]
        }

        l3 = build_l3_view(l2_result=l2_result, profile=profile)
        child_labels = [
            child["label"]
            for parent in l3["l3_parents"]
            for child in parent.get("child_l2_nodes", [])
        ]

        self.assertFalse(any("model corpus" in label for label in child_labels), child_labels)
        self.assertTrue(
            any("annotation data" in label or "corpus design" in label for label in child_labels),
            child_labels,
        )

    def test_icsi_l3_child_labels_reject_setup_fragments(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "isci_meeting.yaml")
        timeline = [
            {
                "meeting_id": "SYN",
                "meeting_date": "2026-05-01",
                "obj_id": f"L1-SYN-{idx:03d}",
                "summary": (
                    "The team discussed recording setup, microphone placement, wire management, "
                    "and equipment cabinet changes for reliable meeting data collection."
                ),
                "importance": 0.76,
            }
            for idx in range(1, 31)
        ]
        l2_result = {
            "l2_nodes": [
                {
                    "l2_id": "L2-recording-setup",
                    "label": "recording setup",
                    "linked_obj_ids": [row["obj_id"] for row in timeline],
                    "timeline_digest": timeline,
                    "top_semantic_terms": [
                        {"term": "stuff gets broken", "object_count": 40},
                        {"term": "third extra person", "object_count": 40},
                        {"term": "another building", "object_count": 40},
                        {"term": "hoc data format", "object_count": 40},
                        {"term": "recording equipment", "object_count": 8},
                        {"term": "microphone placement", "object_count": 8},
                        {"term": "wire management", "object_count": 8},
                    ],
                }
            ]
        }

        l3 = build_l3_view(l2_result=l2_result, profile=profile)
        child_labels = [
            child["label"]
            for parent in l3["l3_parents"]
            for child in parent.get("child_l2_nodes", [])
        ]

        self.assertFalse(
            {"stuff gets broken", "third extra person", "another building", "hoc data format"} & set(child_labels),
            child_labels,
        )
        self.assertTrue(
            {"recording equipment", "microphone placement", "wire management"} & set(child_labels),
            child_labels,
        )

    def test_l3_uses_more_children_for_large_l2_to_avoid_oversized_child(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        topics = [
            "routing policy",
            "worker coordination",
            "tool selection",
            "budget control",
            "answer scoring",
            "evidence audit",
        ]
        timeline = []
        for index in range(120):
            topic = topics[index % len(topics)]
            timeline.append(
                {
                    "meeting_id": "M01",
                    "meeting_date": "2026-05-01",
                    "obj_id": f"L1-LARGE-{index:03d}",
                    "summary": f"The team discussed {topic} for the recurring orchestration topic.",
                    "importance": 0.76,
                }
            )
        l2_result = {
            "l2_nodes": [
                {
                    "l2_id": "L2-orchestration-topic",
                    "label": "orchestration topic",
                    "linked_obj_ids": [row["obj_id"] for row in timeline],
                    "timeline_digest": timeline,
                    "top_semantic_terms": [{"term": topic, "object_count": 20} for topic in topics],
                }
            ]
        }

        l3 = build_l3_view(l2_result=l2_result, profile=profile)
        children = l3["l3_parents"][0]["child_l2_nodes"]
        child_sizes = [len(child["linked_obj_ids"]) for child in children]

        self.assertGreaterEqual(len(children), 6)
        self.assertLessEqual(max(child_sizes), 35, child_sizes)

    def test_l3_keeps_low_separability_split_as_review_only(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        timeline = [
            {
                "meeting_id": "M01",
                "meeting_date": "2026-05-01",
                "obj_id": f"L1-LAB-{index:03d}",
                "summary": "The experiment lab comparison page reports token cost and latency.",
                "importance": 0.76,
            }
            for index in range(80)
        ]
        l2_result = {
            "l2_nodes": [
                {
                    "l2_id": "L2-experiment-lab",
                    "label": "experiment lab",
                    "linked_obj_ids": [row["obj_id"] for row in timeline],
                    "timeline_digest": timeline,
                    "top_semantic_terms": [
                        {"term": "lab comparison page", "object_count": 80},
                        {"term": "full context rag", "object_count": 8},
                        {"term": "layered memory", "object_count": 8},
                    ],
                }
            ]
        }

        l3 = build_l3_view(l2_result=l2_result, profile=profile)

        self.assertEqual(l3["l3_parents"], [])
        self.assertEqual(l3["l3_index"], {})
        self.assertTrue(
            any(row.get("action") == "needs_split_review" for row in l3["l2_merge_review"]["merge_reviews"]),
            l3["l2_merge_review"]["merge_reviews"],
        )

    def test_semantic_l2_hit_matches_any_expected_topic_individually(self) -> None:
        expected = {
            "L2-memory-lifecycle",
            "L2-pipeline-observability-and-validation",
            "L2-memory-retrieval",
        }
        selected = {"topic lifecycle", "rag", "forgetting mechanism"}

        self.assertTrue(_semantic_topic_hit(expected, selected))

    def test_semantic_l2_hit_uses_profile_eval_equivalents(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")

        self.assertTrue(
            _semantic_topic_hit(
                {"L2-memory-evaluation-strategy"},
                {"system performance evaluation"},
                profile=profile,
            )
        )

    def test_l1_rank_prefers_exact_topic_phrase_for_clear_english_query(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        l1_index = {
            "L1-noise": {
                "obj_id": "L1-noise",
                "content": "A generic memory discussion with many repeated memory words.",
                "evidence": "memory memory memory architecture",
                "topics": ["memory architecture"],
                "importance": 0.9,
            },
            "L1-stm-ltm": {
                "obj_id": "L1-stm-ltm",
                "content": "The retrieval router chooses between STM and LTM.",
                "evidence": "The short-term memory and long-term memory tools are both available.",
                "topics": ["short-term memory", "long-term memory"],
                "importance": 0.6,
            },
        }

        ranked = _rank_l1(
            "How are short-term memory and long-term memory integrated?",
            l1_index,
            top_k=2,
            profile=profile,
        )

        self.assertEqual(ranked[0]["obj_id"], "L1-stm-ltm")

    def test_semantic_terms_prefer_complete_memory_phrase_over_rejected_fragments(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "M01",
                    "2026-05-01",
                    [
                        _obj(
                            "L1-M01-001",
                            "decision",
                            "Short-term memory and long-term memory will update independently.",
                            evidence="The team decided short-term memory and long-term memory are separate update paths.",
                            importance=0.74,
                        )
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        terms = semantic["objects"]["L1-M01-001"]["candidate_terms"]

        self.assertTrue(any("short term memory" in term for term in terms), terms)
        self.assertTrue(any("long term memory" in term for term in terms), terms)
        self.assertFalse(any(term in {"term memory", "memory long"} for term in terms), terms)

    def test_profile_role_terms_control_artifact_filtering(self) -> None:
        profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
        profile["l1_roles"] = ["alpha_role", "beta_role", "gamma_role"]
        tree = {
            "tree_version": 1,
            "last_updated_utc": "2026-05-28T00:00:00Z",
            "project_profile": {},
            "phases": [],
            "meetings": [
                _meeting(
                    "M01",
                    "2026-05-01",
                    [
                        _obj(
                            "L1-M01-001",
                            "alpha_role",
                            "The team listed alpha role, beta role, gamma role, then discussed durable retrieval calibration.",
                            evidence="alpha role beta role gamma role were labels; retrieval calibration was the actual topic.",
                            importance=0.8,
                        )
                    ],
                )
            ],
        }

        semantic = build_semantic_key_index(tree, profile)
        terms = semantic["objects"]["L1-M01-001"]["candidate_terms"]

        self.assertTrue(any("retrieval calibration" in term for term in terms), terms)
        self.assertFalse(any("alpha role beta" in term or "beta role gamma" in term for term in terms), terms)

    def test_core_python_does_not_embed_grace_specific_topic_ontology(self) -> None:
        source_dir = REPO_ROOT / "optimization" / "long_term_v2"
        combined = "\n".join(
            path.read_text(encoding="utf-8").lower()
            for path in source_dir.glob("*.py")
        )
        grace_specific_terms = [
            "manager-agent",
            "transcript segmentation",
            "idea-unit coverage",
            "stm-ltm integration",
            "memory evaluation strategy",
            "topic lifecycle",
            "locomo",
        ]

        self.assertFalse(any(term in combined for term in grace_specific_terms))

    def test_build_validate_and_promote_v2_view_under_optimization_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            run_root = base / "optimization" / "runs" / "fixture_v2"
            _write_share_root(share_root)
            before = json.dumps(load_json(share_root / "tree.json"), ensure_ascii=False, sort_keys=True)

            result = build_view(
                share_mem_root=share_root,
                profile_path=REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml",
                out_root=run_root,
                mode="deterministic",
                clean=True,
            )
            validation = validate_run(run_root=run_root)

            self.assertEqual(result["manifest"]["source_l1_count"], 25)
            self.assertTrue((run_root / "semantic_keys" / "semantic_key_index.json").exists())
            self.assertTrue((run_root / "l2" / "l2_view.json").exists())
            self.assertTrue((run_root / "l2" / "l2_index.json").exists())
            self.assertTrue((run_root / "l3" / "l3_view.json").exists())
            self.assertTrue((run_root / "validation" / "manual_review_queue.json").exists())
            self.assertEqual(validation["severe_count"], 0)
            self.assertGreaterEqual(result["manifest"]["l2_topic_count"], 2)
            self.assertGreaterEqual(result["manifest"]["l3_parent_count"], 1)

            l2_view = load_json(run_root / "l2" / "l2_view.json")
            l3_view = load_json(run_root / "l3" / "l3_view.json")
            self.assertFalse(
                any(node["label"] in {"decision", "argument", "finding"} for node in l2_view["l2_nodes"])
            )
            self.assertTrue(
                all(node.get("creation_rationale") and node.get("representative_l1_ids") for node in l2_view["l2_nodes"])
            )
            child_labels = [
                child["label"]
                for parent in l3_view["l3_parents"]
                for child in parent.get("child_l2_nodes", [])
            ]
            self.assertFalse(any(label in {"idea", "llm", "short", "long"} for label in child_labels), child_labels)
            self.assertFalse(any("decision" in label or "todo" in label for label in child_labels), child_labels)
            self.assertTrue(all(len(label.split()) >= 2 for label in child_labels), child_labels)
            after = json.dumps(load_json(share_root / "tree.json"), ensure_ascii=False, sort_keys=True)
            self.assertEqual(after, before)

    def test_validation_warns_when_child_l2_remains_oversized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "oversized_child"
            (run_root / "input_snapshot").mkdir(parents=True, exist_ok=True)
            (run_root / "semantic_keys").mkdir(parents=True, exist_ok=True)
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            (run_root / "l3").mkdir(parents=True, exist_ok=True)
            linked_ids = [f"L1-{index:03d}" for index in range(40)]
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "source_l1_count": 40,
                        "profile_path": str(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml"),
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "input_snapshot" / "tree.json").write_text(json.dumps({"meetings": []}), encoding="utf-8")
            (run_root / "semantic_keys" / "semantic_key_index.json").write_text(
                json.dumps({"objects": {obj_id: {} for obj_id in linked_ids}}),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-large-topic",
                                "label": "large topic",
                                "definition": "Large recurring topic.",
                                "inclusion_criteria": ["large topic evidence"],
                                "exclusion_criteria": ["unrelated evidence"],
                                "linked_obj_ids": linked_ids,
                                "representative_l1_ids": linked_ids[:3],
                                "creation_rationale": "Recurring evidence supports this topic.",
                                "current_state": "Current position is represented by the latest evidence.",
                                "evolution_summary": "The topic evolved across meetings.",
                                "confidence": 0.9,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_index.json").write_text(
                json.dumps({obj_id: {"rationale": "Assigned from evidence.", "score_breakdown": {}} for obj_id in linked_ids}),
                encoding="utf-8",
            )
            (run_root / "l3" / "l3_view.json").write_text(
                json.dumps(
                    {
                        "l3_parents": [
                            {
                                "l3_id": "L3-large-topic",
                                "label": "large topic family",
                                "child_l2_nodes": [
                                    {
                                        "child_l2_id": "L2-large-topic-child",
                                        "label": "large topic child",
                                        "linked_obj_ids": linked_ids,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l3" / "l3_index.json").write_text(
                json.dumps({obj_id: {"child_l2_id": "L2-large-topic-child"} for obj_id in linked_ids}),
                encoding="utf-8",
            )

            validation = validate_run(run_root=run_root)

            self.assertEqual(validation["severe_count"], 0)
            self.assertTrue(
                any(issue["code"] == "oversized_child_l2" for issue in validation["manual_review_queue"]),
                validation["manual_review_queue"],
            )

    def test_validation_flags_rejected_child_l2_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "bad_child_label"
            (run_root / "input_snapshot").mkdir(parents=True, exist_ok=True)
            (run_root / "semantic_keys").mkdir(parents=True, exist_ok=True)
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            (run_root / "l3").mkdir(parents=True, exist_ok=True)
            linked_ids = [f"L1-{index:03d}" for index in range(6)]
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "source_l1_count": 6,
                        "profile_path": str(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "isci_meeting.yaml"),
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "input_snapshot" / "tree.json").write_text(json.dumps({"meetings": []}), encoding="utf-8")
            (run_root / "semantic_keys" / "semantic_key_index.json").write_text(
                json.dumps({"objects": {obj_id: {} for obj_id in linked_ids}}),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-recording-setup",
                                "label": "recording setup",
                                "definition": "Recording setup topic.",
                                "inclusion_criteria": ["recording setup evidence"],
                                "exclusion_criteria": ["unrelated evidence"],
                                "linked_obj_ids": linked_ids,
                                "representative_l1_ids": linked_ids[:3],
                                "creation_rationale": "Recurring evidence supports this topic.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_index.json").write_text(
                json.dumps({obj_id: {"rationale": "Assigned from evidence.", "score_breakdown": {}} for obj_id in linked_ids}),
                encoding="utf-8",
            )
            (run_root / "l3" / "l3_view.json").write_text(
                json.dumps(
                    {
                        "l3_parents": [
                            {
                                "l3_id": "L3-recording-setup",
                                "label": "recording setup",
                                "source_l2_id": "L2-recording-setup",
                                "child_l2_nodes": [
                                    {
                                        "child_l2_id": "L2-recording-setup-stuff-gets-broken",
                                        "label": "stuff gets broken",
                                        "linked_obj_ids": linked_ids,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l3" / "l3_index.json").write_text(
                json.dumps({obj_id: {"child_l2_id": "L2-recording-setup-stuff-gets-broken"} for obj_id in linked_ids}),
                encoding="utf-8",
            )

            validation = validate_run(run_root=run_root)

            self.assertTrue(
                any(issue["code"] == "rejected_child_l2_label" for issue in validation["manual_review_queue"]),
                validation["manual_review_queue"],
            )

    def test_validation_flags_weak_phrase_child_l2_label_with_source_l2_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "weak_child_label"
            (run_root / "input_snapshot").mkdir(parents=True, exist_ok=True)
            (run_root / "semantic_keys").mkdir(parents=True, exist_ok=True)
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            (run_root / "l3").mkdir(parents=True, exist_ok=True)
            linked_ids = [f"L1-{index:03d}" for index in range(6)]
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "source_l1_count": 6,
                        "profile_path": str(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml"),
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "input_snapshot" / "tree.json").write_text(json.dumps({"meetings": []}), encoding="utf-8")
            (run_root / "semantic_keys" / "semantic_key_index.json").write_text(
                json.dumps({"objects": {obj_id: {} for obj_id in linked_ids}}),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-annotation-tool",
                                "label": "annotation tool",
                                "linked_obj_ids": linked_ids,
                                "representative_l1_ids": linked_ids[:3],
                                "creation_rationale": "Recurring evidence supports this topic.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_index.json").write_text(
                json.dumps({obj_id: {"rationale": "Assigned from evidence.", "score_breakdown": {}} for obj_id in linked_ids}),
                encoding="utf-8",
            )
            (run_root / "l3" / "l3_view.json").write_text(
                json.dumps(
                    {
                        "l3_parents": [
                            {
                                "l3_id": "L3-annotation-tool",
                                "label": "annotation tool",
                                "source_l2_id": "L2-annotation-tool",
                                "child_l2_nodes": [
                                    {
                                        "child_l2_id": "L2-annotation-tool-basically-ascii-file",
                                        "label": "basically ascii file",
                                        "linked_obj_ids": linked_ids,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l3" / "l3_index.json").write_text(
                json.dumps({obj_id: {"child_l2_id": "L2-annotation-tool-basically-ascii-file"} for obj_id in linked_ids}),
                encoding="utf-8",
            )

            validation = validate_run(run_root=run_root)

            weak_items = [
                issue
                for issue in validation["manual_review_queue"]
                if issue["code"] == "weak_child_l2_label"
            ]
            self.assertEqual(len(weak_items), 1, validation["manual_review_queue"])
            self.assertEqual(weak_items[0]["source_l2_id"], "L2-annotation-tool")

    def test_focused_split_review_only_targets_needs_split_review_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "focused_split"
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            (run_root / "l3").mkdir(parents=True, exist_ok=True)
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-large-topic",
                                "label": "large topic",
                                "linked_obj_ids": ["L1-LARGE-001", "L1-LARGE-002"],
                                "representative_l1_ids": ["L1-LARGE-001"],
                                "top_semantic_terms": [{"term": "routing policy", "object_count": 5}],
                                "timeline_digest": [
                                    {
                                        "obj_id": "L1-LARGE-001",
                                        "meeting_id": "M01",
                                        "summary": "Routing policy was discussed.",
                                    },
                                    {
                                        "obj_id": "L1-LARGE-002",
                                        "meeting_id": "M01",
                                        "summary": "Worker coordination was discussed.",
                                    },
                                ],
                            },
                            {
                                "l2_id": "L2-single-concept",
                                "label": "single concept",
                                "linked_obj_ids": ["L1-SINGLE-001"],
                                "representative_l1_ids": ["L1-SINGLE-001"],
                                "top_semantic_terms": [{"term": "single concept", "object_count": 1}],
                                "timeline_digest": [
                                    {
                                        "obj_id": "L1-SINGLE-001",
                                        "meeting_id": "M01",
                                        "summary": "A repeated single concept.",
                                    }
                                ],
                            },
                            {
                                "l2_id": "L2-healthy-topic",
                                "label": "healthy topic",
                                "linked_obj_ids": ["L1-HEALTHY-001"],
                                "representative_l1_ids": ["L1-HEALTHY-001"],
                                "top_semantic_terms": [{"term": "healthy topic", "object_count": 1}],
                                "timeline_digest": [
                                    {
                                        "obj_id": "L1-HEALTHY-001",
                                        "meeting_id": "M01",
                                        "summary": "Should not be reviewed.",
                                    }
                                ],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l3" / "l2_merge_review.json").write_text(
                json.dumps(
                    {
                        "merge_reviews": [
                            {"action": "needs_split_review", "source_l2_id": "L2-large-topic"},
                            {"action": "needs_split_review", "source_l2_id": "L2-single-concept"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")

            report = propose_focused_split_review(
                run_root=run_root,
                profile=profile,
                model="fake-model",
                client=_FakeSplitReviewClient(),
            )

            self.assertEqual(report["status"], "llm_split_review_written")
            self.assertEqual(set(report["source_l2_ids"]), {"L2-large-topic", "L2-single-concept"})
            self.assertEqual(report["accepted_split_count"], 1)
            self.assertEqual(report["review_only_count"], 1)
            self.assertEqual(report["rejected_count"], 0)
            self.assertTrue((run_root / "l2" / "llm_split_review_proposals.json").exists())
            self.assertTrue((run_root / "l2" / "llm_split_review_proposals.md").exists())
            self.assertTrue((run_root / "api_calls" / "0002_l2_focused_split_review.json").exists())

    def test_focused_split_review_preserves_child_specific_split_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "focused_child_schema"
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            (run_root / "l3").mkdir(parents=True, exist_ok=True)
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-large-topic",
                                "label": "large topic",
                                "linked_obj_ids": ["L1-LARGE-001", "L1-LARGE-002"],
                                "representative_l1_ids": ["L1-LARGE-001", "L1-LARGE-002"],
                                "top_semantic_terms": [{"term": "routing policy", "object_count": 5}],
                                "timeline_digest": [
                                    {
                                        "obj_id": "L1-LARGE-001",
                                        "meeting_id": "M01",
                                        "summary": "Routing policy was discussed.",
                                    },
                                    {
                                        "obj_id": "L1-LARGE-002",
                                        "meeting_id": "M01",
                                        "summary": "Worker coordination was discussed.",
                                    },
                                ],
                            },
                            {
                                "l2_id": "L2-single-concept",
                                "label": "single concept",
                                "linked_obj_ids": ["L1-SINGLE-001"],
                                "representative_l1_ids": ["L1-SINGLE-001"],
                                "timeline_digest": [
                                    {
                                        "obj_id": "L1-SINGLE-001",
                                        "meeting_id": "M01",
                                        "summary": "A repeated single concept.",
                                    }
                                ],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l3" / "l2_merge_review.json").write_text(
                json.dumps(
                    {
                        "merge_reviews": [
                            {"action": "needs_split_review", "source_l2_id": "L2-large-topic"},
                            {"action": "needs_split_review", "source_l2_id": "L2-single-concept"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")

            report = propose_focused_split_review(
                run_root=run_root,
                profile=profile,
                model="fake-model",
                client=_FakeChildSpecificSplitReviewClient(),
            )

            self.assertEqual(report["accepted_split_count"], 1)
            accepted = report["accepted_split_candidates"][0]
            self.assertEqual([child["label"] for child in accepted["child_candidates"]], ["routing policy", "worker coordination"])
            self.assertEqual(accepted["child_candidates"][0]["representative_l1_ids"], ["L1-LARGE-001"])
            self.assertEqual(accepted["child_candidates"][1]["assignment_criteria"], ["worker coordination"])

    def test_suite_focused_split_review_summary_reports_missing_pending_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            suite_root = Path(tmp) / "optimization" / "runs" / "suite"
            run_root = suite_root / "synthetic_deterministic"
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            (run_root / "l3").mkdir(parents=True, exist_ok=True)
            (run_root / "l3" / "l2_merge_review.json").write_text(
                json.dumps(
                    {
                        "merge_reviews": [
                            {"action": "needs_split_review", "source_l2_id": "L2-a"},
                            {"action": "needs_split_review", "source_l2_id": "L2-b"},
                            {"action": "needs_merge_review", "source_child_l2_id": "L2-small"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l2" / "llm_split_review_proposals.json").write_text(
                json.dumps(
                    {
                        "status": "llm_split_review_written",
                        "source_l2_count": 1,
                        "source_l2_ids": ["L2-a"],
                        "accepted_split_candidates": [
                            {
                                "source_l2_id": "L2-a",
                                "proposed_child_labels": ["alpha branch", "beta branch"],
                                "representative_l1_ids": ["L1-a"],
                            }
                        ],
                        "review_only": [],
                        "rejected": [],
                    }
                ),
                encoding="utf-8",
            )

            summary = _suite_focused_split_review_summary(suite_root)

            self.assertEqual(summary["status"], "fail")
            self.assertEqual(summary["pending_split_review_count"], 2)
            self.assertEqual(summary["reviewed_source_count"], 1)
            self.assertEqual(summary["missing_review_source_ids"], ["L2-b"])

    def test_apply_split_review_candidates_writes_candidate_l3_without_mutating_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "optimization" / "runs"
            source_root = base / "source"
            candidate_root = base / "candidate"
            (source_root / "l2").mkdir(parents=True, exist_ok=True)
            (source_root / "l3").mkdir(parents=True, exist_ok=True)
            (source_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "source_l1_count": 6,
                        "l2_topic_count": 1,
                        "l3_parent_count": 0,
                        "l3_assigned_l1_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            timeline = [
                {"obj_id": "L1-001", "meeting_id": "M01", "meeting_date": "2026-05-01", "summary": "Routing policy was chosen for manager handoff."},
                {"obj_id": "L1-002", "meeting_id": "M02", "meeting_date": "2026-05-02", "summary": "Worker coordination failure modes were reviewed."},
                {"obj_id": "L1-003", "meeting_id": "M03", "meeting_date": "2026-05-03", "summary": "Routing policy metrics were added."},
                {"obj_id": "L1-004", "meeting_id": "M04", "meeting_date": "2026-05-04", "summary": "Worker coordination debugging was assigned."},
                {"obj_id": "L1-005", "meeting_id": "M05", "meeting_date": "2026-05-05", "summary": "Routing policy fallback rules were documented."},
                {"obj_id": "L1-006", "meeting_id": "M06", "meeting_date": "2026-05-06", "summary": "Worker coordination owner handoff was clarified."},
            ]
            (source_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-agentic-pipeline",
                                "label": "agentic pipeline",
                                "linked_obj_ids": [row["obj_id"] for row in timeline],
                                "timeline_digest": timeline,
                                "representative_l1_ids": ["L1-001", "L1-002"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "l2" / "l2_index.json").write_text(json.dumps({}), encoding="utf-8")
            (source_root / "l3" / "l3_view.json").write_text(json.dumps({"l3_parents": []}), encoding="utf-8")
            (source_root / "l3" / "l3_index.json").write_text(json.dumps({}), encoding="utf-8")
            (source_root / "l3" / "l2_merge_review.json").write_text(
                json.dumps(
                    {
                        "merge_reviews": [
                            {"action": "needs_split_review", "source_l2_id": "L2-agentic-pipeline"}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "l2" / "llm_split_review_proposals.json").write_text(
                json.dumps(
                    {
                        "accepted_split_candidates": [
                            {
                                "source_l2_id": "L2-agentic-pipeline",
                                "proposed_child_labels": ["routing policy", "worker coordination"],
                                "confidence": 0.84,
                                "rationale": "The evidence separates routing policy from worker coordination.",
                                "representative_l1_ids": ["L1-001", "L1-002"],
                            }
                        ],
                        "review_only": [],
                        "rejected": [],
                    }
                ),
                encoding="utf-8",
            )
            source_l3_before = (source_root / "l3" / "l3_view.json").read_text(encoding="utf-8")

            report = apply_split_review_candidates(source_run_root=source_root, out_root=candidate_root, clean=True)

            self.assertEqual(report["applied_split_count"], 1)
            self.assertEqual(report["status"], "candidate_splits_applied")
            self.assertEqual((source_root / "l3" / "l3_view.json").read_text(encoding="utf-8"), source_l3_before)
            candidate_l3 = load_json(candidate_root / "l3" / "l3_view.json")
            parent = candidate_l3["l3_parents"][0]
            self.assertEqual(parent["source_l2_id"], "L2-agentic-pipeline")
            self.assertEqual(len(parent["child_l2_nodes"]), 2)
            child_counts = {child["label"]: len(child["linked_obj_ids"]) for child in parent["child_l2_nodes"]}
            self.assertEqual(child_counts["routing policy"], 3)
            self.assertEqual(child_counts["worker coordination"], 3)
            candidate_index = load_json(candidate_root / "l3" / "l3_index.json")
            self.assertEqual(set(candidate_index), {"L1-001", "L1-002", "L1-003", "L1-004", "L1-005", "L1-006"})
            candidate_review = load_json(candidate_root / "l3" / "l2_merge_review.json")
            self.assertFalse(
                any(row.get("source_l2_id") == "L2-agentic-pipeline" and row.get("action") == "needs_split_review" for row in candidate_review["merge_reviews"])
            )
            candidate_manifest = load_json(candidate_root / "manifest.json")
            self.assertEqual(candidate_manifest["l3_parent_count"], 1)
            self.assertEqual(candidate_manifest["l3_assigned_l1_count"], 6)
            self.assertEqual(candidate_manifest["split_review_candidate"]["applied_split_count"], 1)
            self.assertTrue((candidate_root / "l3" / "applied_split_review_candidates.json").exists())

    def test_apply_split_review_candidates_skips_low_separability_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "optimization" / "runs"
            source_root = base / "source"
            candidate_root = base / "candidate"
            (source_root / "l2").mkdir(parents=True, exist_ok=True)
            (source_root / "l3").mkdir(parents=True, exist_ok=True)
            timeline = [
                {"obj_id": f"L1-{index:03d}", "summary": "Experiment Lab comparison page evaluates the same recurring topic."}
                for index in range(1, 8)
            ]
            (source_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-experiment-lab",
                                "label": "experiment lab",
                                "linked_obj_ids": [row["obj_id"] for row in timeline],
                                "timeline_digest": timeline,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "l2" / "l2_index.json").write_text(json.dumps({}), encoding="utf-8")
            (source_root / "l3" / "l3_view.json").write_text(json.dumps({"l3_parents": []}), encoding="utf-8")
            (source_root / "l3" / "l3_index.json").write_text(json.dumps({}), encoding="utf-8")
            (source_root / "l3" / "l2_merge_review.json").write_text(
                json.dumps({"merge_reviews": [{"action": "needs_split_review", "source_l2_id": "L2-experiment-lab"}]}),
                encoding="utf-8",
            )
            (source_root / "l2" / "llm_split_review_proposals.json").write_text(
                json.dumps(
                    {
                        "accepted_split_candidates": [
                            {
                                "source_l2_id": "L2-experiment-lab",
                                "proposed_child_labels": ["comparing retrieval strategies", "experiment lab as an evaluation platform"],
                                "confidence": 0.7,
                                "rationale": "May split by role, but the provided evidence may not separate cleanly.",
                                "representative_l1_ids": ["L1-001", "L1-002"],
                            }
                        ],
                        "review_only": [],
                        "rejected": [],
                    }
                ),
                encoding="utf-8",
            )

            report = apply_split_review_candidates(source_run_root=source_root, out_root=candidate_root, clean=True)

            self.assertEqual(report["applied_split_count"], 0)
            self.assertEqual(report["skipped_split_count"], 1)
            self.assertEqual(report["skipped_splits"][0]["reason"], "low_assignment_separability")
            candidate_l3 = load_json(candidate_root / "l3" / "l3_view.json")
            self.assertEqual(candidate_l3["l3_parents"], [])
            candidate_review = load_json(candidate_root / "l3" / "l2_merge_review.json")
            self.assertTrue(
                any(row.get("source_l2_id") == "L2-experiment-lab" and row.get("action") == "needs_split_review" for row in candidate_review["merge_reviews"])
            )

    def test_apply_split_review_candidates_uses_child_specific_representatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "optimization" / "runs"
            source_root = base / "source"
            candidate_root = base / "candidate"
            (source_root / "l2").mkdir(parents=True, exist_ok=True)
            (source_root / "l3").mkdir(parents=True, exist_ok=True)
            timeline = [
                {"obj_id": "L1-001", "summary": "The team added latency charts to evaluate the control workflow."},
                {"obj_id": "L1-002", "summary": "The team tracked token count changes for the control workflow."},
                {"obj_id": "L1-003", "summary": "The team investigated stale decision regressions in the control workflow."},
                {"obj_id": "L1-004", "summary": "The team investigated false positive retrieval in the control workflow."},
                {"obj_id": "L1-005", "summary": "The team compared retrieval latency charts for the control workflow."},
                {"obj_id": "L1-006", "summary": "The team traced false positive retrieval diagnostics in the control workflow."},
            ]
            (source_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-control-workflow",
                                "label": "control workflow",
                                "linked_obj_ids": [row["obj_id"] for row in timeline],
                                "timeline_digest": timeline,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "l2" / "l2_index.json").write_text(json.dumps({}), encoding="utf-8")
            (source_root / "l3" / "l3_view.json").write_text(json.dumps({"l3_parents": []}), encoding="utf-8")
            (source_root / "l3" / "l3_index.json").write_text(json.dumps({}), encoding="utf-8")
            (source_root / "l3" / "l2_merge_review.json").write_text(
                json.dumps({"merge_reviews": [{"action": "needs_split_review", "source_l2_id": "L2-control-workflow"}]}),
                encoding="utf-8",
            )
            (source_root / "l2" / "llm_split_review_proposals.json").write_text(
                json.dumps(
                    {
                        "accepted_split_candidates": [
                            {
                                "source_l2_id": "L2-control-workflow",
                                "child_candidates": [
                                    {
                                        "label": "performance tracking",
                                        "assignment_criteria": ["latency charts", "token count"],
                                        "representative_l1_ids": ["L1-001", "L1-002", "L1-005"],
                                    },
                                    {
                                        "label": "failure diagnostics",
                                        "assignment_criteria": ["stale decision", "false positive retrieval"],
                                        "representative_l1_ids": ["L1-003", "L1-004", "L1-006"],
                                    },
                                ],
                                "confidence": 0.82,
                                "rationale": "Child-specific evidence separates performance tracking from failure diagnostics.",
                            }
                        ],
                        "review_only": [],
                        "rejected": [],
                    }
                ),
                encoding="utf-8",
            )

            report = apply_split_review_candidates(source_run_root=source_root, out_root=candidate_root, clean=True)

            self.assertEqual(report["applied_split_count"], 1)
            parent = load_json(candidate_root / "l3" / "l3_view.json")["l3_parents"][0]
            child_sizes = {child["label"]: len(child["linked_obj_ids"]) for child in parent["child_l2_nodes"]}
            self.assertEqual(child_sizes, {"performance tracking": 3, "failure diagnostics": 3})
            candidate_index = load_json(candidate_root / "l3" / "l3_index.json")
            self.assertEqual(candidate_index["L1-001"]["child_l2_label"], "performance tracking")
            self.assertEqual(candidate_index["L1-004"]["child_l2_label"], "failure diagnostics")

    def test_apply_split_review_candidates_skips_oversized_candidate_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "optimization" / "runs"
            source_root = base / "source"
            candidate_root = base / "candidate"
            (source_root / "l2").mkdir(parents=True, exist_ok=True)
            (source_root / "l3").mkdir(parents=True, exist_ok=True)
            timeline = [
                {"obj_id": f"L1-A-{index:03d}", "summary": "Alpha routing policy evidence."}
                for index in range(40)
            ] + [
                {"obj_id": f"L1-B-{index:03d}", "summary": "Beta routing policy evidence."}
                for index in range(40)
            ]
            (source_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-too-large",
                                "label": "large source",
                                "linked_obj_ids": [row["obj_id"] for row in timeline],
                                "timeline_digest": timeline,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "l2" / "l2_index.json").write_text(json.dumps({}), encoding="utf-8")
            (source_root / "l3" / "l3_view.json").write_text(json.dumps({"l3_parents": []}), encoding="utf-8")
            (source_root / "l3" / "l3_index.json").write_text(json.dumps({}), encoding="utf-8")
            (source_root / "l3" / "l2_merge_review.json").write_text(
                json.dumps({"merge_reviews": [{"action": "needs_split_review", "source_l2_id": "L2-too-large"}]}),
                encoding="utf-8",
            )
            (source_root / "l2" / "llm_split_review_proposals.json").write_text(
                json.dumps(
                    {
                        "accepted_split_candidates": [
                            {
                                "source_l2_id": "L2-too-large",
                                "child_candidates": [
                                    {"label": "alpha routing", "assignment_criteria": ["alpha"], "representative_l1_ids": ["L1-A-000"]},
                                    {"label": "beta routing", "assignment_criteria": ["beta"], "representative_l1_ids": ["L1-B-000"]},
                                ],
                                "confidence": 0.9,
                                "rationale": "Children are separable but still too large.",
                            }
                        ],
                        "review_only": [],
                        "rejected": [],
                    }
                ),
                encoding="utf-8",
            )

            report = apply_split_review_candidates(source_run_root=source_root, out_root=candidate_root, clean=True)

            self.assertEqual(report["applied_split_count"], 0)
            self.assertEqual(report["skipped_splits"][0]["reason"], "candidate_child_still_oversized")

    def test_llm_refinement_writes_api_log_and_applies_safe_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "llm_refine"
            profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
            l2_result = {
                "l2_nodes": [
                    {
                        "l2_id": "L2-manager-agent",
                        "label": "manager agent",
                        "definition": "Evidence-backed mentor-mentee topic about manager agent.",
                        "inclusion_criteria": ["L1 evidence discusses manager agent."],
                        "exclusion_criteria": [],
                        "linked_obj_ids": ["L1-001", "L1-002"],
                        "timeline_digest": [
                            {
                                "meeting_id": "M01",
                                "meeting_date": "2026-05-01",
                                "obj_id": "L1-001",
                                "summary": "Manager agent routes work to specialized worker agents.",
                                "importance": 0.8,
                            }
                        ],
                        "current_state": "Manager agent topic.",
                        "creation_rationale": "Created deterministically.",
                    }
                ],
                "l2_index": {
                    "L1-001": {
                        "obj_id": "L1-001",
                        "l2_id": "L2-manager-agent",
                        "l2_label": "manager agent",
                    }
                },
                "unlinked_objects": [],
                "manual_review_items": [],
                "diagnostics": {},
            }

            refined, usage = refine_l2_result_with_llm(
                l2_result=l2_result,
                profile=profile,
                run_root=run_root,
                model="fake-model",
                client=_FakeClient(),
            )

            self.assertEqual(usage["status"], "llm_refinement_applied")
            self.assertEqual(refined["l2_nodes"][0]["label"], "manager agent orchestration")
            self.assertEqual(refined["l2_nodes"][0]["original_label"], "manager agent")
            self.assertEqual(refined["l2_index"]["L1-001"]["l2_label"], "manager agent orchestration")
            log_files = list((run_root / "api_calls").glob("*.json"))
            self.assertEqual(len(log_files), 1)
            log_payload = load_json(log_files[0])
            self.assertIn("prompt", log_payload)
            self.assertIn("raw_response", log_payload)
            self.assertNotIn("api_key", json.dumps(log_payload).lower())

    def test_llm_refinement_accepts_top_level_array_response(self) -> None:
        parsed = _extract_json(
            """
            [
              {
                "l2_id": "L2-memory",
                "recommended_label": "memory architecture",
                "confidence": 0.9
              }
            ]
            """
        )

        self.assertEqual(parsed["topics"][0]["l2_id"], "L2-memory")

    def test_llm_induction_proposal_writes_review_sidecar_without_mutating_l2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "proposal"
            profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")
            l2_dir = run_root / "l2"
            l2_dir.mkdir(parents=True, exist_ok=True)
            l2_payload = {
                "schema_version": 1,
                "l2_nodes": [
                    {
                        "l2_id": "L2-manager-agent",
                        "label": "manager agent",
                        "linked_obj_ids": ["L1-001", "L1-002"],
                        "timeline_digest": [
                            {
                                "obj_id": "L1-001",
                                "meeting_id": "M01",
                                "summary": "Manager agent routes work to specialized workers.",
                            }
                        ],
                    },
                    {
                        "l2_id": "L2-agent-routing",
                        "label": "agent routing",
                        "linked_obj_ids": ["L1-003", "L1-004"],
                        "timeline_digest": [],
                    },
                ],
            }
            (l2_dir / "l2_view.json").write_text(json.dumps(l2_payload, ensure_ascii=False), encoding="utf-8")
            before = json.dumps(l2_payload, sort_keys=True)

            report = propose_induction_review(
                run_root=run_root,
                profile=profile,
                model="fake-model",
                client=_FakeProposalClient(),
            )

            self.assertEqual(report["status"], "llm_induction_proposals_written")
            self.assertEqual(report["accepted_counts"]["split_candidates"], 1)
            self.assertTrue((run_root / "l2" / "llm_induction_proposals.json").exists())
            self.assertTrue(list((run_root / "api_calls").glob("*induction_proposal*.json")))
            after = json.dumps(load_json(l2_dir / "l2_view.json"), sort_keys=True)
            self.assertEqual(after, before)

    def test_llm_proposal_validation_rejects_generic_or_unreferenced_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "proposal_validation"
            l2_dir = run_root / "l2"
            l2_dir.mkdir(parents=True, exist_ok=True)
            (run_root / "input_snapshot").mkdir(parents=True, exist_ok=True)
            (run_root / "input_snapshot" / "tree.json").write_text(
                json.dumps(
                    {
                        "meetings": [
                            _meeting(
                                "M01",
                                "2026-05-01",
                                [
                                    _obj("L1-001", "finding", "Manager agent routes retrieval work."),
                                    _obj("L1-002", "finding", "Worker coordination handles retrieval subtasks."),
                                ],
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (l2_dir / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-manager-agent",
                                "label": "manager agent",
                                "linked_obj_ids": ["L1-001", "L1-002"],
                                "timeline_digest": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (l2_dir / "llm_induction_proposals.json").write_text(
                json.dumps(
                    {
                        "merge_candidates": [],
                        "split_candidates": [
                            {
                                "source_l2_id": "L2-manager-agent",
                                "proposed_child_labels": ["system", "retrieval routing"],
                                "confidence": 0.9,
                                "rationale": "One child is too generic and must be rejected.",
                                "representative_l1_ids": ["L1-001"],
                            },
                            {
                                "source_l2_id": "L2-manager-agent",
                                "proposed_child_labels": ["retrieval routing", "worker coordination"],
                                "confidence": 0.82,
                                "rationale": "Supported split with real representative evidence.",
                                "representative_l1_ids": ["L1-001", "L1-002"],
                            },
                        ],
                        "assignment_concerns": [
                            {
                                "obj_id": "L1-999",
                                "l2_id": "L2-manager-agent",
                                "confidence": 0.8,
                                "rationale": "Unknown object should be rejected.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            profile = load_profile(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml")

            report = validate_llm_proposals(run_root=run_root, profile=profile)

            self.assertEqual(report["accepted_count"], 1)
            self.assertEqual(report["rejected_count"], 2)
            self.assertTrue((l2_dir / "llm_proposal_validation.json").exists())
            self.assertTrue((l2_dir / "llm_proposal_review_queue.json").exists())
            rejection_reasons = {row["rejection_reason"] for row in report["proposals"] if row["validation_status"] == "rejected"}
            self.assertIn("generic_or_type_like_label", rejection_reasons)
            self.assertIn("unknown_references", rejection_reasons)

    def test_related_topics_ablation_root_removes_related_topics_without_mutating_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            out_root = base / "optimization" / "runs" / "ablation_input"
            tree = _share_tree()
            for meeting in tree["meetings"]:
                for obj in meeting["memory_objects"]:
                    obj["related_topics"] = ["should disappear"]
            _write_share_root(share_root, tree)
            before = json.dumps(load_json(share_root / "tree.json"), ensure_ascii=False, sort_keys=True)

            report = create_related_topics_ablation_root(share_mem_root=share_root, out_root=out_root)

            self.assertTrue((out_root / "tree.json").exists())
            ablated = load_json(out_root / "tree.json")
            self.assertTrue(
                all(
                    obj.get("related_topics") == []
                    for meeting in ablated["meetings"]
                    for obj in meeting["memory_objects"]
                )
            )
            self.assertEqual(report["cleared_related_topics_count"], 25)
            after = json.dumps(load_json(share_root / "tree.json"), ensure_ascii=False, sort_keys=True)
            self.assertEqual(after, before)

    def test_answer_quality_report_compares_v2_against_canonical_and_rag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "answer_quality"
            rows = [
                {
                    "query_id": "q001",
                    "query": "Why split transcripts into idea units?",
                    "strategy": "rag_baseline",
                    "answer": "RAG retrieved chunks.",
                    "retrieved_context": "chunk context",
                    "scores": {
                        "factual_correctness": 0.7,
                        "evidence_grounding": 0.6,
                        "topic_evolution": 0.4,
                        "completeness": 0.55,
                        "conciseness": 0.8,
                        "hallucination_risk": 0.2,
                        "source_traceability": 0.5,
                    },
                    "scoring_rationale": "RAG has limited evolution context.",
                    "token_usage": {"estimated_context_tokens": 1000},
                    "latency_ms": 15,
                },
                {
                    "query_id": "q001",
                    "query": "Why split transcripts into idea units?",
                    "strategy": "canonical_layered",
                    "answer": "Canonical answer.",
                    "retrieved_context": "canonical context",
                    "scores": {
                        "factual_correctness": 0.75,
                        "evidence_grounding": 0.76,
                        "topic_evolution": 0.65,
                        "completeness": 0.7,
                        "conciseness": 0.72,
                        "hallucination_risk": 0.18,
                        "source_traceability": 0.7,
                    },
                    "scoring_rationale": "Canonical is grounded.",
                    "token_usage": {"estimated_context_tokens": 2500},
                    "latency_ms": 20,
                },
                {
                    "query_id": "q001",
                    "query": "Why split transcripts into idea units?",
                    "strategy": "optimization_v2_deterministic",
                    "answer": "V2 answer.",
                    "retrieved_context": "v2 context",
                    "scores": {
                        "factual_correctness": 0.8,
                        "evidence_grounding": 0.82,
                        "topic_evolution": 0.78,
                        "completeness": 0.74,
                        "conciseness": 0.73,
                        "hallucination_risk": 0.15,
                        "source_traceability": 0.84,
                    },
                    "scoring_rationale": "V2 has evidence and topic evolution.",
                    "token_usage": {"estimated_context_tokens": 2700},
                    "latency_ms": 22,
                },
                {
                    "query_id": "q001",
                    "query": "Why split transcripts into idea units?",
                    "strategy": "full_context",
                    "answer": "Full context answer.",
                    "retrieved_context": "full context",
                    "scores": {
                        "factual_correctness": 0.82,
                        "evidence_grounding": 0.7,
                        "topic_evolution": 0.7,
                        "completeness": 0.82,
                        "conciseness": 0.45,
                        "hallucination_risk": 0.18,
                        "source_traceability": 0.42,
                    },
                    "scoring_rationale": "Full context is verbose.",
                    "token_usage": {"estimated_context_tokens": 9000},
                    "latency_ms": 50,
                },
            ]

            report = evaluate_answer_quality(run_root=run_root, scored_rows=rows)

            self.assertEqual(report["status"], "pass")
            self.assertGreaterEqual(
                report["summary"]["optimization_v2_deterministic"]["average_overall_score"],
                report["summary"]["canonical_layered"]["average_overall_score"],
            )
            self.assertGreater(
                report["summary"]["optimization_v2_deterministic"]["average_dimensions"]["source_traceability"],
                report["summary"]["full_context"]["average_dimensions"]["source_traceability"],
            )
            self.assertTrue((run_root / "answer_quality" / "answer_quality_report.json").exists())
            self.assertTrue((run_root / "answer_quality" / "failure_cases.json").exists())

    def test_answer_quality_can_read_existing_csv_score_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "answer_quality_csv"
            csv_path = Path(tmp) / "scores.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "question_id,method,question,response,factuality_score,completeness_score,hallucination_control_score,evidence_grounding_score,context_specificity_score,temporal_evolution_score,judge_notes,judge_input_tokens,judge_output_tokens,judge_total_tokens,judge_token_source",
                        "q1,Structured,Why?,Answer,0.8,0.7,0.9,0.8,0.7,0.8,ok,10,5,15,actual",
                        "q1,RAG,Why?,Answer,0.7,0.6,0.8,0.6,0.6,0.5,ok,8,4,12,actual",
                    ]
                ),
                encoding="utf-8",
            )

            report = evaluate_answer_quality(run_root=run_root, scored_path=csv_path)

            self.assertEqual(report["summary"]["canonical_layered"]["query_count"], 1)
            self.assertEqual(report["summary"]["rag_baseline"]["query_count"], 1)
            self.assertEqual(report["status"], "warning")
            self.assertIn("missing_optimization_v2_strategy", report["gate_reasons"])

    def test_answer_quality_v2_rows_estimate_context_tokens_from_context(self) -> None:
        usage = _context_token_usage("這是一段 retrieved context with evidence.")

        self.assertGreater(usage["estimated_context_tokens"], 0)
        self.assertEqual(usage["token_source"], "estimated")
        self.assertIsNone(usage["actual_input_tokens"])

    def test_manual_review_protocol_and_certification_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            run_root = base / "optimization" / "runs" / "fixture_v2"
            _write_share_root(share_root)
            build_view(
                share_mem_root=share_root,
                profile_path=REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml",
                out_root=run_root,
                mode="deterministic",
                clean=True,
            )
            validate_run(run_root=run_root)
            compare_dir = run_root / "comparison"
            compare_dir.mkdir(parents=True, exist_ok=True)
            (compare_dir / "baseline_vs_v2_l2.json").write_text(
                json.dumps(
                    {
                        "baseline_high_importance_linked_rate": 0.9,
                        "v2_high_importance_linked_rate": 1.0,
                        "changed_high_importance_l1_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            eval_dir = run_root / "retrieval_eval"
            eval_dir.mkdir(parents=True, exist_ok=True)
            (eval_dir / "retrieval_eval_report.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "avg_expected_obj_recall_at_context": 0.9,
                            "expected_l2_semantic_hit_rate": 0.25,
                            "expected_l3_semantic_hit_rate": 1.0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            native_eval_dir = run_root / "retrieval_eval_v2_native"
            native_eval_dir.mkdir(parents=True, exist_ok=True)
            (native_eval_dir / "retrieval_eval_report.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "avg_expected_obj_recall_at_context": 0.9,
                            "expected_l2_semantic_hit_rate": 1.0,
                            "expected_l3_semantic_hit_rate": 1.0,
                        }
                    }
                ),
                encoding="utf-8",
            )

            protocol = generate_manual_review_protocol(run_root=run_root, out_dir=run_root / "manual_review")
            cert = certify_maturity(
                grace_run_root=run_root,
                ablation_run_root=run_root,
                out_dir=run_root / "certification",
                core_root=REPO_ROOT / "optimization" / "long_term_v2",
            )

            self.assertTrue((run_root / "manual_review" / "manual_review_protocol.json").exists())
            self.assertGreater(protocol["review_item_count"], 0)
            self.assertTrue((run_root / "certification" / "maturity_certification_report.json").exists())
            self.assertIn("gate_results", cert)
            self.assertEqual(cert["gate_results"]["gate_1_isolation"]["status"], "pass")
            self.assertEqual(cert["gate_results"]["gate_2_no_grace_specific_core"]["status"], "pass")
            self.assertEqual(
                cert["gate_results"]["gate_8_retrieval_quality"]["retrieval"]["semantic_eval_source"],
                "retrieval_eval_v2_native",
            )
            ablation_gate = cert["gate_results"]["gate_2_related_topics_ablation"]
            self.assertEqual(ablation_gate["status"], "pass")
            self.assertIn("gate_semantics", ablation_gate)
            self.assertTrue(ablation_gate["ablation_gate_checks"]["high_importance_linked_rate_at_least_0_95"])

    def test_manual_review_protocol_samples_semantic_rescue_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            run_root = base / "optimization" / "runs" / "rescue_review"
            recurring = [
                _obj(
                    f"L1-EVAL-{index}",
                    "finding",
                    "The evaluation framework uses benchmark questions, retrieval baselines, and answer quality scoring.",
                    evidence="The mentor discussed benchmark questions and retrieval baselines for answer quality evaluation.",
                    importance=0.72,
                    topics=[],
                )
                for index in range(1, 5)
            ]
            related_singleton = _obj(
                "L1-EVAL-SINGLE",
                "argument",
                "A LOCOMO benchmark result should be used in the answer quality evaluation baseline for multi-hop questions.",
                evidence="The team used this prior paper benchmark to reason about answer quality evaluation and baseline tradeoffs.",
                importance=0.63,
                topics=[],
            )
            _write_share_root(
                share_root,
                {
                    "tree_version": 1,
                    "last_updated_utc": "2026-05-28T00:00:00Z",
                    "project_profile": {},
                    "phases": [],
                    "meetings": [_meeting("M1", "2026-05-01", recurring + [related_singleton])],
                },
            )
            build_view(
                share_mem_root=share_root,
                profile_path=REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml",
                out_root=run_root,
                mode="deterministic",
                clean=True,
            )
            validate_run(run_root=run_root)

            protocol = generate_manual_review_protocol(run_root=run_root, out_dir=run_root / "manual_review")

            rescue_items = protocol.get("semantic_rescue_assignment_sample", [])
            self.assertTrue(rescue_items)
            self.assertEqual(rescue_items[0]["obj_id"], "L1-EVAL-SINGLE")

    def test_manual_review_finalization_requires_valid_decisions_and_blocks_severe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "manual_review"
            review_dir = run_root / "manual_review"
            review_dir.mkdir(parents=True, exist_ok=True)
            (review_dir / "manual_review_protocol.json").write_text(
                json.dumps(
                    {
                        "required_labels": ["correct", "wrong_assignment", "generic_bucket"],
                        "high_importance_linked_l1_sample": [{"obj_id": "L1-001"}],
                    }
                ),
                encoding="utf-8",
            )
            (review_dir / "review_decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "review_id": "RV-0001",
                                "item_type": "l2_topic",
                                "item_id": "L2-good",
                                "decision": "correct",
                                "severity": "none",
                                "reason": "Evidence is coherent.",
                                "reviewer": "human",
                                "created_at_utc": "2026-05-29T00:00:00Z",
                            }
                        ),
                        json.dumps(
                            {
                                "review_id": "RV-0002",
                                "item_type": "l2_topic",
                                "item_id": "L2-bad",
                                "decision": "generic_bucket",
                                "severity": "severe",
                                "reason": "Generic topic bucket.",
                                "reviewer": "human",
                                "created_at_utc": "2026-05-29T00:00:00Z",
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            report = finalize_manual_review(run_root=run_root)

            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["severe_issue_count"], 1)
            self.assertTrue((review_dir / "final_manual_review_report.json").exists())
            self.assertTrue((review_dir / "final_manual_review_report.md").exists())

    def test_manual_review_requires_unlinked_sample_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "manual_review_unlinked"
            review_dir = run_root / "manual_review"
            review_dir.mkdir(parents=True, exist_ok=True)
            (review_dir / "manual_review_protocol.json").write_text(
                json.dumps({"unlinked_l1_sample": [{"obj_id": "L1-unlinked"}]}),
                encoding="utf-8",
            )
            (review_dir / "review_decisions.jsonl").write_text(
                json.dumps(
                    {
                        "review_id": "RV-0001",
                        "item_type": "l2_topic",
                        "item_id": "L2-good",
                        "decision": "correct",
                        "severity": "none",
                        "reason": "Evidence is coherent.",
                        "reviewer": "human",
                        "created_at_utc": "2026-05-29T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            report = finalize_manual_review(run_root=run_root)

            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["missing_high_importance_unlinked_review_count"], 1)

    def test_certification_uses_answer_quality_and_final_manual_review_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            run_root = base / "optimization" / "runs" / "cert_v2"
            _write_share_root(share_root)
            build_view(
                share_mem_root=share_root,
                profile_path=REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml",
                out_root=run_root,
                mode="deterministic",
                clean=True,
            )
            validate_run(run_root=run_root)
            compare_dir = run_root / "comparison"
            compare_dir.mkdir(parents=True, exist_ok=True)
            (compare_dir / "baseline_vs_v2_l2.json").write_text(
                json.dumps(
                    {
                        "baseline_high_importance_linked_rate": 0.9,
                        "v2_high_importance_linked_rate": 1.0,
                        "changed_high_importance_l1_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            native_eval_dir = run_root / "retrieval_eval_v2_native"
            native_eval_dir.mkdir(parents=True, exist_ok=True)
            (native_eval_dir / "retrieval_eval_report.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "avg_expected_obj_recall_at_context": 0.9,
                            "expected_l2_semantic_hit_rate": 1.0,
                            "expected_l3_semantic_hit_rate": 1.0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            retrieval_dir = run_root / "retrieval_eval"
            retrieval_dir.mkdir(parents=True, exist_ok=True)
            (retrieval_dir / "retrieval_eval_report.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "avg_expected_obj_recall_at_context": 0.9,
                            "expected_l2_semantic_hit_rate": 1.0,
                            "expected_l3_semantic_hit_rate": 1.0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            protocol = generate_manual_review_protocol(run_root=run_root, out_dir=run_root / "manual_review")
            review_rows = [
                {
                    "review_id": "RV-0001",
                    "item_type": "l2_topic",
                    "item_id": "L2-topic",
                    "decision": "correct",
                    "severity": "none",
                    "reason": "Reviewed sample is coherent.",
                    "reviewer": "human",
                    "created_at_utc": "2026-05-29T00:00:00Z",
                }
            ]
            for index, sample in enumerate(protocol.get("unlinked_l1_sample", []), start=2):
                review_rows.append(
                    {
                        "review_id": f"RV-{index:04d}",
                        "item_type": "unlinked_l1",
                        "item_id": sample["obj_id"],
                        "decision": "should_unlink_noise",
                        "severity": "none",
                        "reason": "Reviewed unlinked sample is not a durable topic.",
                        "reviewer": "human",
                        "created_at_utc": "2026-05-29T00:00:00Z",
                    }
                )
            (run_root / "manual_review" / "review_decisions.jsonl").write_text(
                "\n".join(json.dumps(row) for row in review_rows),
                encoding="utf-8",
            )
            finalize_manual_review(run_root=run_root)
            evaluate_answer_quality(
                run_root=run_root,
                scored_rows=[
                    {
                        "query_id": "q001",
                        "query": "test",
                        "strategy": "canonical_layered",
                        "scores": {
                            "factual_correctness": 0.7,
                            "evidence_grounding": 0.7,
                            "topic_evolution": 0.7,
                            "completeness": 0.7,
                            "conciseness": 0.7,
                            "hallucination_risk": 0.2,
                            "source_traceability": 0.7,
                        },
                    },
                    {
                        "query_id": "q001",
                        "query": "test",
                        "strategy": "rag_baseline",
                        "scores": {
                            "factual_correctness": 0.6,
                            "evidence_grounding": 0.6,
                            "topic_evolution": 0.4,
                            "completeness": 0.6,
                            "conciseness": 0.8,
                            "hallucination_risk": 0.25,
                            "source_traceability": 0.5,
                        },
                    },
                    {
                        "query_id": "q001",
                        "query": "test",
                        "strategy": "full_context",
                        "scores": {
                            "factual_correctness": 0.75,
                            "evidence_grounding": 0.7,
                            "topic_evolution": 0.6,
                            "completeness": 0.75,
                            "conciseness": 0.5,
                            "hallucination_risk": 0.2,
                            "source_traceability": 0.4,
                        },
                    },
                    {
                        "query_id": "q001",
                        "query": "test",
                        "strategy": "optimization_v2_deterministic",
                        "scores": {
                            "factual_correctness": 0.8,
                            "evidence_grounding": 0.8,
                            "topic_evolution": 0.8,
                            "completeness": 0.75,
                            "conciseness": 0.7,
                            "hallucination_risk": 0.18,
                            "source_traceability": 0.85,
                        },
                    },
                ],
            )
            suite_root = base / "optimization" / "runs" / "suite"
            suite_root.mkdir(parents=True, exist_ok=True)
            (suite_root / "suite_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "pass",
                        "dataset_count": 1,
                        "failed_datasets": [],
                    }
                ),
                encoding="utf-8",
            )

            cert = certify_maturity(
                grace_run_root=run_root,
                out_dir=run_root / "certification",
                core_root=REPO_ROOT / "optimization" / "long_term_v2",
                suite_root=suite_root,
            )

            self.assertEqual(cert["gate_results"]["gate_9_answer_quality_evaluation"]["status"], "pass")
            self.assertEqual(cert["gate_results"]["gate_11_manual_review_completion"]["status"], "pass")
            self.assertEqual(cert["gate_results"]["gate_10_cross_dataset_maturity_suite"]["status"], "pass")
            self.assertEqual(cert["cross_dataset_suite"]["dataset_count"], 1)
            self.assertEqual(cert["status"], "warning")

    def test_certification_can_include_split_candidate_application_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            run_root = base / "optimization" / "runs" / "cert_candidate"
            candidate_root = base / "optimization" / "runs" / "split_candidate"
            _write_share_root(share_root)
            build_view(
                share_mem_root=share_root,
                profile_path=REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml",
                out_root=run_root,
                mode="deterministic",
                clean=True,
            )
            validate_run(run_root=run_root)
            compare_dir = run_root / "comparison"
            compare_dir.mkdir(parents=True, exist_ok=True)
            (compare_dir / "baseline_vs_v2_l2.json").write_text(
                json.dumps(
                    {
                        "baseline_high_importance_linked_rate": 0.9,
                        "v2_high_importance_linked_rate": 1.0,
                        "changed_high_importance_l1_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            retrieval_dir = run_root / "retrieval_eval"
            retrieval_dir.mkdir(parents=True, exist_ok=True)
            (retrieval_dir / "retrieval_eval_report.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "avg_expected_obj_recall_at_context": 0.9,
                            "expected_l2_semantic_hit_rate": 1.0,
                            "expected_l3_semantic_hit_rate": 1.0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            shutil.copytree(run_root, candidate_root)
            (candidate_root / "l3" / "applied_split_review_candidates.json").write_text(
                json.dumps(
                    {
                        "status": "candidate_splits_applied",
                        "applied_split_count": 1,
                        "skipped_split_count": 1,
                        "applied_splits": [{"source_l2_id": "L2-a"}],
                        "skipped_splits": [{"source_l2_id": "L2-b", "reason": "candidate_child_still_oversized"}],
                    }
                ),
                encoding="utf-8",
            )
            (candidate_root / "reports").mkdir(parents=True, exist_ok=True)
            (candidate_root / "reports" / "retrieval_split_pressure.json").write_text(
                json.dumps(
                    {
                        "query_count": 2,
                        "needs_split_topic_count": 3,
                        "topics_with_retrieval_pressure_count": 1,
                        "topics": [{"l2_id": "L2-large", "retrieval_query_count": 2}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            cert = certify_maturity(
                grace_run_root=run_root,
                out_dir=run_root / "certification",
                core_root=REPO_ROOT / "optimization" / "long_term_v2",
                split_candidate_run_root=candidate_root,
            )

            gate = cert["gate_results"]["gate_7_split_candidate_application"]
            self.assertEqual(gate["status"], "pass")
            self.assertEqual(gate["split_candidate_application"]["applied_split_count"], 1)
            self.assertEqual(gate["split_candidate_application"]["severe_count"], 0)
            self.assertEqual(cert["retrieval_split_pressure"]["query_count"], 2)
            self.assertEqual(cert["retrieval_split_pressure"]["topics_with_retrieval_pressure_count"], 1)

    def test_retrieval_split_pressure_report_ranks_needs_split_topics_used_by_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "pressure"
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            (run_root / "l3").mkdir(parents=True, exist_ok=True)
            (run_root / "retrieval_eval").mkdir(parents=True, exist_ok=True)
            (run_root / "l3" / "l2_merge_review.json").write_text(
                json.dumps(
                    {
                        "merge_reviews": [
                            {"action": "needs_split_review", "source_l2_id": "L2-a", "source_event_count": 80},
                            {"action": "needs_split_review", "source_l2_id": "L2-b", "source_event_count": 50},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {"l2_id": "L2-a", "label": "alpha topic", "linked_obj_ids": ["L1-a"] * 80},
                            {"l2_id": "L2-b", "label": "beta topic", "linked_obj_ids": ["L1-b"] * 50},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "retrieval_eval" / "retrieval_eval_report.json").write_text(
                json.dumps(
                    {
                        "queries": [
                            {"query_id": "q001", "selected_l2_ids": ["L2-a"], "selected_l2_labels": ["alpha topic"]},
                            {"query_id": "q002", "selected_l2_ids": ["L2-a", "L2-b"], "selected_l2_labels": ["alpha topic", "beta topic"]},
                            {"query_id": "q003", "selected_l2_ids": [], "selected_l2_labels": []},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_retrieval_split_pressure_report(run_root=run_root)

            self.assertEqual(report["topics"][0]["l2_id"], "L2-a")
            self.assertEqual(report["topics"][0]["retrieval_query_count"], 2)
            self.assertEqual(report["topics"][1]["l2_id"], "L2-b")
            self.assertTrue((run_root / "reports" / "retrieval_split_pressure.json").exists())

    def test_retrieval_pressure_queries_are_generated_from_needs_split_l2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "synthetic"
            (run_root / "input_snapshot").mkdir(parents=True, exist_ok=True)
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            (run_root / "l3").mkdir(parents=True, exist_ok=True)
            tree = {
                "meetings": [
                    _meeting(
                        "SYN-001",
                        "2026-05-01",
                        [
                            _obj(
                                "L1-SYN-001-001",
                                "finding",
                                "Child L2 splitting needs evidence-backed criteria and reviewer validation.",
                                topics=["child l2"],
                            ),
                            _obj(
                                "L1-SYN-001-002",
                                "argument",
                                "Child L2 should not be split when the evidence remains one coherent topic.",
                                topics=["child l2"],
                            ),
                        ],
                    )
                ]
            }
            (run_root / "input_snapshot" / "tree.json").write_text(
                json.dumps(tree, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-child-l2",
                                "label": "child l2",
                                "linked_obj_ids": ["L1-SYN-001-001", "L1-SYN-001-002"],
                                "definition": "Evidence about child L2 split decisions.",
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (run_root / "l3" / "l2_merge_review.json").write_text(
                json.dumps(
                    {
                        "merge_reviews": [
                            {
                                "source_l2_id": "L2-child-l2",
                                "source_l2_label": "child l2",
                                "source_event_count": 42,
                                "action": "needs_split_review",
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            report = build_retrieval_pressure_queries(run_root=run_root, max_topics=1)

            self.assertEqual(report["query_count"], 1)
            query = report["queries"][0]
            self.assertEqual(query["expected_l2_ids"], ["L2-child-l2"])
            self.assertEqual(query["expected_l2_labels"], ["child l2"])
            self.assertIn("Child L2", query["query"])
            self.assertEqual(query["expected_obj_ids"], ["L1-SYN-001-001", "L1-SYN-001-002"])
            self.assertTrue((run_root / "retrieval_eval" / "pressure_queries.jsonl").exists())

    def test_curate_v2_native_queries_uses_representative_l1_and_l2_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "native_queries"
            (run_root / "input_snapshot").mkdir(parents=True, exist_ok=True)
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            tree = {
                "meetings": [
                    _meeting(
                        "SYN-001",
                        "2026-05-01",
                        [
                            _obj(
                                "L1-SYN-001-001",
                                "finding",
                                "The mentor and mentee discussed evaluation evidence and review protocol.",
                                topics=["evaluation evidence"],
                            ),
                            _obj(
                                "L1-SYN-001-002",
                                "open_issue",
                                "The group still needed a clearer answer-quality rubric.",
                                topics=["evaluation evidence"],
                            ),
                        ],
                    )
                ]
            }
            (run_root / "input_snapshot" / "tree.json").write_text(
                json.dumps(tree, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_root / "l2" / "l2_view.json").write_text(
                json.dumps(
                    {
                        "l2_nodes": [
                            {
                                "l2_id": "L2-evaluation-evidence",
                                "label": "evaluation evidence",
                                "definition": "Evidence-backed evaluation protocol discussion.",
                                "representative_l1_ids": ["L1-SYN-001-001"],
                                "linked_obj_ids": ["L1-SYN-001-001", "L1-SYN-001-002"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            report = curate_v2_native_queries(run_root=run_root, topic_source="largest", max_queries=1)

            self.assertEqual(report["query_count"], 1)
            query = report["queries"][0]
            self.assertIn("evaluation evidence", query["query"])
            self.assertEqual(query["expected_l2_ids"], ["L2-evaluation-evidence"])
            self.assertEqual(query["expected_l2_labels"], ["evaluation evidence"])
            self.assertEqual(query["expected_obj_ids"], ["L1-SYN-001-001", "L1-SYN-001-002"])
            self.assertTrue((run_root / "retrieval_eval" / "v2_native_queries.jsonl").exists())

    def test_professor_delivery_report_summarizes_maturity_and_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "optimization" / "reports" / "delivery"
            certification = {
                "status": "warning",
                "failing_gates": [],
                "warning_gates": ["gate_12_promotion_decision"],
                "gate_results": {
                    "gate_1_isolation": {"status": "pass"},
                    "gate_2_no_grace_specific_core": {"status": "pass", "match_count": 0},
                    "gate_3_l1_input_audit": {
                        "status": "pass",
                        "comparison": {
                            "baseline_high_importance_linked_rate": 0.9577,
                            "v2_high_importance_linked_rate": 1.0,
                        },
                    },
                    "gate_5_l2_topic_quality": {
                        "status": "pass",
                        "validation": {"severe_count": 0, "warning_count": 2},
                    },
                    "gate_8_retrieval_quality": {
                        "status": "pass",
                        "retrieval": {
                            "avg_expected_obj_recall_at_context": 0.8728,
                            "expected_l2_semantic_hit_rate": 1.0,
                            "expected_l3_semantic_hit_rate": 0.5,
                        },
                    },
                    "gate_9_answer_quality_evaluation": {
                        "status": "pass",
                        "answer_quality": {
                            "summary": {
                                "canonical_layered": {
                                    "average_overall_score": 0.85,
                                    "average_context_tokens": 10262.6667,
                                },
                                "optimization_v2_deterministic": {
                                    "average_overall_score": 0.8905,
                                    "average_context_tokens": 3685.3333,
                                },
                                "rag_baseline": {
                                    "average_overall_score": 0.4286,
                                    "average_context_tokens": 20197.3333,
                                },
                                "full_context": {
                                    "average_overall_score": 0.2857,
                                    "average_context_tokens": 98531.0,
                                },
                            },
                            "failure_case_count": 4,
                        },
                    },
                    "gate_10_cross_dataset_maturity_suite": {
                        "status": "pass",
                        "suite": {"dataset_count": 3, "failed_dataset_count": 0},
                    },
                    "gate_11_manual_review_completion": {
                        "status": "pass",
                        "manual_review": {
                            "decision_count": 43,
                            "severe_issue_count": 0,
                            "wrong_assignment_rate": 0.0465,
                        },
                    },
                    "gate_12_promotion_decision": {
                        "status": "warning",
                        "promotion_recommendation": "eligible_for_shadow_mode_only",
                    },
                },
            }
            diagnostics = {
                "summary": [
                    {
                        "dataset": "synthetic_candidate_needs_split",
                        "query_count": 12,
                        "avg_expected_obj_recall_at_context": 0.625,
                        "expected_l2_semantic_hit_rate": 1.0,
                    },
                    {
                        "dataset": "icsi_5file_largest_topics",
                        "query_count": 8,
                        "avg_expected_obj_recall_at_context": 1.0,
                        "expected_l2_semantic_hit_rate": 1.0,
                    },
                ],
            }

            report = build_professor_delivery_report(
                certification=certification,
                v2_native_diagnostics=diagnostics,
                out_dir=out_dir,
            )

            self.assertEqual(report["deliverability_status"], "deliverable_shadow_mode")
            self.assertEqual(report["promotion_boundary"], "do_not_promote_to_canonical")
            self.assertEqual(report["core_evidence"]["failing_gate_count"], 0)
            self.assertEqual(report["answer_quality"]["best_strategy"], "optimization_v2_deterministic")
            self.assertEqual(report["cross_dataset"]["dataset_count"], 3)
            self.assertEqual(len(report["talking_points"]), 5)
            self.assertTrue((out_dir / "professor_delivery_report.json").exists())
            md = (out_dir / "professor_delivery_report.md").read_text(encoding="utf-8")
            self.assertIn("Optimization v2 Delivery Report", md)
            self.assertIn("do_not_promote_to_canonical", md)

    def test_professor_delivery_report_cli_runs_from_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cert_path = base / "certification.json"
            diagnostics_path = base / "diagnostics.json"
            out_dir = base / "optimization" / "reports" / "delivery"
            cert_path.write_text(
                json.dumps(
                    {
                        "status": "warning",
                        "failing_gates": [],
                        "warning_gates": ["gate_12_promotion_decision"],
                        "gate_results": {
                            "gate_1_isolation": {"status": "pass"},
                            "gate_2_no_grace_specific_core": {"status": "pass", "match_count": 0},
                            "gate_9_answer_quality_evaluation": {
                                "status": "pass",
                                "answer_quality": {
                                    "summary": {
                                        "canonical_layered": {"average_overall_score": 0.8},
                                        "optimization_v2_deterministic": {"average_overall_score": 0.9},
                                    }
                                },
                            },
                            "gate_10_cross_dataset_maturity_suite": {
                                "status": "pass",
                                "suite": {"dataset_count": 1, "failed_dataset_count": 0},
                            },
                            "gate_11_manual_review_completion": {
                                "status": "pass",
                                "manual_review": {"decision_count": 1, "severe_issue_count": 0},
                            },
                            "gate_12_promotion_decision": {"status": "warning"},
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            diagnostics_path.write_text(json.dumps({"summary": []}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "optimization/long_term_v2/make_professor_delivery_report.py",
                    "--certification-report",
                    str(cert_path),
                    "--v2-native-diagnostics",
                    str(diagnostics_path),
                    "--out",
                    str(out_dir),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((out_dir / "professor_delivery_report.md").exists())

    def test_retrieval_eval_report_keeps_expected_ids_for_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            run_root = base / "optimization" / "runs" / "eval"
            _write_share_root(
                share_root,
                {
                    "meetings": [
                        _meeting(
                            "SYN-001",
                            "2026-05-01",
                            [
                                _obj(
                                    "L1-SYN-001-001",
                                    "finding",
                                    "Evidence-backed topic splitting improves retrieval review.",
                                    topics=["topic splitting"],
                                )
                            ],
                        )
                    ]
                },
            )
            (run_root / "l2").mkdir(parents=True, exist_ok=True)
            (run_root / "l3").mkdir(parents=True, exist_ok=True)
            (run_root / "l2" / "l2_index.json").write_text(
                json.dumps(
                    {
                        "L1-SYN-001-001": {
                            "l2_id": "L2-topic-splitting",
                            "l2_label": "topic splitting",
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            queries_path = base / "queries.jsonl"
            queries_path.write_text(
                json.dumps(
                    {
                        "query": "topic splitting retrieval review",
                        "expected_obj_ids": ["L1-SYN-001-001"],
                        "expected_l2_ids": ["L2-topic-splitting"],
                        "expected_l2_labels": ["topic splitting"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = evaluate_retrieval(run_root=run_root, queries_path=queries_path, share_mem_root=share_root)

            row = report["queries"][0]
            self.assertEqual(row["expected_obj_ids"], ["L1-SYN-001-001"])
            self.assertEqual(row["matched_expected_obj_ids"], ["L1-SYN-001-001"])
            self.assertEqual(row["expected_l2_ids"], ["L2-topic-splitting"])
            self.assertEqual(row["expected_l2_labels"], ["topic splitting"])

    def test_validate_run_flags_l1_mojibake_text_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_root = base / "optimization" / "runs" / "mojibake"
            share_root = base / "share_mem"
            _write_share_root(
                share_root,
                {
                    "meetings": [
                        _meeting(
                            "SYN-001",
                            "2026-05-01",
                            [
                                _obj(
                                    "L1-SYN-001-001",
                                    "finding",
                                    "??SYN-001 銝哨??\ue93a?? garbled transcript evidence",
                                    topics=["garbled text"],
                                )
                            ],
                        )
                    ]
                },
            )
            build_view(
                share_mem_root=share_root,
                profile_path=REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml",
                out_root=run_root,
                mode="deterministic",
                clean=True,
            )

            report = validate_run(run_root=run_root)
            audit = load_json(run_root / "validation" / "l1_input_audit.json")

            self.assertGreaterEqual(audit["text_quality"]["suspect_mojibake_count"], 1)
            self.assertTrue(any(issue["code"] == "l1_text_quality_mojibake" for issue in report["issues"]))

    def test_maturity_suite_writes_summary_under_optimization_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            suite_root = base / "optimization" / "runs" / "maturity_suite"
            _write_share_root(share_root)

            report = run_maturity_suite(
                suite_root=suite_root,
                datasets=[
                    {
                        "dataset_id": "fixture",
                        "share_mem_root": str(share_root),
                        "profile": str(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml"),
                        "run_llm": False,
                    }
                ],
                clean=True,
            )

            self.assertEqual(report["dataset_count"], 1)
            self.assertEqual(report["datasets"][0]["name"], "fixture")
            self.assertTrue((suite_root / "suite_manifest.json").exists())
            self.assertTrue((suite_root / "suite_summary.json").exists())
            self.assertFalse((share_root / "suite_summary.json").exists())

    def test_maturity_suite_config_loader_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            datasets_path = Path(tmp) / "datasets.json"
            datasets_path.write_text(
                "\ufeff" + json.dumps([{"dataset_id": "fixture", "share_mem_root": "share_mem"}]),
                encoding="utf-8",
            )

            datasets = load_datasets_config(datasets_path)

            self.assertEqual(datasets[0]["dataset_id"], "fixture")

    def test_cli_smoke_writes_run_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share_root = base / "share_mem"
            run_root = base / "optimization" / "runs" / "cli_v2"
            _write_share_root(share_root)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "optimization" / "long_term_v2" / "build_view.py"),
                    "--share-mem-root",
                    str(share_root),
                    "--profile",
                    str(REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml"),
                    "--out",
                    str(run_root),
                    "--mode",
                    "deterministic",
                    "--clean",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((run_root / "manifest.json").exists())
            self.assertFalse((share_root / "l2_view.json").exists())


if __name__ == "__main__":
    unittest.main()
