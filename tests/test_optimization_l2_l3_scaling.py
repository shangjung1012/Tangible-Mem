from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from optimization.long_term_v2.audit_topic_quality import audit_topic_quality
from optimization.long_term_v2.apply_split_review_candidates import apply_split_review_candidates
from optimization.long_term_v2.cross_dataset_suite import run_cross_dataset_suite
from optimization.long_term_v2.compare_topic_candidates import compare_topic_candidates
from optimization.long_term_v2.io_utils import load_json
from optimization.long_term_v2.llm_split_review import propose_focused_split_review
from optimization.long_term_v2.build_view import build_view
from optimization.long_term_v2.profiles import load_profile
from optimization.long_term_v2.promote_l3 import build_l3_view


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCOMO_STYLE_FIXTURE_ROOT = REPO_ROOT / "optimization" / "long_term_v2" / "fixtures" / "locomo_style_share_mem"
LOCOMO_PROFILE = REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "conversation_memory.yaml"
MENTOR_PROFILE = REPO_ROOT / "optimization" / "long_term_v2" / "profiles" / "mentor_mentee.yaml"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _obj(obj_id: str, content: str, *, importance: float = 0.72, topics: list[str] | None = None) -> dict:
    return {
        "obj_id": obj_id,
        "type": "finding",
        "legacy_type": "result",
        "content": content,
        "importance": importance,
        "evidence": content,
        "related_topics": topics or [],
        "related_obj_ids": [],
    }


def _share_root(root: Path, meeting_prefix: str, objects: list[dict]) -> Path:
    meeting = {
        "meeting_id": meeting_prefix,
        "timestamp": "2026-01-01T00:00:00Z",
        "meeting_date": "2026-01-01",
        "source_file": f"{meeting_prefix}.txt",
        "phase_id": "",
        "memory_objects": objects,
    }
    tree = {
        "tree_version": 1,
        "last_updated_utc": "2026-01-01T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [meeting],
    }
    _write_json(root / "tree.json", tree)
    return root


def _minimal_run_root(root: Path) -> Path:
    run = root / "optimization" / "runs" / "audit_fixture"
    l2_nodes = [
        {
            "l2_id": "L2-data-source",
            "label": "data source",
            "linked_obj_ids": ["L1-001", "L1-002", "L1-003", "L1-004"],
            "meeting_ids": ["M001", "M002"],
            "timeline_digest": [
                {
                    "meeting_id": "M001",
                    "meeting_date": "2026-01-01",
                    "obj_id": "L1-001",
                    "summary": "Aurora digit reading source task was selected for data collection.",
                },
                {
                    "meeting_id": "M001",
                    "meeting_date": "2026-01-01",
                    "obj_id": "L1-002",
                    "summary": "Collaboration data vetting needed a different evidence source.",
                },
                {
                    "meeting_id": "M002",
                    "meeting_date": "2026-01-02",
                    "obj_id": "L1-003",
                    "summary": "Spontaneous speech inference required conversational material.",
                },
                {
                    "meeting_id": "M002",
                    "meeting_date": "2026-01-02",
                    "obj_id": "L1-004",
                    "summary": "Backchannel inference was framed as an annotation data source.",
                },
            ],
            "top_semantic_terms": [
                {"term": "aurora digit", "object_count": 1},
                {"term": "collaboration vetting", "object_count": 1},
                {"term": "spontaneous speech", "object_count": 1},
                {"term": "backchannel inference", "object_count": 1},
            ],
        }
    ]
    _write_json(run / "manifest.json", {"source_l1_count": 4})
    _write_json(run / "l2" / "l2_view.json", {"l2_nodes": l2_nodes})
    _write_json(run / "l2" / "l2_index.json", {})
    _write_json(run / "l3" / "l3_view.json", {"l3_parents": []})
    _write_json(run / "l3" / "l3_index.json", {})
    return run


