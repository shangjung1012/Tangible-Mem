from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from optimization.long_term_v2.create_icsi_eval_pack import create_icsi_eval_pack
from optimization.long_term_v2.compare_icsi_systems_no_llm import compare_systems_no_llm
from optimization.long_term_v2.evaluate_retrieval import _load_queries
from optimization.long_term_v2.revise_icsi_eval_pack import revise_icsi_eval_pack


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _obj(obj_id: str, content: str, *, meeting_id: str, obj_type: str = "finding") -> dict:
    return {
        "obj_id": obj_id,
        "type": obj_type,
        "legacy_type": "result",
        "content": content,
        "importance": 0.72,
        "evidence": content,
        "related_topics": ["audio processing"],
        "related_obj_ids": [],
        "_meeting_id": meeting_id,
    }


def _meeting(meeting_id: str, objects: list[dict]) -> dict:
    return {
        "meeting_id": meeting_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "meeting_date": "2026-01-01",
        "source_file": f"{meeting_id}.txt",
        "phase_id": "",
        "memory_objects": [
            {key: value for key, value in obj.items() if key != "_meeting_id"}
            for obj in objects
        ],
    }


def _fixture(root: Path) -> tuple[Path, Path]:
    share = root / "memory_outputs" / "icsi" / "runs" / "fixture" / "share_mem_effective"
    source_objs = [
        _obj("L1-Bmr001-001", "The team discussed audio processing filters for meeting recordings.", meeting_id="Bmr001"),
        _obj("L1-Bmr002-001", "A decision was made to preserve audio channel metadata for later analysis.", meeting_id="Bmr002", obj_type="decision"),
    ]
    heldout_objs = [
        _obj("L1-Bmr024-001", "Later meetings revisited audio processing because channel alignment remained fragile.", meeting_id="Bmr024"),
        _obj("L1-Bmr025-001", "The group carried forward audio channel issues into a later recording workflow.", meeting_id="Bmr025"),
    ]
    weak_objs = [
        _obj("L1-Bmr001-weak", "The speaker said go ahead during a transition.", meeting_id="Bmr001"),
        _obj("L1-Bmr024-weak", "The phrase go ahead appeared again.", meeting_id="Bmr024"),
    ]
    tree = {
        "tree_version": 1,
        "last_updated_utc": "2026-01-01T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [
            _meeting("Bmr001", [source_objs[0], weak_objs[0]]),
            _meeting("Bmr002", [source_objs[1]]),
            _meeting("Bmr024", [heldout_objs[0], weak_objs[1]]),
            _meeting("Bmr025", [heldout_objs[1]]),
        ],
    }
    _write_json(share / "tree.json", tree)
    _write_json(share / "manifest.json", {"meeting_count": 4, "object_count": 6, "meeting_ids": ["Bmr001", "Bmr002", "Bmr024", "Bmr025"]})
    for meeting in tree["meetings"]:
        _write_json(share / "meetings" / f"{meeting['meeting_id']}.json", meeting)

    run = root / "optimization" / "runs" / "fixture_v2"
    l2_nodes = [
        {
            "l2_id": "L2-audio-processing",
            "label": "audio processing",
            "linked_obj_ids": ["L1-Bmr001-001", "L1-Bmr002-001", "L1-Bmr024-001", "L1-Bmr025-001"],
            "meeting_ids": ["Bmr001", "Bmr002", "Bmr024", "Bmr025"],
            "timeline_digest": [
                {"obj_id": "L1-Bmr001-001", "meeting_id": "Bmr001", "summary": "audio filters"},
                {"obj_id": "L1-Bmr024-001", "meeting_id": "Bmr024", "summary": "alignment remained fragile"},
            ],
        },
        {
            "l2_id": "L2-go-ahead",
            "label": "go ahead",
            "linked_obj_ids": ["L1-Bmr001-weak", "L1-Bmr024-weak"],
            "meeting_ids": ["Bmr001", "Bmr024"],
            "timeline_digest": [],
        },
        {
            "l2_id": "L2-team-decided",
            "label": "team decided",
            "linked_obj_ids": ["L1-Bmr001-001", "L1-Bmr002-001", "L1-Bmr024-001"],
            "meeting_ids": ["Bmr001", "Bmr002", "Bmr024"],
            "timeline_digest": [],
        },
    ]
    l2_index = {
        "L1-Bmr001-001": {"l2_id": "L2-audio-processing", "l2_label": "audio processing"},
        "L1-Bmr002-001": {"l2_id": "L2-audio-processing", "l2_label": "audio processing"},
        "L1-Bmr024-001": {"l2_id": "L2-audio-processing", "l2_label": "audio processing"},
        "L1-Bmr025-001": {"l2_id": "L2-audio-processing", "l2_label": "audio processing"},
        "L1-Bmr001-weak": {"l2_id": "L2-go-ahead", "l2_label": "go ahead"},
        "L1-Bmr024-weak": {"l2_id": "L2-go-ahead", "l2_label": "go ahead"},
    }
    _write_json(run / "manifest.json", {"profile_path": str(Path("optimization/long_term_v2/profiles/isci_meeting.yaml").resolve())})
    _write_json(run / "l2" / "l2_view.json", {"l2_nodes": l2_nodes})
    _write_json(run / "l2" / "l2_index.json", l2_index)
    _write_json(run / "l3" / "l3_view.json", {"l3_parents": []})
    _write_json(run / "l3" / "l3_index.json", {})
    return run, share


