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
from memory_observatory.services import experiment_cli
from memory_observatory.services.baselines import build_full_context, retrieve_lexical_rag
from memory_observatory.services.data_loader import ObservatoryDataLoader
from memory_observatory.services.experiment_runner import run_experiment
from memory_observatory.services.feedback_store import FeedbackStore
from memory_observatory.services.report_store import ReportStore
from memory_observatory.services.scoring_export import export_observatory_run_to_scoring_csv
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

    def test_full_context_can_stop_at_token_budget_without_gold_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            transcript_root = root / "meeting_recording" / "transcript" / "grace"
            (transcript_root / "0318.txt").write_text("memory retrieval detail " * 800, encoding="utf-8")
            result = build_full_context(
                repo_root=root,
                scope="all",
                max_context_chars=0,
                max_context_tokens=120,
            )

        self.assertTrue(result["truncated"])
        self.assertLessEqual(result["metrics"]["estimated_context_tokens"], 140)
        self.assertEqual(result["full_context_scope"], "all")

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

    def test_lexical_rag_can_stop_at_token_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            transcript = root / "meeting_recording" / "transcript" / "grace" / "0307.txt"
            transcript.write_text(
                "\n".join(f"line {index} memory retrieval detail" for index in range(1, 160)),
                encoding="utf-8",
            )
            result = retrieve_lexical_rag(
                "memory retrieval",
                repo_root=root,
                top_k=999,
                max_context_chars=0,
                max_context_tokens=160,
            )

        self.assertTrue(result["truncated"])
        self.assertLess(result["retrieved_chunk_count"], 999)
        self.assertLessEqual(result["metrics"]["estimated_context_tokens"], 190)

    def test_lexical_rag_max_context_zero_disables_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            transcript = root / "meeting_recording" / "transcript" / "grace" / "0307.txt"
            transcript.write_text(
                "\n".join(f"line {index} memory retrieval detail" for index in range(1, 80)),
                encoding="utf-8",
            )
            result = retrieve_lexical_rag(
                "memory retrieval",
                repo_root=root,
                top_k=3,
                max_context_chars=0,
            )

        self.assertFalse(result["truncated"])
        self.assertNotIn("...(truncated)", result["context"])
        self.assertGreater(result["metrics"]["context_char_count"], 0)

    def test_layered_trace_max_context_zero_disables_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            full_context = "=== Global Topic Map ===\n" + ("memory retrieval detail\n" * 100)
            with patch(
                "recall.recall",
                return_value={
                    "global_topic_map": {},
                    "long_term_l1": [{"obj_id": "L1-0307-001"}],
                    "long_term_l2": [],
                    "long_term_l3": [],
                    "retrieval_debug": {"selected_l1_count": 1},
                },
            ), patch(
                "recall.format_recall_for_prompt",
                return_value=full_context,
            ):
                from memory_observatory.services.retrieval_trace import RetrievalTraceService

                result = RetrievalTraceService(root).run_trace(
                    "memory retrieval",
                    no_llm=True,
                    max_context_chars=0,
                )

        self.assertFalse(result["truncated"])
        self.assertEqual(result["context"], full_context)
        self.assertNotIn("...(truncated)", result["formatted_prompt_context"])

    def test_layered_trace_default_limit_allows_six_thousand_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            full_context = "=== L1 Evidence Seeds ===\n" + ("memory retrieval detail\n" * 240)
            self.assertGreater(len(full_context), 4000)
            self.assertLess(len(full_context), 6000)
            with patch(
                "recall.recall",
                return_value={
                    "global_topic_map": {},
                    "long_term_l1": [{"obj_id": "L1-0307-001"}],
                    "long_term_l2": [],
                    "long_term_l3": [],
                    "retrieval_debug": {"selected_l1_count": 1},
                },
            ), patch(
                "recall.format_recall_for_prompt",
                return_value=full_context,
            ):
                from memory_observatory.services.retrieval_trace import RetrievalTraceService

                result = RetrievalTraceService(root).run_trace(
                    "memory retrieval",
                    no_llm=True,
                )

        self.assertFalse(result["truncated"])
        self.assertEqual(result["context"], full_context)

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
            stale_dir = store.runs_root / "stale_temp_dir"
            stale_dir.mkdir(parents=True)
            store.write_run(
                run_dir,
                {
                    "run_id": run_dir.name,
                    "summary": {"query_count": 1},
                    "queries": [],
                },
            )

            self.assertEqual(store.list_runs()[0]["run_id"], run_dir.name)
            self.assertNotIn("stale_temp_dir", {row["run_id"] for row in store.list_runs()})
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

    def test_topic_detail_api_includes_linked_l1_objects_for_tree_drilldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            client = TestClient(create_app(repo_root=root))

            response = client.get("/api/topics/l2/L2-memory-retrieval-child")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["parent_l3_id"], "L3-memory-family")
        self.assertEqual(payload["event_count"], 1)
        self.assertEqual(payload["size_bucket"], "tiny")
        self.assertEqual(payload["linked_l1_objects"][0]["obj_id"], "L1-0307-001")
        self.assertEqual(payload["linked_l1_objects"][0]["topic_link"]["child_l2_id"], "L2-memory-retrieval-child")

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

    def test_experiment_can_configure_rag_top_k_and_disable_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            transcript = root / "meeting_recording" / "transcript" / "grace" / "0307.txt"
            transcript.write_text(
                "\n".join(f"line {index} memory retrieval detail" for index in range(1, 80)),
                encoding="utf-8",
            )
            result = run_experiment(
                repo_root=root,
                queries_path=root / "long_term" / "eval" / "long_term_retrieval_queries.jsonl",
                out=root / "memory_observatory" / "runs",
                strategies=["rag_baseline"],
                retrieval_mode="lexical",
                no_llm=True,
                generate_answers=False,
                max_context_chars=0,
                rag_top_k=3,
            )

        rag = result["queries"][0]["strategies"]["rag_baseline"]
        self.assertEqual(result["config"]["rag_top_k"], 3)
        self.assertEqual(rag["retrieved_chunk_count"], 3)
        self.assertFalse(rag["truncated"])
        self.assertNotIn("...(truncated)", rag["context"])

    def test_experiment_can_apply_dynamic_baseline_token_multiplier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            transcript = root / "meeting_recording" / "transcript" / "grace" / "0307.txt"
            transcript.write_text(
                "\n".join(f"line {index} memory retrieval detail" for index in range(1, 260)),
                encoding="utf-8",
            )
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
                        "estimated_context_tokens": 100,
                        "total_ms": 1,
                        "retrieval_ms": 1,
                        "generation_ms": 0,
                    },
                },
            ):
                result = run_experiment(
                    repo_root=root,
                    queries_path=root / "long_term" / "eval" / "long_term_retrieval_queries.jsonl",
                    out=root / "memory_observatory" / "runs",
                    strategies=["full_context", "rag_baseline", "layered_memory"],
                    retrieval_mode="lexical",
                    no_llm=True,
                    generate_answers=False,
                    max_context_chars=0,
                    rag_top_k=999,
                    baseline_token_multiplier=3.0,
                    full_context_scope="all",
                )

        query = result["queries"][0]
        self.assertEqual(result["config"]["baseline_token_multiplier"], 3.0)
        self.assertEqual(result["config"]["full_context_scope"], "all")
        self.assertLessEqual(query["strategies"]["full_context"]["metrics"]["estimated_context_tokens"], 340)
        self.assertLessEqual(query["strategies"]["rag_baseline"]["metrics"]["estimated_context_tokens"], 340)
        self.assertTrue(query["strategies"]["full_context"]["truncated"])
        self.assertTrue(query["strategies"]["rag_baseline"]["truncated"])

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

    def test_layered_trace_can_use_tight_budget_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            with patch(
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
                    no_llm=True,
                    budget_profile="large_corpus_tight",
                    max_context_chars=0,
                )

        self.assertEqual(result["budget_profile"], "large_corpus_tight")
        self.assertEqual(recall_call.call_args.kwargs["max_l1_seeds_for_prompt"], 8)
        self.assertEqual(recall_call.call_args.kwargs["max_events_per_child_l2"], 1)
        self.assertEqual(recall_call.call_args.kwargs["max_event_chars"], 80)

    def test_experiment_passes_budget_profile_to_layered_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            with patch(
                "memory_observatory.services.experiment_runner.RetrievalTraceService.run_trace",
                return_value={
                    "strategy": "layered_memory",
                    "query": "How does memory retrieval work?",
                    "budget_profile": "large_corpus_tight",
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
                    no_llm=True,
                    generate_answers=False,
                    budget_profile="large_corpus_tight",
                    max_context_chars=0,
                )

        self.assertEqual(result["config"]["budget_profile"], "large_corpus_tight")
        self.assertEqual(trace_call.call_args.kwargs["budget_profile"], "large_corpus_tight")

    def test_experiment_cli_defaults_to_no_llm_planner_with_answers(self) -> None:
        with patch(
            "memory_observatory.services.experiment_cli.run_experiment",
            return_value={"run_id": "run-test"},
        ) as runner:
            experiment_cli.main(["--generate-answers"])

        self.assertTrue(runner.call_args.kwargs["generate_answers"])
        self.assertTrue(runner.call_args.kwargs["no_llm"])

    def test_experiment_cli_defaults_to_unbounded_context_for_fair_comparison(self) -> None:
        with patch(
            "memory_observatory.services.experiment_cli.run_experiment",
            return_value={"run_id": "run-test"},
        ) as runner:
            experiment_cli.main([])

        self.assertEqual(runner.call_args.kwargs["max_context_chars"], 0)

    def test_experiment_cli_can_opt_into_llm_planner(self) -> None:
        with patch(
            "memory_observatory.services.experiment_cli.run_experiment",
            return_value={"run_id": "run-test"},
        ) as runner:
            experiment_cli.main(["--generate-answers", "--use-llm-planner"])

        self.assertTrue(runner.call_args.kwargs["generate_answers"])
        self.assertFalse(runner.call_args.kwargs["no_llm"])

    def test_experiment_cli_accepts_budget_profile(self) -> None:
        with patch(
            "memory_observatory.services.experiment_cli.run_experiment",
            return_value={"run_id": "run-test"},
        ) as runner:
            experiment_cli.main(["--budget-profile", "large_corpus_tight"])

        self.assertEqual(runner.call_args.kwargs["budget_profile"], "large_corpus_tight")

    def test_experiment_cli_accepts_realistic_budget_controls(self) -> None:
        with patch(
            "memory_observatory.services.experiment_cli.run_experiment",
            return_value={"run_id": "run-test"},
        ) as runner:
            experiment_cli.main(
                [
                    "--full-context-scope",
                    "all",
                    "--baseline-token-multiplier",
                    "5",
                    "--rag-top-k",
                    "999",
                ]
            )

        self.assertEqual(runner.call_args.kwargs["full_context_scope"], "all")
        self.assertEqual(runner.call_args.kwargs["baseline_token_multiplier"], 5.0)
        self.assertEqual(runner.call_args.kwargs["rag_top_k"], 999)

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

    def test_export_observatory_results_to_v2_scoring_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "observatory_test"
            _write_json(
                run_dir / "results.json",
                {
                    "run_id": "observatory_test",
                    "queries": [
                        {
                            "query_id": "q001",
                            "query": "Why use layered memory?",
                            "category": "topic_synthesis",
                            "expected_route": "long_term",
                            "expected_winner": "Layered Memory",
                            "expected_answer": "It should ground answers in L1 evidence and add L2/L3 evolution context.",
                            "expected_obj_ids": ["L1-0307-001"],
                            "strategies": {
                                "layered_memory": {
                                    "answer": "Layered memory starts from L1 evidence and adds topic evolution.",
                                    "metrics": {
                                        "estimated_context_tokens": 300,
                                        "actual_total_tokens": 500,
                                        "token_source": "actual_usage_metadata",
                                    },
                                },
                                "rag_baseline": {
                                    "answer": "RAG returns local chunks.",
                                    "metrics": {"estimated_context_tokens": 280},
                                },
                                "full_context": {
                                    "answer": "Full context injects everything.",
                                    "metrics": {"estimated_context_tokens": 3000},
                                },
                            },
                        }
                    ],
                },
            )
            out_csv = Path(tmp) / "scoring" / "observatory_answers.csv"

            summary = export_observatory_run_to_scoring_csv(run_dir, out_csv)

            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(summary["missing_expected_answer_count"], 0)
            rows = out_csv.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 2)
            self.assertIn("agent_answer", rows[0])
            self.assertIn("Layered memory starts from L1 evidence", rows[1])
            self.assertIn("RAG returns local chunks", rows[1])
            self.assertTrue((out_csv.with_suffix(".summary.json")).exists())

    def test_eval_query_loader_accepts_csv_gold_questions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "doc" / "evaluation_questions.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text(
                "question_id,category,question,expected_answer,gold_l1_obj_ids,expected_l2_ids,expected_l3_ids\n"
                "VM-E01,topic_synthesis,Why layered memory?,Use L1 evidence.,L1-0307-001,L2-memory,L3-memory\n",
                encoding="utf-8",
            )

            rows = ObservatoryDataLoader(root).load_eval_queries(csv_path)

        self.assertEqual(rows[0]["query_id"], "VM-E01")
        self.assertEqual(rows[0]["query"], "Why layered memory?")
        self.assertEqual(rows[0]["expected_answer"], "Use L1 evidence.")
        self.assertEqual(rows[0]["expected_obj_ids"], ["L1-0307-001"])

    def test_experiment_preserves_csv_gold_fields_for_scoring_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_repo(root)
            csv_path = root / "doc" / "evaluation_questions.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text(
                "question_id,category,expected_route,expected_winner,question,expected_answer,gold_l1_obj_ids\n"
                "VM-E01,topic_synthesis,long_term,Layered Memory,Why layered memory?,Use L1 evidence.,L1-0307-001\n",
                encoding="utf-8",
            )

            result = run_experiment(
                repo_root=root,
                queries_path=csv_path,
                out=root / "memory_observatory" / "runs",
                strategies=["rag_baseline"],
                retrieval_mode="lexical",
                no_llm=True,
                generate_answers=False,
            )

        query = result["queries"][0]
        self.assertEqual(query["query_id"], "VM-E01")
        self.assertEqual(query["category"], "topic_synthesis")
        self.assertEqual(query["expected_answer"], "Use L1 evidence.")
        self.assertEqual(query["expected_winner"], "Layered Memory")

    def test_v2_scorer_can_select_answer_only_variant(self) -> None:
        from app.score_evaluation_answers_v2 import selected_variants

        self.assertEqual(selected_variants("answer"), [("answer", "Answer")])
        self.assertEqual(selected_variants("answer,evidence"), [("answer", "Answer"), ("evidence", "Evidence")])


if __name__ == "__main__":
    unittest.main()