def _candidate_run(root: Path, name: str, *, broad_count: int, review_only: list[dict], weak_l3: int = 0) -> Path:
    run = root / "optimization" / "runs" / name
    _write_json(
        run / "manifest.json",
        {
            "source_l1_count": 10,
            "linked_l1_count": 10 - len(review_only),
            "unlinked_l1_count": len(review_only),
            "l2_topic_count": 2,
            "l3_parent_count": 0,
        },
    )
    _write_json(
        run / "l2" / "unlinked_l1_report.json",
        {"unlinked_objects": review_only},
    )
    _write_json(run / "l2" / "l2_view.json", {"l2_nodes": []})
    _write_json(run / "l2" / "l2_index.json", {})
    _write_json(run / "l3" / "l3_view.json", {"l3_parents": []})
    _write_json(
        run / "l3" / "l2_merge_review.json",
        {
            "merge_reviews": [
                {"action": "needs_split_review", "source_l2_id": f"L2-weak-{idx}"}
                for idx in range(weak_l3)
            ]
        },
    )
    _write_json(
        run / "topic_quality" / "topic_quality_report.json",
        {
            "issues": [
                {"severity": "warning", "code": "broad_l2_mixed_signatures", "l2_id": f"L2-broad-{idx}"}
                for idx in range(broad_count)
            ],
            "manual_review_count": broad_count,
        },
    )
    return run


class _FakeSplitReviewModels:
    def __init__(self) -> None:
        self.prompt = ""

    def generate_content(self, *, model: str, contents: str, config: dict) -> object:
        self.prompt = contents
        payload = json.loads(contents)
        source = payload["sources"][0]
        reps = [row["obj_id"] for row in source["timeline_sample"][:2]]
        raw = {
            "split_candidates": [
                {
                    "source_l2_id": source["source_l2_id"],
                    "child_candidates": [
                        {
                            "label": "digit task logistics",
                            "assignment_criteria": ["digit", "task", "participant"],
                            "representative_l1_ids": [reps[0]],
                        },
                        {
                            "label": "collaboration data review",
                            "assignment_criteria": ["collaboration", "review", "evidence"],
                            "representative_l1_ids": [reps[1]],
                        },
                    ],
                    "confidence": 0.82,
                    "rationale": "The evidence separates data collection logistics from data review concerns.",
                }
            ],
            "review_only": [],
        }
        return type("FakeResponse", (), {"text": json.dumps(raw)})()


class _FakeSplitReviewClient:
    def __init__(self) -> None:
        self.models = _FakeSplitReviewModels()


class _FakeWrappedSplitReviewModels(_FakeSplitReviewModels):
    def generate_content(self, *, model: str, contents: str, config: dict) -> object:
        base = json.loads(super().generate_content(model=model, contents=contents, config=config).text)
        return type("FakeResponse", (), {"text": json.dumps({"topics": [base]})})()


class _FakeWrappedSplitReviewClient:
    def __init__(self) -> None:
        self.models = _FakeWrappedSplitReviewModels()


