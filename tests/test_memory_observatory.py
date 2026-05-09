from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

from memory_observatory.main import create_app
from memory_observatory.services.baselines import build_full_context, retrieve_lexical_rag
from memory_observatory.services.experiment_runner import run_experiment
from memory_observatory.services.feedback_store import FeedbackStore
from memory_observatory.services.report_store import ReportStore
from memory_observatory.services.token_utils import estimate_tokens
from long_term.recall import format_recall_for_prompt


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fixture_repo(root: Path) -> None:
    _write_json(
        root / "share_mem" / "tree.json",
        {
            "tree_version": 1,
            "meetings": [
                {
                    "meeting_id": "0307",
                    "meeting_date": "2026-03-07",
                    "source_file": "0307.txt",
                    "memory_objects": [
                        {
                            "obj_id": "L1-0307-001",
                            "meeting_id": "0307",
                            "meeting_date": "2026-03-07",
                            "type": "decision",
                            "content": "Use layered memory retrieval from L1 evidence.",
                            "evidence": "The team chose L1 first retrieval.",
                            "importance": 0.8,
                            "related_topics": ["memory retrieval"],
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        root / "long_term" / "l2" / "l2_view.json",
        {
            "schema_version": 1,
            "l2_nodes": [
                {
                    "l2_id": "L2-memory-retrieval",
                    "label": "memory retrieval",
                    "current_state": "Recall starts from L1 evidence.",
                    "linked_obj_ids": ["L1-0307-001"],
                    "meeting_ids": ["0307"],
                    "timeline_digest": [
                        {
                            "meeting_id": "0307",
                            "meeting_date": "2026-03-07",
                            "obj_id": "L1-0307-001",
                            "summary": "L1-first retrieval was chosen.",
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        root / "long_term" / "l2" / "l2_index.json",
        {
            "L1-0307-001": {
                "obj_id": "L1-0307-001",
                "l2_id": "L2-memory-retrieval",
                "l2_label": "memory retrieval",
                "assignment_reason": "test",
                "confidence": 1.0,
            }
        },
    )
    _write_json(
        root / "long_term" / "l3" / "l3_view.json",
        {
            "schema_version": 1,
            "materialized_l3_count": 1,
            "l3_nodes": [
                {
                    "l3_id": "L3-memory-family",
                    "label": "memory family",
                    "child_l2_nodes": [
                        {
                            "l2_id": "L2-memory-retrieval-child",
                            "label": "Memory Retrieval Child",
                            "linked_obj_ids": ["L1-0307-001"],
                            "timeline_digest": [
                                {
                                    "meeting_id": "0307",
                                    "meeting_date": "2026-03-07",
                                    "obj_id": "L1-0307-001",
                                    "summary": "Layered retrieval uses evidence seeds.",
                                }
                            ],
                            "current_state": "Evidence-first recall.",
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        root / "long_term" / "l3" / "l3_index.json",
        {
            "L1-0307-001": {
                "obj_id": "L1-0307-001",
                "l3_id": "L3-memory-family",
                "child_l2_id": "L2-memory-retrieval-child",
                "child_l2_label": "Memory Retrieval Child",
                "assignment_reason": "criteria_match",
                "assignment_score": 1,
            }
        },
    )
    _write_json(
        root / "long_term" / "l3" / "validation" / "l3_validation_report.json",
        {
            "materialized_l3_count": 1,
            "severe_count": 0,
            "warning_count": 0,
            "promotion_coverage": {
                "unassigned_l1_count": 0,
                "duplicate_assignment_count": 0,
                "invalid_l3_index_count": 0,
            },
        },
    )
    _write_json(
        root / "long_term" / "eval" / "retrieval_eval_report.json",
        {
            "query_count": 1,
            "run_count": 1,
            "best_params": {"retrieval_mode": "lexical"},
        },
    )
    (root / "long_term" / "eval").mkdir(parents=True, exist_ok=True)
    (root / "long_term" / "eval" / "long_term_retrieval_queries.jsonl").write_text(
        json.dumps(
            {
                "query": "How does memory retrieval work?",
                "expected_obj_ids": ["L1-0307-001"],
                "expected_l2_ids": ["L2-memory-retrieval"],
                "expected_l3_ids": ["L3-memory-family"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    transcript_root = root / "meeting_recording" / "transcript" / "grace"
    transcript_root.mkdir(parents=True, exist_ok=True)
    (transcript_root / "0307.txt").write_text(
        "Line one memory retrieval evidence.\nLine two unrelated logistics.\n",
        encoding="utf-8",
    )


class MemoryObservatoryTests(unittest.TestCase):
    def test_token_estimate_handles_english_chinese_and_mixed_text(self) -> None:
        self.assertGreater(estimate_tokens("memory retrieval baseline"), 0)
        self.assertGreater(estimate_tokens("記憶檢索測試"), 0)
        self.assertEqual(
            estimate_tokens("memory 記憶 retrieval"),
            estimate_tokens("memory 記憶 retrieval"),
        )

    def test_full_context_records_truncation_and_token_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            result = build_full_context(
                repo_root=root,
                scope="all",
                max_context_chars=40,
            )

        self.assertEqual(result["strategy"], "full_context")
        self.assertTrue(result["truncated"])
        self.assertGreater(result["metrics"]["estimated_context_tokens"], 0)
        self.assertEqual(result["included_meeting_count"], 1)

    def test_lexical_rag_returns_chunk_metadata_with_line_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            result = retrieve_lexical_rag(
                "memory retrieval",
                repo_root=root,
                top_k=1,
            )

        self.assertEqual(result["strategy"], "rag_baseline")
        self.assertEqual(result["retrieved_chunk_count"], 1)
        chunk = result["retrieved_chunks"][0]
        self.assertEqual(chunk["meeting_id"], "0307")
        self.assertEqual(chunk["start_line"], 1)
        self.assertGreater(chunk["score"], 0)

    def test_feedback_store_writes_sidecars_without_modifying_raw_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            tree_before = (root / "share_mem" / "tree.json").read_text(encoding="utf-8")
            store = FeedbackStore(root / "share_mem")
            record = store.save_importance_adjustment(
                {
                    "obj_id": "L1-0307-001",
                    "meeting_id": "0307",
                    "object_type": "decision",
                    "canonical_importance": 0.8,
                    "user_importance": 0.95,
                    "reason_code": "important_design_decision",
                    "note": "key demo evidence",
                }
            )

            self.assertEqual(
                tree_before,
                (root / "share_mem" / "tree.json").read_text(encoding="utf-8"),
            )
            self.assertTrue((root / "share_mem" / "user_feedback" / "importance_adjustments.jsonl").exists())
            index = store.load_override_index()
            self.assertEqual(index["L1-0307-001"]["latest_feedback_id"], record["feedback_id"])
            self.assertEqual(index["L1-0307-001"]["effective_importance"], 0.95)

    def test_report_store_creates_run_and_loads_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ReportStore(Path(tmp) / "runs")
            run_dir = store.create_run_dir("demo")
            store.write_run(
                run_dir,
                {
                    "run_id": run_dir.name,
                    "summary": {"query_count": 1},
                    "queries": [],
                },
            )

            self.assertEqual(store.list_runs()[0]["run_id"], run_dir.name)
            self.assertEqual(store.load_run(run_dir.name)["summary"]["query_count"], 1)

    def test_api_smoke_and_retrieval_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            client = TestClient(create_app(repo_root=root))

            self.assertEqual(client.get("/").status_code, 200)
            overview = client.get("/api/overview")
            self.assertEqual(overview.status_code, 200)
            self.assertEqual(overview.json()["meeting_count"], 1)
            trace = client.get(
                "/api/retrieval/trace",
                params={"query": "memory retrieval", "retrieval_mode": "lexical", "no_llm": "true"},
            )
            self.assertEqual(trace.status_code, 200)
            payload = trace.json()
            self.assertEqual(payload["strategy"], "layered_memory")
            self.assertGreaterEqual(payload["metrics"]["selected_l1_count"], 1)
            self.assertIn("formatted_prompt_context", payload)

    def test_llm_trace_uses_planner_model_separately_from_answer_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            with patch(
                "recall_planner.plan_recall",
                return_value={
                    "complexity": "simple",
                    "search_targets": ["long_term_l1"],
                    "keywords": ["memory", "retrieval"],
                },
            ) as planner, patch(
                "recall.recall",
                return_value={
                    "global_topic_map": {},
                    "long_term_l1": [{"obj_id": "L1-0307-001"}],
                    "long_term_l2": [],
                    "long_term_l3": [],
                    "retrieval_debug": {"selected_l1_count": 1},
                },
            ) as recall_call, patch(
                "recall.format_recall_for_prompt",
                return_value="=== L1 Evidence Seeds ===\nL1-0307-001",
            ):
                from memory_observatory.services.retrieval_trace import RetrievalTraceService

                result = RetrievalTraceService(root).run_trace(
                    "memory retrieval",
                    no_llm=False,
                    model_name="gemini-2.5-pro",
                    planner_model_name="gemini-2.5-flash",
                )

        self.assertTrue(result["use_llm_planner"])
        self.assertEqual(result["planner_model"], "gemini-2.5-flash")
        self.assertEqual(result["answer_model"], "gemini-2.5-pro")
        self.assertEqual(planner.call_args.kwargs["model_name"], "gemini-2.5-flash")
        self.assertEqual(recall_call.call_args.kwargs["model_name"], "gemini-2.5-pro")

    def test_no_llm_experiment_writes_strategy_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            result = run_experiment(
                repo_root=root,
                queries_path=root / "long_term" / "eval" / "long_term_retrieval_queries.jsonl",
                out=root / "memory_observatory" / "runs",
                strategies=["full_context", "rag_baseline", "layered_memory"],
                retrieval_mode="lexical",
                no_llm=True,
                generate_answers=False,
                max_context_chars=2000,
            )

            run_dir = root / "memory_observatory" / "runs" / result["run_id"]
            self.assertTrue((run_dir / "results.json").exists())
            self.assertTrue((run_dir / "contexts" / "q001" / "layered_memory.txt").exists())
            self.assertIn("avg_context_tokens", result["summary"])
            self.assertIn("layered_memory", result["queries"][0]["strategies"])

    def test_experiment_records_planner_model_and_passes_it_to_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            with patch(
                "memory_observatory.services.experiment_runner.RetrievalTraceService.run_trace",
                return_value={
                    "strategy": "layered_memory",
                    "query": "How does memory retrieval work?",
                    "l1_evidence_seeds": [{"obj_id": "L1-0307-001"}],
                    "l2_evolution_context": [],
                    "l3_navigation": [],
                    "context": "layered context",
                    "metrics": {
                        "estimated_context_tokens": 3,
                        "total_ms": 1,
                        "retrieval_ms": 1,
                        "generation_ms": 0,
                    },
                },
            ) as trace_call:
                result = run_experiment(
                    repo_root=root,
                    queries_path=root / "long_term" / "eval" / "long_term_retrieval_queries.jsonl",
                    out=root / "memory_observatory" / "runs",
                    strategies=["layered_memory"],
                    retrieval_mode="lexical",
                    no_llm=False,
                    generate_answers=False,
                    model="gemini-2.5-pro",
                    planner_model="gemini-2.5-flash",
                    max_context_chars=2000,
                )

        self.assertEqual(result["config"]["model"], "gemini-2.5-pro")
        self.assertEqual(result["config"]["planner_model"], "gemini-2.5-flash")
        self.assertEqual(trace_call.call_args.kwargs["model_name"], "gemini-2.5-pro")
        self.assertEqual(trace_call.call_args.kwargs["planner_model_name"], "gemini-2.5-flash")

    def test_formatter_can_expand_l1_evidence_for_observatory_answers(self) -> None:
        long_content = "A standard RAG approach is insufficient because it cannot track rejected versus adopted topic lifecycle state."
        formatted = format_recall_for_prompt(
            {
                "long_term_l1": [
                    {
                        "meeting_id": "0325",
                        "meeting_date": "2026-03-25",
                        "obj_id": "L1-0325-090",
                        "type": "argument",
                        "importance": 0.77,
                        "score": 0.59,
                        "content": long_content,
                        "evidence": long_content,
                    }
                ],
                "long_term_l2": [],
                "long_term_l3": [],
                "global_topic_map": {},
            },
            l1_content_chars=220,
            l1_evidence_chars=220,
        )

        self.assertIn("rejected versus adopted topic lifecycle state", formatted)
        self.assertNotIn("(truncated)", formatted)


if __name__ == "__main__":
    unittest.main()