class IcsiEvalPackTests(unittest.TestCase):
    def test_retrieval_query_loader_accepts_utf8_sig_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.jsonl"
            path.write_text(
                json.dumps({"query_id": "q001", "query": "test"}, ensure_ascii=False) + "\n",
                encoding="utf-8-sig",
            )

            rows = _load_queries(path)

            self.assertEqual(rows, [{"query_id": "q001", "query": "test"}])

    def test_eval_pack_uses_heldout_as_trigger_and_source_as_answerable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, share = _fixture(Path(tmp))
            out = Path(tmp) / "optimization" / "reports" / "icsi_eval_pack"

            report = create_icsi_eval_pack(
                run_root=run,
                share_mem_root=share,
                out_dir=out,
                source_through_meeting_id="Bmr023",
                max_questions=5,
            )

            self.assertEqual(report["status"], "candidate_manual_review_required")
            self.assertEqual(report["query_count"], 5)
            self.assertTrue((out / "heldout_eval_queries.jsonl").exists())
            self.assertTrue((out / "source_share_mem" / "tree.json").exists())
            source_tree = json.loads((out / "source_share_mem" / "tree.json").read_text(encoding="utf-8"))
            self.assertEqual([meeting["meeting_id"] for meeting in source_tree["meetings"]], ["Bmr001", "Bmr002"])
            rows = [
                json.loads(line)
                for line in (out / "heldout_eval_queries.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(all(row["benchmark_type"] == "heldout_future_meeting" for row in rows))
            self.assertTrue(all(row["expected_obj_ids"] == row["expected_source_obj_ids"] for row in rows))
            self.assertTrue(all(obj_id.startswith("L1-Bmr00") for row in rows for obj_id in row["expected_source_obj_ids"]))
            self.assertTrue(all(obj_id.startswith("L1-Bmr02") for row in rows for obj_id in row["heldout_trigger_obj_ids"]))
            self.assertEqual({row["expected_l2_labels"][0] for row in rows}, {"audio processing"})
            self.assertIn("manual review", (out / "heldout_eval_pack.md").read_text(encoding="utf-8").lower())

    def test_eval_pack_filters_weak_labels_and_requires_pre_post_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, share = _fixture(Path(tmp))
            out = Path(tmp) / "optimization" / "reports" / "icsi_eval_pack"

            report = create_icsi_eval_pack(
                run_root=run,
                share_mem_root=share,
                out_dir=out,
                source_through_meeting_id="Bmr023",
                max_questions=10,
            )

            labels = {label for row in report["queries"] for label in row["expected_l2_labels"]}
            self.assertNotIn("go ahead", labels)
            self.assertNotIn("team decided", labels)
            self.assertEqual(labels, {"audio processing"})

    def test_revised_eval_pack_applies_review_decisions_without_using_heldout_as_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = root / "optimization" / "reports" / "pack"
            queries = [
                {
                    "query_id": "icsi-heldout-q001",
                    "query_type": "evidence_lookup",
                    "query": "accepted question",
                    "answer_from_meetings": ["Bmr001"],
                    "heldout_trigger_meetings": ["Bmr024"],
                    "expected_obj_ids": ["L1-Bmr001-001"],
                    "expected_source_obj_ids": ["L1-Bmr001-001"],
                    "heldout_trigger_obj_ids": ["L1-Bmr024-001"],
                    "source_evidence_preview": [{"obj_id": "L1-Bmr001-001", "content": "source"}],
                    "heldout_trigger_preview": [{"obj_id": "L1-Bmr024-001", "content": "heldout"}],
                    "provenance": {"manual_review_required": True},
                    "status": "candidate_manual_review_required",
                },
                {
                    "query_id": "icsi-heldout-q002",
                    "query_type": "topic_evolution",
                    "query": "weak evolution question",
                    "answer_from_meetings": ["Bmr001"],
                    "heldout_trigger_meetings": ["Bmr024"],
                    "expected_obj_ids": ["L1-Bmr001-002"],
                    "expected_source_obj_ids": ["L1-Bmr001-002"],
                    "heldout_trigger_obj_ids": ["L1-Bmr024-002"],
                    "source_evidence_preview": [{"obj_id": "L1-Bmr001-002", "content": "disk source"}],
                    "heldout_trigger_preview": [{"obj_id": "L1-Bmr024-002", "content": "disk heldout"}],
                    "provenance": {"manual_review_required": True},
                    "status": "candidate_manual_review_required",
                },
                {
                    "query_id": "icsi-heldout-q006",
                    "query_type": "decision_rationale",
                    "query": "noisy acoustic modeling question",
                    "answer_from_meetings": ["Bmr002", "Bmr005"],
                    "heldout_trigger_meetings": ["Bmr024"],
                    "expected_obj_ids": ["L1-Bmr002-197", "L1-Bmr002-239", "L1-Bmr005-001"],
                    "expected_source_obj_ids": ["L1-Bmr002-197", "L1-Bmr002-239", "L1-Bmr005-001"],
                    "heldout_trigger_obj_ids": ["L1-Bmr024-006"],
                    "source_evidence_preview": [
                        {"obj_id": "L1-Bmr002-197", "content": "acoustic model training"},
                        {"obj_id": "L1-Bmr002-239", "content": "Control-C process noise"},
                        {"obj_id": "L1-Bmr005-001", "content": "digit-reading automation"},
                    ],
                    "heldout_trigger_preview": [{"obj_id": "L1-Bmr024-006", "content": "heldout trigger"}],
                    "provenance": {"manual_review_required": True},
                    "status": "candidate_manual_review_required",
                },
                {
                    "query_id": "icsi-heldout-q005",
                    "query_type": "corpus_process",
                    "query": "broad annotation process question",
                    "answer_from_meetings": ["Bmr002"],
                    "heldout_trigger_meetings": ["Bmr024"],
                    "expected_obj_ids": ["L1-Bmr002-093", "L1-Bmr002-094", "L1-Bmr002-095", "L1-Bmr002-114"],
                    "expected_source_obj_ids": ["L1-Bmr002-093", "L1-Bmr002-094", "L1-Bmr002-095", "L1-Bmr002-114"],
                    "heldout_trigger_obj_ids": ["L1-Bmr024-005"],
                    "source_evidence_preview": [
                        {"obj_id": "L1-Bmr002-093", "content": "Mississippi State tools"},
                        {"obj_id": "L1-Bmr002-094", "content": "Mississippi State and XWaves"},
                        {"obj_id": "L1-Bmr002-095", "content": "XWaves"},
                        {"obj_id": "L1-Bmr002-114", "content": "Alembic Workbench free tool uncertainty"},
                    ],
                    "heldout_trigger_preview": [{"obj_id": "L1-Bmr024-005", "content": "heldout trigger"}],
                    "provenance": {"manual_review_required": True},
                    "status": "candidate_manual_review_required",
                },
            ]
            pack.mkdir(parents=True)
            (pack / "heldout_eval_queries.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in queries) + "\n",
                encoding="utf-8",
            )
            (pack / "review_decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "query_id": "icsi-heldout-q001",
                                "decision": "accept",
                                "severity": "none",
                                "reason": "usable",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "query_id": "icsi-heldout-q002",
                                "decision": "revise",
                                "severity": "minor",
                                "reason": "single source meeting",
                                "recommended_query": "What source-side evidence did the BMR meetings contain about disk space constraints and storage decisions?",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "query_id": "icsi-heldout-q005",
                                "decision": "revise",
                                "severity": "minor",
                                "reason": "narrow tool candidates",
                                "recommended_query": "What annotation tool options and workflow requirements had been discussed before later transcription workflow changes?",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "query_id": "icsi-heldout-q006",
                                "decision": "revise",
                                "severity": "minor",
                                "reason": "remove noise",
                                "recommended_query": "What source-side evidence discussed acoustic model training data and digit-reading automation?",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = revise_icsi_eval_pack(
                source_pack=pack / "heldout_eval_queries.jsonl",
                decisions_path=pack / "review_decisions.jsonl",
                out_dir=root / "optimization" / "reports" / "revised",
            )

            self.assertEqual(report["total_query_count"], 4)
            self.assertEqual(report["revised_count"], 3)
            self.assertEqual(report["accepted_unchanged_count"], 1)
            rows = _load_queries(root / "optimization" / "reports" / "revised" / "approved_revised_heldout_eval_queries.jsonl")
            by_id = {row["query_id"]: row for row in rows}
            self.assertEqual(by_id["icsi-heldout-q002"]["query_type"], "evidence_lookup")
            self.assertIn("disk space constraints", by_id["icsi-heldout-q002"]["query"])
            self.assertNotIn("L1-Bmr002-239", by_id["icsi-heldout-q006"]["expected_obj_ids"])
            self.assertNotIn("L1-Bmr002-239", by_id["icsi-heldout-q006"]["expected_source_obj_ids"])
            self.assertIn("Mississippi State", by_id["icsi-heldout-q005"]["query"])
            self.assertNotIn("L1-Bmr002-114", by_id["icsi-heldout-q005"]["expected_obj_ids"])
            self.assertTrue(
                all(
                    obj_id.startswith("L1-Bmr00")
                    for row in rows
                    for obj_id in row["expected_obj_ids"]
                )
            )
            self.assertTrue(
                all(
                    obj_id.startswith("L1-Bmr02")
                    for row in rows
                    for obj_id in row["heldout_trigger_obj_ids"]
                )
            )
            self.assertEqual(by_id["icsi-heldout-q006"]["status"], "agent_revised_for_dry_run")

    def test_no_llm_system_comparison_reports_recall_and_context_tradeoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, share = _fixture(root)
            queries = root / "optimization" / "reports" / "queries.jsonl"
            queries.parent.mkdir(parents=True)
            queries.write_text(
                json.dumps(
                    {
                        "query_id": "q001",
                        "query": "audio processing channel metadata",
                        "expected_obj_ids": ["L1-Bmr001-001", "L1-Bmr002-001"],
                        "expected_l2_labels": ["audio processing"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = compare_systems_no_llm(
                run_root=run,
                share_mem_root=share,
                queries_path=queries,
                out_dir=root / "optimization" / "reports" / "comparison",
                rag_top_k=1,
                layered_top_k_l1=4,
            )

            self.assertEqual(report["summary"]["query_count"], 1)
            self.assertEqual(report["summary"]["strategies"], ["full_context_l1", "rag_l1_lexical", "optimization_v2_layered"])
            self.assertEqual(report["summary"]["expected_l1_recall"]["full_context_l1"], 1.0)
            self.assertLess(report["summary"]["expected_l1_recall"]["rag_l1_lexical"], 1.0)
            self.assertGreaterEqual(report["summary"]["expected_l1_recall"]["optimization_v2_layered"], 1.0)
            self.assertGreater(
                report["summary"]["avg_context_tokens"]["full_context_l1"],
                report["summary"]["avg_context_tokens"]["rag_l1_lexical"],
            )
            self.assertTrue((root / "optimization" / "reports" / "comparison" / "system_comparison_summary.md").exists())


if __name__ == "__main__":
    unittest.main()