class OptimizationL2L3ScalingTests(unittest.TestCase):
    def test_optimization_load_json_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payload.json"
            path.write_text('\ufeff{"ok": true}', encoding="utf-8")

            self.assertEqual(load_json(path), {"ok": True})

    def test_topic_quality_audit_flags_broad_l2_with_multiple_subtopic_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = _minimal_run_root(Path(tmp))

            report = audit_topic_quality(run_root=run_root)

            issue_codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("broad_l2_mixed_signatures", issue_codes)
            self.assertIn("needs_topic_review", issue_codes)

    def test_topic_quality_audit_treats_materialized_child_split_as_mitigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = _minimal_run_root(Path(tmp))
            events = load_json(run_root / "l2" / "l2_view.json")["l2_nodes"][0]["timeline_digest"]
            _write_json(
                run_root / "l3" / "l3_view.json",
                {
                    "l3_parents": [
                        {
                            "l3_id": "L3-data-source-candidate-split",
                            "source_l2_id": "L2-data-source",
                            "label": "data source",
                            "child_l2_nodes": [
                                {
                                    "child_l2_id": "L2-data-source-digit-task",
                                    "label": "digit task sources",
                                    "linked_obj_ids": ["L1-001", "L1-002", "L1-003"],
                                    "timeline_digest": events[:3],
                                },
                                {
                                    "child_l2_id": "L2-data-source-speech-inference",
                                    "label": "speech inference sources",
                                    "linked_obj_ids": ["L1-004", "L1-005", "L1-006"],
                                    "timeline_digest": events[:3],
                                },
                            ],
                        }
                    ]
                },
            )

            report = audit_topic_quality(run_root=run_root)

            broad_source_ids = {
                issue.get("l2_id")
                for issue in report["issues"]
                if issue.get("code") == "broad_l2_mixed_signatures"
            }
            self.assertNotIn("L2-data-source", broad_source_ids)
            summary = report["topic_summaries"][0]
            self.assertEqual(summary["split_mitigation"], "materialized_child_l2_context")

    def test_topic_quality_audit_treats_small_llm_review_only_as_mitigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = _minimal_run_root(Path(tmp))
            _write_json(
                run_root / "l2" / "llm_split_review_proposals.json",
                {
                    "review_only": [
                        {
                            "source_l2_id": "L2-data-source",
                            "reason": "The evidence is a small coherent topic and should not be split into trivial children.",
                            "representative_l1_ids": ["L1-001", "L1-002"],
                        }
                    ]
                },
            )

            report = audit_topic_quality(run_root=run_root)

            broad_source_ids = {
                issue.get("l2_id")
                for issue in report["issues"]
                if issue.get("code") == "broad_l2_mixed_signatures"
            }
            self.assertNotIn("L2-data-source", broad_source_ids)
            summary = report["topic_summaries"][0]
            self.assertEqual(summary["review_disposition_mitigation"], "llm_review_only_small_topic")

    def test_topic_quality_audit_does_not_mitigate_large_llm_review_only_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "optimization" / "runs" / "large_review_only"
            summaries = [
                "Aurora digit reading protocol selected numeric prompts for participant sessions.",
                "Beamforming microphone array estimated speaker position from close sensors.",
                "Consent form metadata captured participant affiliation and education category.",
                "Overlap timing analysis normalized overlappee counts by total speaking time.",
                "External transcription sponsor changed staffing assumptions for annotation work.",
                "Noise projector environment affected acoustic recordings in the meeting room.",
                "Headset placement procedure specified mouth-corner distance for audio quality.",
                "NIST presegmentation data model introduced speech and non-speech intervals.",
                "Collaboration proposal examined inference structures in language understanding.",
                "Portable recording equipment plan addressed cable runs and amplifier transport.",
                "Speaker channel mapping linked microphone numbers to seated participants.",
                "Waveform transcription tool review compared external annotation software.",
            ]
            events = [
                {"obj_id": f"L1-{index:03d}", "meeting_id": "M001", "summary": summary}
                for index, summary in enumerate(summaries)
            ]
            _write_json(
                run_root / "l2" / "l2_view.json",
                {
                    "l2_nodes": [
                        {
                            "l2_id": "L2-data-source",
                            "label": "data source",
                            "linked_obj_ids": [row["obj_id"] for row in events],
                            "timeline_digest": events,
                            "top_semantic_terms": [{"term": f"unique source term {index}"} for index in range(12)],
                        }
                    ]
                },
            )
            _write_json(run_root / "l3" / "l3_view.json", {"l3_parents": []})
            _write_json(
                run_root / "l2" / "llm_split_review_proposals.json",
                {
                    "review_only": [
                        {
                            "source_l2_id": "L2-data-source",
                            "reason": "The model was unsure whether a split is safe.",
                            "representative_l1_ids": ["L1-000", "L1-001"],
                        }
                    ]
                },
            )

            report = audit_topic_quality(run_root=run_root)

            broad_source_ids = {
                issue.get("l2_id")
                for issue in report["issues"]
                if issue.get("code") == "broad_l2_mixed_signatures"
            }
            self.assertIn("L2-data-source", broad_source_ids)
            summary = report["topic_summaries"][0]
            self.assertEqual(summary["review_disposition_mitigation"], "none")

    def test_profile_can_send_low_confidence_l1_to_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share = _share_root(
                root / "share",
                "REVIEW-001",
                [
                    _obj("L1-REVIEW-001", "The team briefly mentioned a loose source note.", importance=0.2, topics=["source note"]),
                    _obj("L1-REVIEW-002", "The team briefly mentioned another loose source note.", importance=0.2, topics=["source note"]),
                ],
            )
            profile = root / "profile.yaml"
            profile.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "review_only_fixture",
                        "inherits": "mentor_mentee",
                        "domain": "mentor_mentee_research_meeting",
                        "semantic_facets": [{"name": "design_problem", "seed_terms": ["source"]}],
                        "l2_policy": {
                            "min_topic_evidence": 2,
                            "minimum_assignment_confidence": 0.25,
                            "review_only_min_assignment_confidence": 0.8,
                            "high_importance_threshold": 0.7,
                            "allow_single_meeting_topic_if_high_importance": False,
                        },
                        "l3_policy": {"adaptive_thresholds": True, "min_absolute_threshold": 99},
                    }
                ),
                encoding="utf-8",
            )
            out = root / "optimization" / "runs" / "review_only"

            build_view(share_mem_root=share, profile_path=profile, out_root=out, mode="deterministic", clean=True)
            unlinked = load_json(out / "l2" / "unlinked_l1_report.json")["unlinked_objects"]

            self.assertEqual({row["reason"] for row in unlinked}, {"review_only_low_assignment_confidence"})
            self.assertEqual(load_json(out / "l2" / "l2_index.json"), {})

    def test_l3_does_not_materialize_low_separability_children(self) -> None:
        profile = load_profile(MENTOR_PROFILE)
        profile["l3_policy"] = {
            **(profile.get("l3_policy", {}) or {}),
            "min_absolute_threshold": 10,
            "target_child_l2_size_range": [4, 8],
            "min_child_l2_count": 3,
            "min_split_separability": 0.72,
        }
        timeline = [
            {
                "meeting_id": "M001",
                "meeting_date": "2026-01-01",
                "obj_id": f"L1-SAME-{index:03d}",
                "summary": "The team repeated one broad comparison page note about context cost and latency.",
                "importance": 0.72,
            }
            for index in range(36)
        ]
        l2_result = {
            "l2_nodes": [
                {
                    "l2_id": "L2-comparison-page",
                    "label": "comparison page",
                    "linked_obj_ids": [row["obj_id"] for row in timeline],
                    "timeline_digest": timeline,
                    "top_semantic_terms": [
                        {"term": "comparison page note", "object_count": 36},
                        {"term": "context cost", "object_count": 2},
                    ],
                }
            ]
        }

        l3 = build_l3_view(l2_result=l2_result, profile=profile)

        self.assertEqual(l3["l3_parents"], [])
        review_rows = l3["l2_merge_review"]["merge_reviews"]
        self.assertTrue(any(row.get("action") == "needs_split_review" for row in review_rows), review_rows)
        self.assertTrue(any("low_split_separability" in row.get("reason_codes", []) for row in review_rows), review_rows)

    def test_l3_materializes_when_child_topics_are_separable(self) -> None:
        profile = load_profile(MENTOR_PROFILE)
        profile["l3_policy"] = {
            **(profile.get("l3_policy", {}) or {}),
            "min_absolute_threshold": 10,
            "target_child_l2_size_range": [4, 8],
            "min_child_l2_count": 2,
            "min_split_separability": 0.45,
        }
        topics = ["wire management", "equipment cabinet"]
        timeline = [
            {
                "meeting_id": "M001",
                "meeting_date": "2026-01-01",
                "obj_id": f"L1-SPLIT-{index:03d}",
                "summary": f"The team discussed {topics[index % 2]} for a reliable recording setup.",
                "importance": 0.72,
            }
            for index in range(24)
        ]
        l2_result = {
            "l2_nodes": [
                {
                    "l2_id": "L2-recording-setup",
                    "label": "recording setup",
                    "linked_obj_ids": [row["obj_id"] for row in timeline],
                    "timeline_digest": timeline,
                    "top_semantic_terms": [{"term": term, "object_count": 12} for term in topics],
                }
            ]
        }

        l3 = build_l3_view(l2_result=l2_result, profile=profile)

        labels = [child["label"] for parent in l3["l3_parents"] for child in parent["child_l2_nodes"]]
        self.assertIn("wire management", labels)
        self.assertIn("equipment cabinet", labels)

    def test_cross_dataset_suite_writes_grace_icsi_locomo_style_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grace = _share_root(
                root / "grace_share",
                "GRACE-001",
                [
                    _obj(
                        "L1-GRACE-001",
                        "Memory retrieval should use evidence seeds before topic summaries.",
                        topics=["evidence-first retrieval"],
                    ),
                    _obj(
                        "L1-GRACE-002",
                        "Topic summaries should explain retrieval evolution across meetings.",
                        topics=["topic evolution"],
                    ),
                    _obj(
                        "L1-GRACE-003",
                        "Answer context should preserve source traceability.",
                        topics=["source traceability"],
                    ),
                    _obj(
                        "L1-GRACE-004",
                        "Review gates should prevent unsupported memory topic promotion.",
                        topics=["review gates"],
                    ),
                ],
            )
            icsi = _share_root(
                root / "icsi_share",
                "BMR-001",
                [
                    _obj("L1-ICSI-001", "Recording setup used headset microphones in the meeting room.", topics=["recording setup"]),
                    _obj("L1-ICSI-002", "Audio channel quality affected transcription confidence.", topics=["audio quality"]),
                    _obj("L1-ICSI-003", "Equipment placement changed how participants were captured.", topics=["equipment placement"]),
                    _obj("L1-ICSI-004", "Corpus notes tracked source data and room configuration.", topics=["corpus notes"]),
                ],
            )
            out = root / "optimization" / "runs" / "cross_suite"

            report = run_cross_dataset_suite(
                grace_share_mem_root=grace,
                icsi_share_mem_root=icsi,
                conversation_share_mem_root=LOCOMO_STYLE_FIXTURE_ROOT,
                out_root=out,
                mode="deterministic",
                clean=True,
            )

            rows = {row["dataset"]: row for row in report["datasets"]}
            self.assertEqual(set(rows), {"grace", "icsi", "conversation_style"})
            self.assertNotEqual(rows["conversation_style"]["decision"], "fail")
            self.assertEqual(rows["conversation_style"]["domain_leakage_issue_count"], 0)
            self.assertTrue((out / "suite_summary.json").exists())
            locomo_run = Path(rows["conversation_style"]["run_root"])
            l2_view = load_json(locomo_run / "l2" / "l2_view.json")
            l2_index = load_json(locomo_run / "l2" / "l2_index.json")
            linked_from_view = {
                obj_id
                for node in l2_view.get("l2_nodes", [])
                for obj_id in node.get("linked_obj_ids", [])
            }
            self.assertLessEqual(linked_from_view, set(l2_index))

    def test_compare_topic_candidates_prefers_review_only_over_forced_broad_l2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = _candidate_run(root, "baseline", broad_count=3, review_only=[])
            candidate = _candidate_run(
                root,
                "candidate",
                broad_count=1,
                review_only=[
                    {
                        "obj_id": "L1-low",
                        "importance": 0.4,
                        "reason": "review_only_low_assignment_confidence",
                    }
                ],
            )

            report = compare_topic_candidates(
                baseline_run_root=baseline,
                candidate_run_roots=[candidate],
                out=root / "optimization" / "runs" / "comparison",
            )

            row = report["candidates"][0]
            self.assertGreater(row["score_delta"], 0)
            self.assertIn("reduced_broad_topic_risk", row["improvements"])
            self.assertIn("review_only_l1_has_reason", row["improvements"])

    def test_compare_topic_candidates_penalizes_unexplained_high_importance_unlinked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = _candidate_run(root, "baseline", broad_count=1, review_only=[])
            candidate = _candidate_run(
                root,
                "bad_candidate",
                broad_count=1,
                review_only=[{"obj_id": "L1-high", "importance": 0.88, "reason": ""}],
            )

            report = compare_topic_candidates(
                baseline_run_root=baseline,
                candidate_run_roots=[candidate],
                out=root / "optimization" / "runs" / "comparison",
            )

            row = report["candidates"][0]
            self.assertLess(row["score_delta"], 0)
            self.assertIn("unexplained_high_importance_unlinked", row["regressions"])

    def test_focused_split_review_can_use_topic_quality_review_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root = _minimal_run_root(root)
            review_source = run_root / "topic_quality" / "manual_topic_review_queue.json"
            _write_json(
                review_source,
                {
                    "items": [
                        {
                            "code": "needs_topic_review",
                            "l2_id": "L2-data-source",
                            "label": "data source",
                        }
                    ]
                },
            )
            profile = load_profile(MENTOR_PROFILE)
            client = _FakeSplitReviewClient()

            report = propose_focused_split_review(
                run_root=run_root,
                profile=profile,
                model="fake-model",
                client=client,
                review_source_path=review_source,
                sample_limit=4,
            )

            self.assertEqual(report["source_l2_count"], 1)
            self.assertEqual(report["accepted_split_count"], 1)
            self.assertEqual(report["source_l2_ids"], ["L2-data-source"])
            self.assertIn("L2-data-source", client.models.prompt)

    def test_focused_split_review_accepts_topics_wrapped_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root = _minimal_run_root(root)
            _write_json(
                run_root / "topic_quality" / "manual_topic_review_queue.json",
                {"items": [{"code": "broad_l2_mixed_signatures", "l2_id": "L2-data-source"}]},
            )

            report = propose_focused_split_review(
                run_root=run_root,
                profile=load_profile(MENTOR_PROFILE),
                model="fake-model",
                client=_FakeWrappedSplitReviewClient(),
                review_source_path=run_root / "topic_quality" / "manual_topic_review_queue.json",
                sample_limit=4,
            )

            self.assertEqual(report["accepted_split_count"], 1)
            self.assertEqual(report["accepted_split_candidates"][0]["source_l2_id"], "L2-data-source")

    def test_apply_split_review_skips_candidate_with_tiny_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "optimization" / "runs" / "source"
            timeline = [
                {
                    "obj_id": f"L1-TINY-{index}",
                    "meeting_id": "M001",
                    "meeting_date": "2026-01-01",
                    "summary": "Common recording setup evidence." if index < 4 else "Rare table microphone evidence.",
                }
                for index in range(5)
            ]
            _write_json(
                source / "l2" / "l2_view.json",
                {
                    "l2_nodes": [
                        {
                            "l2_id": "L2-recording-setup",
                            "label": "recording setup",
                            "linked_obj_ids": [row["obj_id"] for row in timeline],
                            "timeline_digest": timeline,
                        }
                    ]
                },
            )
            _write_json(source / "l2" / "l2_index.json", {})
            _write_json(source / "l3" / "l3_view.json", {"l3_parents": []})
            _write_json(source / "l3" / "l3_index.json", {})
            _write_json(source / "l3" / "l2_merge_review.json", {"merge_reviews": []})
            _write_json(
                source / "l2" / "llm_split_review_proposals.json",
                {
                    "accepted_split_candidates": [
                        {
                            "source_l2_id": "L2-recording-setup",
                            "confidence": 0.9,
                            "rationale": "One child would be too small.",
                            "child_candidates": [
                                {
                                    "label": "common recording setup",
                                    "assignment_criteria": ["common recording setup"],
                                    "representative_l1_ids": ["L1-TINY-0"],
                                },
                                {
                                    "label": "table microphone placement",
                                    "assignment_criteria": ["rare table microphone"],
                                    "representative_l1_ids": ["L1-TINY-4"],
                                },
                            ],
                        }
                    ]
                },
            )

            report = apply_split_review_candidates(
                source_run_root=source,
                out_root=Path(tmp) / "optimization" / "runs" / "candidate",
                clean=True,
            )

            self.assertEqual(report["applied_split_count"], 0)
            self.assertEqual(report["skipped_splits"][0]["reason"], "tiny_candidate_child")


if __name__ == "__main__":
    unittest.main()
