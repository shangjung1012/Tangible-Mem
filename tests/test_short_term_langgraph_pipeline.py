from __future__ import annotations

import json
import os
import queue
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

for module_name in (
    "short_term.agents",
    "short_term.core.graph_state",
    "short_term.core.reducer",
    "short_term.runtime.research_logger",
    "short_term.core.verifier",
):
    sys.modules.pop(module_name, None)

from short_term.core.reducer import reduce_candidates  # noqa: E402
from short_term.runtime.research_logger import ResearchLogger  # noqa: E402
from short_term.workflow.langgraph_update import (  # noqa: E402
    _build_graph,
    _candidate_payload_is_sparse,
    _extract_candidates,
)
from short_term.runtime.genai_retry import call_with_retry  # noqa: E402
from short_term.storage.memory_tools import (  # noqa: E402
    AgentToolContext,
    AgentToolPolicy,
    read_short_term_memory_tool,
    write_memory_candidate_tool,
)
from short_term.storage.sqlite_store import save_memory_to_sqlite  # noqa: E402
from short_term.storage.staging_store import load_staged_candidates  # noqa: E402
from short_term.storage.staging_store import update_staged_candidate_statuses  # noqa: E402
from short_term.storage.staging_store import write_staged_candidate  # noqa: E402
from short_term.storage.transcript_store import import_transcript_to_sqlite  # noqa: E402
from short_term.core.verifier import verify_candidates  # noqa: E402
from short_term.agents.base import GeminiJsonAgent  # noqa: E402


class ShortTermLangGraphPipelineTests(unittest.TestCase):
    def test_research_logger_writes_debug_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ResearchLogger(
                Path(tmpdir),
                "Bmr001",
                run_id="run_Bmr001",
            )
            logger.write_run_meta({"meeting_id": "Bmr001"})
            logger.graph_event(
                node="segment_window",
                event="end",
                summary={"units": 2},
                line_range="L1-L10",
                duration_seconds=1.25,
            )
            logger.agent_call(
                agent_name="segment_agent",
                prompt_version="v",
                model_name="gemini-2.5-pro",
                temperature=0.1,
                input_summary={"line_range": "L1-L10"},
                prompt="PROMPT",
                raw_response='{"units":[]}',
                parsed={"units": []},
                errors=[],
                retry_count=0,
                retry_events=[],
                latency_seconds=0.5,
            )
            logger.final_outputs(
                final_patch={"next_meeting_focus": ["追蹤資料"]},
                final_memory={"memory_version": 1},
                report={"run_id": "run_Bmr001", "candidate_counts": {"raw": 0}},
            )

            run_dir = Path(tmpdir) / "run_Bmr001"
            self.assertTrue((run_dir / "run_meta.json").exists())
            self.assertTrue((run_dir / "graph_events.jsonl").exists())
            self.assertTrue((run_dir / "prompts" / "001_segment_agent.prompt.txt").exists())
            self.assertTrue((run_dir / "responses" / "001_segment_agent.raw.txt").exists())
            self.assertTrue((run_dir / "responses" / "001_segment_agent.parsed.json").exists())
            self.assertTrue((run_dir / "report.md").exists())

    def test_research_logger_records_retry_events_in_agent_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ResearchLogger(Path(tmpdir), "Bmr001", run_id="run_Bmr001")
            logger.agent_call(
                agent_name="action_item_agent",
                prompt_version="v",
                model_name="gemini-2.5-pro",
                temperature=0.1,
                input_summary={},
                prompt="PROMPT",
                raw_response='{"action_items":[]}',
                parsed={"action_items": []},
                errors=[],
                retry_count=1,
                retry_events=[
                    {
                        "operation_name": "action_item_agent generate_content",
                        "attempt": 1,
                        "max_retries": 15,
                        "delay_seconds": 2.0,
                        "error_type": "RuntimeError",
                        "error": "503 unavailable",
                    }
                ],
                latency_seconds=0.5,
            )

            meta_path = (
                Path(tmpdir)
                / "run_Bmr001"
                / "responses"
                / "001_action_item_agent.meta.json"
            )
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["retry_count"], 1)
            self.assertEqual(meta["retry_events"][0]["attempt"], 1)

    def test_call_with_retry_emits_retry_events(self) -> None:
        attempts = {"count": 0}
        events: list[dict[str, object]] = []

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("503 unavailable")
            return "ok"

        result = call_with_retry(
            flaky,
            operation_name="test operation",
            max_retries=2,
            on_retry=events.append,
            sleep_func=lambda _: None,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["attempt"], 1)
        self.assertEqual(events[0]["operation_name"], "test operation")

    def test_call_with_retry_enforces_local_timeout(self) -> None:
        with mock.patch.dict(os.environ, {"GOOGLE_GENAI_TIMEOUT_MS": "10"}):
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                call_with_retry(
                    lambda: time.sleep(1),
                    operation_name="slow operation",
                    max_retries=1,
                )

    def test_call_with_retry_enforces_timeout_from_worker_thread(self) -> None:
        errors: queue.Queue[BaseException] = queue.Queue()

        def run() -> None:
            with mock.patch.dict(os.environ, {"GOOGLE_GENAI_TIMEOUT_MS": "10"}):
                try:
                    call_with_retry(
                        lambda: time.sleep(1),
                        operation_name="slow worker operation",
                        max_retries=1,
                    )
                except BaseException as exc:  # noqa: BLE001
                    errors.put(exc)

        worker = threading.Thread(target=run)
        worker.start()
        worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertIsInstance(errors.get_nowait(), TimeoutError)

    def test_call_with_retry_retries_timeout_once(self) -> None:
        attempts = {"count": 0}
        events: list[dict[str, object]] = []

        def slow_then_ok() -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                time.sleep(1)
            return "ok"

        with mock.patch.dict(os.environ, {"GOOGLE_GENAI_TIMEOUT_MS": "10"}):
            result = call_with_retry(
                slow_then_ok,
                operation_name="slow then ok",
                max_retries=15,
                on_retry=events.append,
                sleep_func=lambda _: None,
            )

        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(events[0]["error_type"], "TimeoutError")
        self.assertEqual(events[0]["max_retries"], 2)

    def test_tool_agent_repairs_empty_final_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ResearchLogger(Path(tmpdir), "Bmr001", run_id="run_Bmr001")
            chat = _FakeChat(
                [
                    _FakeResponse(""),
                    _FakeResponse('{"experiment_todos": []}'),
                ]
            )
            agent = GeminiJsonAgent(
                name="experiment_todo_agent",
                client=_FakeClient(chat),
                model_name="gemini-2.5-pro",
                schema={"type": "object", "properties": {"experiment_todos": {"type": "array"}}},
            )

            result = agent.run(
                prompt="Extract experiment todos.",
                logger=logger,
                input_summary={},
                tool_context=AgentToolContext(
                    db_path=Path(tmpdir) / "memory.db",
                    run_id="run_Bmr001",
                    meeting_id="Bmr001",
                    policy=AgentToolPolicy(
                        agent_name="experiment_todo_agent",
                        write_sections={"experiment_todos"},
                    ),
                ),
            )
            meta_path = (
                Path(tmpdir)
                / "run_Bmr001"
                / "responses"
                / "001_experiment_todo_agent.meta.json"
            )
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            self.assertEqual(result.errors, [])
            self.assertEqual(result.parsed, {"experiment_todos": []})
            self.assertEqual(chat.messages_sent, 2)
            self.assertEqual(meta["retry_count"], 1)
            self.assertEqual(meta["retry_events"][0]["error_type"], "EmptyModelResponse")

    def test_verifier_rejects_missing_evidence_and_unknown_update_id(self) -> None:
        current_memory = {
            "action_items": [
                {
                    "item_id": "A001",
                    "title": "Existing",
                    "status": "open",
                    "priority": "medium",
                }
            ],
            "method_changes": [],
            "experiment_todos": [],
        }
        candidates = [
            {
                "agent": "action_item_agent",
                "section": "action_items",
                "candidate_id": "bad",
                "payload": {
                    "item_id": "A999",
                    "title": "Update missing",
                    "detail": "x",
                    "proposer": "unknown",
                    "owner": "unknown",
                    "status": "open",
                    "priority": "medium",
                    "dependencies": [],
                    "evidence": "L2",
                    "operation": "update",
                    "confidence": 0.8,
                },
            },
            {
                "agent": "next_focus_agent",
                "section": "next_meeting_focus",
                "candidate_id": "no-evidence",
                "payload": {
                    "text": "下次追蹤資料",
                    "evidence": "",
                    "confidence": 0.9,
                },
            },
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory=current_memory,
            allowed_line_numbers={1, 2, 3},
        )

        self.assertEqual(verified, [])
        self.assertEqual(len(rejected), 2)
        self.assertEqual(counts["update_unknown_id"], 1)
        self.assertEqual(counts["missing_evidence"], 1)

    def test_verifier_allows_no_op_without_focus_text(self) -> None:
        candidates = [
            {
                "agent": "next_focus_agent",
                "section": "next_meeting_focus",
                "candidate_id": "focus-no-op",
                "payload": {
                    "operation": "no_op",
                    "text": "",
                    "evidence": "L1",
                    "confidence": 0.9,
                },
            }
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory={"action_items": [], "method_changes": [], "experiment_todos": []},
            allowed_line_numbers={1},
        )

        self.assertEqual(len(verified), 1)
        self.assertEqual(rejected, [])
        self.assertEqual(counts, {})

    def test_verifier_recovers_meeting_evidence_from_structured_line_refs(self) -> None:
        candidates = [
            {
                "agent": "meeting_summary_agent",
                "section": "meeting_window",
                "candidate_id": "meeting",
                "payload": {
                    "meeting_id": "0307",
                    "summary": "Discussed memory architecture.",
                    "key_points": [
                        "Defined STM and LTM boundaries (L4-L6).",
                        "Discussed evaluation planning (L10-L11).",
                    ],
                    "open_questions": ["How should it be evaluated? (L12)"],
                    "evidence": "Evidence based on idea units 1, 2.",
                    "operation": "create",
                    "confidence": 0.9,
                },
            }
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory={"action_items": [], "method_changes": [], "experiment_todos": []},
            allowed_line_numbers=set(range(1, 20)),
        )

        self.assertEqual(len(verified), 1)
        self.assertEqual(rejected, [])
        self.assertEqual(counts, {})
        self.assertEqual(verified[0]["payload"]["evidence"], "L4-L6, L10-L12")

    def test_verifier_does_not_mask_explicit_out_of_window_evidence(self) -> None:
        candidates = [
            {
                "agent": "meeting_summary_agent",
                "section": "meeting_window",
                "candidate_id": "meeting",
                "payload": {
                    "meeting_id": "0307",
                    "summary": "Discussed memory architecture.",
                    "key_points": ["Defined STM and LTM boundaries (L4-L6)."],
                    "evidence": "L999",
                    "operation": "create",
                    "confidence": 0.9,
                },
            }
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory={"action_items": [], "method_changes": [], "experiment_todos": []},
            allowed_line_numbers=set(range(1, 20)),
        )

        self.assertEqual(verified, [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(counts["evidence_line_not_read"], 1)
        self.assertEqual(rejected[0]["payload"]["evidence"], "L999")

    def test_verifier_strips_non_canonical_create_ids(self) -> None:
        candidates = [
            {
                "agent": "action_item_agent",
                "section": "action_items",
                "candidate_id": "temp-id",
                "payload": {
                    "item_id": "Bmr009-temp-1",
                    "title": "Simplify analysis",
                    "detail": "Start with 1D distributions.",
                    "proposer": "me013",
                    "owner": "unknown",
                    "status": "open",
                    "priority": "low",
                    "dependencies": [],
                    "evidence": "L1",
                    "operation": "create",
                    "confidence": 0.9,
                },
            }
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory={"action_items": [], "method_changes": [], "experiment_todos": []},
            allowed_line_numbers={1},
        )
        patch = reduce_candidates(verified)

        self.assertEqual(rejected, [])
        self.assertEqual(counts, {})
        self.assertEqual(len(verified), 1)
        self.assertNotIn("item_id", patch["action_items"][0])

    def test_verifier_rejects_non_canonical_update_ids(self) -> None:
        candidates = [
            {
                "agent": "method_change_agent",
                "section": "method_changes",
                "candidate_id": "bad-method-update",
                "payload": {
                    "change_id": "Bmr003-MC-4",
                    "topic": "format",
                    "status": "active",
                    "evidence": "L1",
                    "operation": "update",
                    "confidence": 0.9,
                },
            },
            {
                "agent": "experiment_todo_agent",
                "section": "experiment_todos",
                "candidate_id": "bad-todo-update",
                "payload": {
                    "todo_id": "Bmr005-TODO-1",
                    "description": "Run experiment",
                    "status": "open",
                    "owner": "unknown",
                    "related_action_item_ids": [],
                    "evidence": "L1",
                    "operation": "update",
                    "confidence": 0.9,
                },
            },
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory={
                "action_items": [],
                "method_changes": [{"change_id": "M001"}],
                "experiment_todos": [{"todo_id": "E001"}],
            },
            allowed_line_numbers={1},
        )

        self.assertEqual(verified, [])
        self.assertEqual(len(rejected), 2)
        self.assertEqual(counts["invalid_method_change_id"], 1)
        self.assertEqual(counts["invalid_experiment_todo_id"], 1)

    def test_sparse_candidate_payload_detection(self) -> None:
        self.assertTrue(
            _candidate_payload_is_sparse(
                {
                    "payload": {
                        "operation": "create",
                        "confidence": 0.9,
                        "evidence": "L1",
                    }
                }
            )
        )
        self.assertFalse(
            _candidate_payload_is_sparse(
                {
                    "payload": {
                        "operation": "create",
                        "confidence": 0.9,
                        "title": "Prepare data",
                    }
                }
            )
        )
        self.assertFalse(
            _candidate_payload_is_sparse(
                {
                    "operation": "no_op",
                    "payload": {
                        "operation": "no_op",
                        "confidence": 0.9,
                        "evidence": "L1",
                    },
                }
            )
        )

    def test_staging_rejects_sparse_candidate_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "memory.db"
            result = write_staged_candidate(
                db_path,
                run_id="run",
                meeting_id="Bmr001",
                agent_name="action_item_agent",
                target_section="action_items",
                operation="create",
                candidate_payload={},
                confidence=0.9,
            )
            staged = load_staged_candidates(
                db_path,
                run_id="run",
                agent_name="action_item_agent",
                target_section="action_items",
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "sparse_candidate_payload")
            self.assertEqual(staged, [])

    def test_staging_accepts_sparse_no_op_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "memory.db"
            result = write_staged_candidate(
                db_path,
                run_id="run",
                meeting_id="Bmr001",
                agent_name="action_item_agent",
                target_section="action_items",
                operation="no_op",
                candidate_payload={},
                confidence=0.9,
            )
            staged = load_staged_candidates(
                db_path,
                run_id="run",
                agent_name="action_item_agent",
                target_section="action_items",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(len(staged), 1)
            self.assertEqual(staged[0]["operation"], "no_op")

    def test_staging_uses_evidence_lines_not_quote_for_payload_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "memory.db"
            result = write_staged_candidate(
                db_path,
                run_id="run",
                meeting_id="Bmr001",
                agent_name="action_item_agent",
                target_section="action_items",
                operation="create",
                candidate_payload={
                    "title": "Prepare data",
                    "detail": "Prepare data.",
                    "proposer": "unknown",
                    "owner": "unknown",
                    "status": "open",
                    "priority": "medium",
                    "dependencies": [],
                },
                evidence_lines=[3, 4, 6],
                evidence_quote="We should prepare the data.",
                confidence=0.9,
            )
            staged = load_staged_candidates(
                db_path,
                run_id="run",
                agent_name="action_item_agent",
                target_section="action_items",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(staged[0]["payload"]["evidence"], "L3-L4, L6")
            self.assertEqual(staged[0]["evidence_quote"], "We should prepare the data.")

    def test_extract_candidates_fails_when_agent_errors_without_usable_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            logger = ResearchLogger(tmp / "logs", "Bmr001", run_id="run_Bmr001")
            state = {
                "run_id": "run_Bmr001",
                "meeting_id": "Bmr001",
                "source_file": "Bmr001.txt",
                "model_name": "gemini-2.5-pro",
                "db_path": str(tmp / "memory.db"),
                "transcript_db_path": str(tmp / "transcripts.db"),
                "checkpoint_db_path": str(tmp / "checkpoint.db"),
                "research_log_dir": str(tmp / "logs"),
                "log_level": "debug",
                "keep_full_prompts": True,
                "dry_run": True,
                "transcript_line_count": 1,
                "transcript_overview": {"line_count": 1},
                "current_memory": {
                    "action_items": [],
                    "method_changes": [],
                    "experiment_todos": [],
                },
                "current_window": {
                    "context_start_line": 1,
                    "context_end_line": 1,
                    "forward_start_line": 1,
                    "forward_end_line": 1,
                    "items": [{"line_number": 1, "text": "We should prepare the data."}],
                },
                "current_units": [
                    {
                        "unit_id": "U001",
                        "line_start": 1,
                        "line_end": 1,
                        "topic": "prepare data",
                        "kind_hint": ["action_item"],
                        "needs_more_context": False,
                    }
                ],
                "raw_candidates": [],
                "tool_reads": {},
            }
            agent = _FakeAgent(
                "action_item_agent",
                {},
                errors=["LLM returned an empty response."],
            )

            with self.assertRaisesRegex(RuntimeError, "LLM agent failed in extract_action_items"):
                _extract_candidates(
                    state,  # type: ignore[arg-type]
                    logger,
                    agent,
                    "action_items",
                    "action_items",
                    "Extract action items.",
                )

    def test_extract_candidates_retries_after_agent_parse_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            logger = ResearchLogger(tmp / "logs", "Bmr001", run_id="run_Bmr001")
            state = {
                "run_id": "run_Bmr001",
                "meeting_id": "Bmr001",
                "source_file": "Bmr001.txt",
                "model_name": "gemini-2.5-pro",
                "db_path": str(tmp / "memory.db"),
                "transcript_db_path": str(tmp / "transcripts.db"),
                "checkpoint_db_path": str(tmp / "checkpoint.db"),
                "research_log_dir": str(tmp / "logs"),
                "log_level": "debug",
                "keep_full_prompts": True,
                "dry_run": True,
                "transcript_line_count": 1,
                "transcript_overview": {"line_count": 1},
                "current_memory": {
                    "action_items": [],
                    "method_changes": [],
                    "experiment_todos": [],
                },
                "current_window": {
                    "context_start_line": 1,
                    "context_end_line": 1,
                    "forward_start_line": 1,
                    "forward_end_line": 1,
                    "items": [{"line_number": 1, "text": "We should prepare the data."}],
                },
                "current_units": [
                    {
                        "unit_id": "U001",
                        "line_start": 1,
                        "line_end": 1,
                        "topic": "prepare data",
                        "kind_hint": ["action_item"],
                        "needs_more_context": False,
                    }
                ],
                "raw_candidates": [],
                "tool_reads": {},
            }
            agent = _FakeAgent(
                "action_item_agent",
                [
                    ({}, ["Expecting ',' delimiter"]),
                    (
                        {
                            "action_items": [
                                {
                                    "operation": "create",
                                    "title": "Prepare data",
                                    "detail": "Prepare the data.",
                                    "proposer": "unknown",
                                    "owner": "unknown",
                                    "status": "open",
                                    "priority": "medium",
                                    "dependencies": [],
                                    "evidence": "L1",
                                    "confidence": 0.9,
                                }
                            ]
                        },
                        [],
                    ),
                ],
            )

            candidates = _extract_candidates(
                state,  # type: ignore[arg-type]
                logger,
                agent,
                "action_items",
                "action_items",
                "Extract action items.",
            )

            self.assertEqual(agent.call_count, 2)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["payload"]["title"], "Prepare data")

    def test_extract_candidates_passes_staging_tool_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            logger = ResearchLogger(tmp / "logs", "Bmr001", run_id="run_Bmr001")
            state = {
                "run_id": "run_Bmr001",
                "meeting_id": "Bmr001",
                "source_file": "Bmr001.txt",
                "model_name": "gemini-2.5-pro",
                "db_path": str(tmp / "memory.db"),
                "transcript_db_path": str(tmp / "transcripts.db"),
                "checkpoint_db_path": str(tmp / "checkpoint.db"),
                "research_log_dir": str(tmp / "logs"),
                "log_level": "debug",
                "keep_full_prompts": True,
                "dry_run": True,
                "transcript_line_count": 1,
                "transcript_overview": {"line_count": 1},
                "current_memory": {
                    "action_items": [],
                    "method_changes": [],
                    "experiment_todos": [],
                },
                "current_window": {
                    "context_start_line": 1,
                    "context_end_line": 1,
                    "forward_start_line": 1,
                    "forward_end_line": 1,
                    "items": [{"line_number": 1, "text": "We should prepare the data."}],
                },
                "current_units": [
                    {
                        "unit_id": "U001",
                        "line_start": 1,
                        "line_end": 1,
                        "topic": "prepare data",
                        "kind_hint": ["action_item"],
                        "needs_more_context": False,
                    }
                ],
                "raw_candidates": [],
                "tool_reads": {},
            }
            agent = _FakeAgent("action_item_agent", {"action_items": []})

            _extract_candidates(
                state,  # type: ignore[arg-type]
                logger,
                agent,
                "action_items",
                "action_items",
                "Extract action items.",
            )

            context = agent.last_kwargs.get("tool_context")
            self.assertIsInstance(context, AgentToolContext)
            self.assertEqual(context.policy.agent_name, "action_item_agent")
            self.assertEqual(context.policy.write_sections, {"action_items"})

    def test_verifier_accepts_valid_candidates_and_reducer_builds_patch(self) -> None:
        candidates = [
            {
                "agent": "action_item_agent",
                "section": "action_items",
                "candidate_id": "action",
                "payload": {
                    "item_id": "",
                    "title": "整理實驗資料",
                    "detail": "整理新的實驗資料格式",
                    "proposer": "unknown",
                    "owner": "unknown",
                    "status": "open",
                    "priority": "medium",
                    "dependencies": [],
                    "evidence": "L1-L2",
                    "operation": "create",
                    "confidence": 0.9,
                },
            },
            {
                "agent": "next_focus_agent",
                "section": "next_meeting_focus",
                "candidate_id": "focus",
                "payload": {
                    "text": "追蹤實驗資料格式",
                    "evidence": "L2",
                    "confidence": 0.8,
                },
            },
        ]

        verified, rejected, _ = verify_candidates(
            candidates,
            current_memory={"action_items": [], "method_changes": [], "experiment_todos": []},
            allowed_line_numbers={1, 2},
        )
        patch = reduce_candidates(verified)

        self.assertEqual(rejected, [])
        self.assertEqual(patch["action_items"][0]["title"], "整理實驗資料")
        self.assertNotIn("operation", patch["action_items"][0])
        self.assertNotIn("confidence", patch["action_items"][0])
        self.assertEqual(patch["action_items"][0]["evidence"], "L1-L2")
        self.assertEqual(patch["next_meeting_focus"], ["追蹤實驗資料格式"])

    def test_reducer_merges_multiple_meeting_window_candidates(self) -> None:
        candidates = [
            {
                "agent": "meeting_summary_agent",
                "section": "meeting_window",
                "candidate_id": "meeting-early",
                "payload": {
                    "meeting_id": "Bmr002",
                    "source_file": "Bmr002.txt",
                    "summary": "The meeting started with microphone setup.",
                    "key_points": ["Microphone channels were mapped."],
                    "open_questions": [],
                    "evidence": "L1-L80",
                    "confidence": 0.98,
                },
            },
            {
                "agent": "meeting_summary_agent",
                "section": "meeting_window",
                "candidate_id": "meeting-later",
                "payload": {
                    "meeting_id": "Bmr002",
                    "source_file": "Bmr002.txt",
                    "summary": "Later discussion covered transcript alignment and data formats.",
                    "key_points": ["Transcript alignment was considered feasible."],
                    "open_questions": ["Which transcription data format should be used?"],
                    "evidence": "L985-L1030",
                    "confidence": 1.0,
                },
            },
            {
                "agent": "meeting_summary_agent",
                "section": "meeting_window",
                "candidate_id": "meeting-no-op",
                "payload": {
                    "meeting_id": "Bmr002",
                    "source_file": "Bmr002.txt",
                    "summary": "no_op: procedural aside with no substantive summary update.",
                    "key_points": [],
                    "open_questions": [],
                    "evidence": "L1200",
                    "confidence": 0.9,
                },
            },
        ]

        patch = reduce_candidates(candidates)

        self.assertEqual(len(patch["meeting_window"]), 1)
        meeting = patch["meeting_window"][0]
        self.assertEqual(meeting["meeting_id"], "Bmr002")
        self.assertIn("microphone setup", meeting["summary"])
        self.assertIn("transcript alignment", meeting["summary"])
        self.assertNotIn("no_op", meeting["summary"])
        self.assertEqual(
            meeting["key_points"],
            [
                "Microphone channels were mapped.",
                "Transcript alignment was considered feasible.",
            ],
        )
        self.assertEqual(
            meeting["open_questions"],
            ["Which transcription data format should be used?"],
        )
        self.assertEqual(meeting["evidence"], "L1-L80, L985-L1030")

    def test_verifier_rejects_duplicate_create(self) -> None:
        candidates = [
            {
                "agent": "action_item_agent",
                "section": "action_items",
                "candidate_id": "dup",
                "payload": {
                    "item_id": "",
                    "title": "整理實驗資料",
                    "detail": "duplicate",
                    "proposer": "unknown",
                    "owner": "unknown",
                    "status": "open",
                    "priority": "medium",
                    "dependencies": [],
                    "operation": "create",
                    "confidence": 0.9,
                },
            }
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory={
                "action_items": [{"item_id": "A001", "title": "整理實驗資料"}],
                "method_changes": [],
                "experiment_todos": [],
            },
            allowed_line_numbers=set(),
        )

        self.assertEqual(verified, [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(counts["duplicate_create"], 1)

    def test_verifier_rejects_completed_experiment_create(self) -> None:
        candidates = [
            {
                "agent": "experiment_todo_agent",
                "section": "experiment_todos",
                "candidate_id": "done",
                "payload": {
                    "todo_id": "",
                    "description": "Adam reads the digit list on headset two.",
                    "status": "completed",
                    "owner": "me011",
                    "related_action_item_ids": [],
                    "evidence": "L1-L3",
                    "operation": "create",
                    "confidence": 0.9,
                },
            }
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory={
                "action_items": [],
                "method_changes": [],
                "experiment_todos": [],
            },
            allowed_line_numbers={1, 2, 3},
        )

        self.assertEqual(verified, [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(counts["completed_create_not_allowed"], 1)

    def test_verifier_rejects_unknown_related_action_item_ref(self) -> None:
        candidates = [
            {
                "agent": "experiment_todo_agent",
                "section": "experiment_todos",
                "candidate_id": "bad-ref",
                "payload": {
                    "todo_id": "",
                    "description": "Run evaluation",
                    "status": "open",
                    "owner": "unknown",
                    "related_action_item_ids": ["A999"],
                    "evidence": "L1",
                    "operation": "create",
                    "confidence": 0.9,
                },
            }
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory={
                "action_items": [{"item_id": "A001", "title": "Existing"}],
                "method_changes": [],
                "experiment_todos": [],
            },
            allowed_line_numbers={1},
        )

        self.assertEqual(verified, [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(counts["related_action_item_unknown_id"], 1)

    def test_verifier_rejects_inventory_only_method_change(self) -> None:
        candidates = [
            {
                "agent": "method_change_agent",
                "section": "method_changes",
                "candidate_id": "inventory",
                "payload": {
                    "change_id": "M001",
                    "topic": "Microphone setup for recording",
                    "before": "Not specified",
                    "after": "Multiple microphones were used for recording.",
                    "reason": "To document the recording setup for the experiment.",
                    "status": "active",
                    "evidence": "L1-L5",
                    "operation": "create",
                    "confidence": 0.9,
                },
            }
        ]

        verified, rejected, counts = verify_candidates(
            candidates,
            current_memory={
                "action_items": [],
                "method_changes": [],
                "experiment_todos": [],
            },
            allowed_line_numbers={1, 2, 3, 4, 5},
        )

        self.assertEqual(verified, [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(counts["inventory_not_method_change"], 1)

    def test_graph_event_jsonl_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ResearchLogger(Path(tmpdir), "Bmr002", run_id="run_Bmr002")
            logger.graph_event(node="n", event="start", summary={"x": 1})
            path = Path(tmpdir) / "run_Bmr002" / "graph_events.jsonl"
            payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(payload["run_id"], "run_Bmr002")
            self.assertEqual(payload["node"], "n")

    def test_langgraph_fails_fast_on_planner_llm_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            transcript_db = tmp / "transcripts.db"
            memory_db = tmp / "memory.db"
            import_transcript_to_sqlite(
                db_path=transcript_db,
                meeting_id="Bmr005",
                source_file="Bmr005.txt",
                transcript="[S]: We should prepare the experiment data next.",
            )
            logger = ResearchLogger(tmp / "logs", "Bmr005", run_id="run_Bmr005")
            agents = _FakeAgents()
            agents.context_planner = _FakeAgent(
                "context_planner",
                {},
                errors=["403 PERMISSION_DENIED"],
            )
            graph = _build_graph(
                agents=agents,
                logger=logger,
                db_path=memory_db,
                transcript_db_path=transcript_db,
            )

            with self.assertRaisesRegex(RuntimeError, "403 PERMISSION_DENIED"):
                graph.compile().invoke(
                    {
                        "run_id": "run_Bmr005",
                        "meeting_id": "Bmr005",
                        "source_file": "Bmr005.txt",
                        "model_name": "gemini-2.5-pro",
                        "db_path": str(memory_db),
                        "transcript_db_path": str(transcript_db),
                        "checkpoint_db_path": str(tmp / "checkpoint.db"),
                        "research_log_dir": str(tmp / "logs"),
                        "log_level": "debug",
                        "keep_full_prompts": True,
                        "dry_run": False,
                        "chunk_size": 80,
                        "max_lookback_lines": 20,
                        "max_lookahead_lines": 40,
                        "max_context_rounds": 3,
                        "transcript_line_count": 1,
                        "transcript_overview": {"line_count": 1},
                        "current_memory": {
                            "memory_version": 0,
                            "meeting_history_ids": [],
                            "meeting_window": [],
                            "action_items": [],
                            "method_changes": [],
                            "experiment_todos": [],
                            "next_meeting_focus": [],
                        },
                        "memory_source": "default",
                        "processed_until_line": 0,
                        "planner_history": [],
                        "context_rounds": 0,
                        "unresolved_context": [],
                        "raw_candidates": [],
                        "verified_candidates": [],
                        "rejected_candidates": [],
                        "final_patch": {},
                        "final_memory": {},
                        "report": {},
                        "persisted": False,
                        "read_line_numbers": [],
                    }
                )

            events = [
                json.loads(line)
                for line in (logger.run_dir / "graph_events.jsonl").read_text().splitlines()
            ]
            self.assertTrue(
                any(
                    event["node"] == "plan_next_window"
                    and event["status"] == "error"
                    for event in events
                )
            )
            with sqlite3.connect(str(memory_db)) as conn:
                canonical_rows = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    AND name IN ('memory_meta', 'meeting_window')
                    """
                ).fetchall()
            self.assertEqual(canonical_rows, [])

    def test_langgraph_refuses_to_persist_without_meeting_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            transcript_db = tmp / "transcripts.db"
            memory_db = tmp / "memory.db"
            import_transcript_to_sqlite(
                db_path=transcript_db,
                meeting_id="Bmr006",
                source_file="Bmr006.txt",
                transcript="[S]: We should prepare the experiment data next.",
            )
            logger = ResearchLogger(tmp / "logs", "Bmr006", run_id="run_Bmr006")
            graph = _build_graph(
                agents=_NoMeetingSummaryFakeAgents(),
                logger=logger,
                db_path=memory_db,
                transcript_db_path=transcript_db,
            )

            with self.assertRaisesRegex(RuntimeError, "Missing meeting_window summary"):
                graph.compile().invoke(
                    {
                        "run_id": "run_Bmr006",
                        "meeting_id": "Bmr006",
                        "source_file": "Bmr006.txt",
                        "model_name": "gemini-2.5-pro",
                        "db_path": str(memory_db),
                        "transcript_db_path": str(transcript_db),
                        "checkpoint_db_path": str(tmp / "checkpoint.db"),
                        "research_log_dir": str(tmp / "logs"),
                        "log_level": "debug",
                        "keep_full_prompts": True,
                        "dry_run": False,
                        "chunk_size": 80,
                        "max_lookback_lines": 20,
                        "max_lookahead_lines": 40,
                        "max_context_rounds": 3,
                        "transcript_line_count": 1,
                        "transcript_overview": {"line_count": 1},
                        "current_memory": {
                            "memory_version": 0,
                            "meeting_history_ids": [],
                            "meeting_window": [],
                            "action_items": [],
                            "method_changes": [],
                            "experiment_todos": [],
                            "next_meeting_focus": [],
                        },
                        "memory_source": "default",
                        "processed_until_line": 0,
                        "planner_history": [],
                        "context_rounds": 0,
                        "unresolved_context": [],
                        "raw_candidates": [],
                        "verified_candidates": [],
                        "rejected_candidates": [],
                        "final_patch": {},
                        "final_memory": {},
                        "report": {},
                        "persisted": False,
                        "read_line_numbers": [],
                    }
                )

            with sqlite3.connect(str(memory_db)) as conn:
                canonical_rows = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    AND name IN ('memory_meta', 'meeting_window')
                    """
                ).fetchall()
            self.assertEqual(canonical_rows, [])

    def test_langgraph_runner_shape_with_fake_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            transcript_db = tmp / "transcripts.db"
            memory_db = tmp / "memory.db"
            import_transcript_to_sqlite(
                db_path=transcript_db,
                meeting_id="Bmr003",
                source_file="Bmr003.txt",
                transcript="[S]: We should prepare the experiment data next.",
            )
            logger = ResearchLogger(tmp / "logs", "Bmr003", run_id="run_Bmr003")
            graph = _build_graph(
                agents=_FakeAgents(),
                logger=logger,
                db_path=memory_db,
                transcript_db_path=transcript_db,
            )
            state = graph.compile().invoke(
                {
                    "run_id": "run_Bmr003",
                    "meeting_id": "Bmr003",
                    "source_file": "Bmr003.txt",
                    "model_name": "gemini-2.5-pro",
                    "db_path": str(memory_db),
                    "transcript_db_path": str(transcript_db),
                    "checkpoint_db_path": str(tmp / "checkpoint.db"),
                    "research_log_dir": str(tmp / "logs"),
                    "log_level": "debug",
                    "keep_full_prompts": True,
                    "dry_run": True,
                    "chunk_size": 80,
                    "max_lookback_lines": 20,
                    "max_lookahead_lines": 40,
                    "max_context_rounds": 3,
                    "transcript_line_count": 1,
                    "transcript_overview": {"line_count": 1},
                    "current_memory": {
                        "memory_version": 0,
                        "meeting_history_ids": [],
                        "meeting_window": [],
                        "action_items": [],
                        "method_changes": [],
                        "experiment_todos": [],
                        "next_meeting_focus": [],
                    },
                    "memory_source": "default",
                    "processed_until_line": 0,
                    "planner_history": [],
                    "context_rounds": 0,
                    "raw_candidates": [],
                    "verified_candidates": [],
                    "rejected_candidates": [],
                    "final_patch": {},
                    "final_memory": {},
                    "report": {},
                    "persisted": False,
                    "read_line_numbers": [],
                }
            )

            self.assertEqual(state["final_patch"]["next_meeting_focus"], ["準備實驗資料"])
            self.assertEqual(state["final_memory"]["meeting_history_ids"], ["Bmr003"])
            self.assertFalse(state["persisted"])
            events = [
                json.loads(line)
                for line in (logger.run_dir / "graph_events.jsonl").read_text().splitlines()
            ]
            read_window_end = [
                event
                for event in events
                if event["node"] == "read_window" and event["event"] == "end"
            ][0]
            self.assertEqual(read_window_end["line_range"], "L1-L1")

    def test_langgraph_accumulates_context_windows_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            transcript_db = tmp / "transcripts.db"
            memory_db = tmp / "memory.db"
            import_transcript_to_sqlite(
                db_path=transcript_db,
                meeting_id="Bmr007",
                source_file="Bmr007.txt",
                transcript="\n".join(f"[S]: line {index}" for index in range(1, 121)),
            )
            logger = ResearchLogger(tmp / "logs", "Bmr007", run_id="run_Bmr007")
            agents = _ExpandedContextFakeAgents()
            graph = _build_graph(
                agents=agents,
                logger=logger,
                db_path=memory_db,
                transcript_db_path=transcript_db,
            )

            state = graph.compile().invoke(
                {
                    "run_id": "run_Bmr007",
                    "meeting_id": "Bmr007",
                    "source_file": "Bmr007.txt",
                    "model_name": "gemini-2.5-pro",
                    "db_path": str(memory_db),
                    "transcript_db_path": str(transcript_db),
                    "checkpoint_db_path": str(tmp / "checkpoint.db"),
                    "research_log_dir": str(tmp / "logs"),
                    "log_level": "debug",
                    "keep_full_prompts": True,
                    "dry_run": True,
                    "chunk_size": 80,
                    "max_lookback_lines": 20,
                    "max_lookahead_lines": 40,
                    "max_context_rounds": 3,
                    "transcript_line_count": 120,
                    "transcript_overview": {"line_count": 120},
                    "current_memory": {
                        "memory_version": 0,
                        "meeting_history_ids": [],
                        "meeting_window": [],
                        "action_items": [],
                        "method_changes": [],
                        "experiment_todos": [],
                        "next_meeting_focus": [],
                    },
                    "memory_source": "default",
                    "processed_until_line": 0,
                    "planner_history": [],
                    "context_rounds": 0,
                    "context_units_buffer": [],
                    "context_items_buffer": [],
                    "raw_candidates": [],
                    "verified_candidates": [],
                    "rejected_candidates": [],
                    "final_patch": {},
                    "final_memory": {},
                    "report": {},
                    "persisted": False,
                    "read_line_numbers": [],
                }
            )

            meeting_prompt = str(agents.meeting.last_kwargs["prompt"])
            self.assertIn('"line_start": 1', meeting_prompt)
            self.assertIn('"line_start": 81', meeting_prompt)
            self.assertIn("L1 [S]: line 1", meeting_prompt)
            self.assertIn("L120 [S]: line 120", meeting_prompt)
            self.assertEqual(state["processed_until_line"], 120)
            self.assertEqual(state["context_units_buffer"], [])
            self.assertEqual(state["context_items_buffer"], [])

    def test_langgraph_stops_context_retry_when_planner_repeats_same_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            transcript_db = tmp / "transcripts.db"
            memory_db = tmp / "memory.db"
            import_transcript_to_sqlite(
                db_path=transcript_db,
                meeting_id="Bmr004",
                source_file="Bmr004.txt",
                transcript="\n".join(f"[S]: line {index}" for index in range(1, 101)),
            )
            logger = ResearchLogger(tmp / "logs", "Bmr004", run_id="run_Bmr004")
            graph = _build_graph(
                agents=_RepeatedContextFakeAgents(),
                logger=logger,
                db_path=memory_db,
                transcript_db_path=transcript_db,
            )

            state = graph.compile().invoke(
                {
                    "run_id": "run_Bmr004",
                    "meeting_id": "Bmr004",
                    "source_file": "Bmr004.txt",
                    "model_name": "gemini-2.5-pro",
                    "db_path": str(memory_db),
                    "transcript_db_path": str(transcript_db),
                    "checkpoint_db_path": str(tmp / "checkpoint.db"),
                    "research_log_dir": str(tmp / "logs"),
                    "log_level": "debug",
                    "keep_full_prompts": True,
                    "dry_run": True,
                    "chunk_size": 80,
                    "max_lookback_lines": 20,
                    "max_lookahead_lines": 40,
                    "max_context_rounds": 3,
                    "transcript_line_count": 100,
                    "transcript_overview": {"line_count": 100},
                    "current_memory": {
                        "memory_version": 0,
                        "meeting_history_ids": [],
                        "meeting_window": [],
                        "action_items": [],
                        "method_changes": [],
                        "experiment_todos": [],
                        "next_meeting_focus": [],
                    },
                    "memory_source": "default",
                    "processed_until_line": 0,
                    "planner_history": [],
                    "context_rounds": 0,
                    "raw_candidates": [],
                    "verified_candidates": [],
                    "rejected_candidates": [],
                    "final_patch": {},
                    "final_memory": {},
                    "report": {},
                    "persisted": False,
                    "read_line_numbers": [],
                }
            )

            self.assertEqual(len(state["unresolved_context"]), 1)
            self.assertEqual(
                state["unresolved_context"][0]["reason"],
                "segment_requested_more_context_but_planner_repeated_same_range",
            )
            events = [
                json.loads(line)
                for line in (logger.run_dir / "graph_events.jsonl").read_text().splitlines()
            ]
            repeated_window_reads = [
                event
                for event in events
                if event["node"] == "read_window"
                and event["event"] == "end"
                and event["line_range"] == "L1-L80"
            ]
            self.assertEqual(len(repeated_window_reads), 2)

    def test_memory_tools_read_sqlite_and_write_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "memory.db"
            save_memory_to_sqlite(
                db_path,
                {
                    "memory_version": 1,
                    "last_updated_utc": "2026-04-30T00:00:00Z",
                    "last_updated_meeting_id": "Bmr000",
                    "meeting_history_ids": ["Bmr000"],
                    "meeting_window": [],
                    "action_items": [
                        {
                            "item_id": "A001",
                            "title": "Existing task",
                            "detail": "",
                            "proposer": "unknown",
                            "owner": "unknown",
                            "status": "open",
                            "priority": "medium",
                            "dependencies": [],
                            "created_meeting_id": "Bmr000",
                            "last_updated_meeting_id": "Bmr000",
                            "history": [],
                        }
                    ],
                    "method_changes": [],
                    "experiment_todos": [],
                    "next_meeting_focus": [],
                },
            )
            context = AgentToolContext(
                db_path=db_path,
                run_id="run_Bmr004",
                meeting_id="Bmr004",
                policy=AgentToolPolicy(
                    agent_name="action_item_agent",
                    read_sections={"action_items"},
                    required_read_sections={"action_items"},
                    write_sections={"action_items"},
                ),
            )

            read_result = read_short_term_memory_tool(context, section="action_items")
            write_result = write_memory_candidate_tool(
                context,
                operation="update",
                target_section="action_items",
                target_id="A001",
                candidate_payload={"item_id": "A001", "title": "Existing task"},
                confidence=0.8,
            )
            staged = load_staged_candidates(
                db_path,
                run_id="run_Bmr004",
                agent_name="action_item_agent",
                target_section="action_items",
            )

            self.assertTrue(read_result["ok"])
            self.assertTrue(write_result["ok"])
            self.assertEqual(len(staged), 1)
            self.assertEqual(staged[0]["target_id"], "A001")

    def test_staging_statuses_update_after_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "memory.db"
            good = write_staged_candidate(
                db_path,
                run_id="run",
                meeting_id="Bmr001",
                agent_name="action_item_agent",
                target_section="action_items",
                operation="create",
                candidate_payload={
                    "title": "Prepare data",
                    "detail": "Prepare data.",
                    "proposer": "unknown",
                    "owner": "unknown",
                    "status": "open",
                    "priority": "medium",
                    "dependencies": [],
                },
                evidence_lines=[1],
                evidence_quote="Prepare data.",
                confidence=0.9,
            )
            bad = write_staged_candidate(
                db_path,
                run_id="run",
                meeting_id="Bmr001",
                agent_name="action_item_agent",
                target_section="action_items",
                operation="no_op",
                candidate_payload={},
                confidence=0.0,
            )

            update_staged_candidate_statuses(
                db_path,
                verified_candidate_ids={str(good["candidate_id"])},
                rejected_candidate_ids={str(bad["candidate_id"])},
            )
            rows = load_staged_candidates(db_path, run_id="run")
            statuses = {row["candidate_id"]: row["staging_status"] for row in rows}

            self.assertEqual(statuses[good["candidate_id"]], "verified")
            self.assertEqual(statuses[bad["candidate_id"]], "rejected")


class _FakePart:
    def __init__(self, text: str) -> None:
        self.text = text
        self.function_call = None


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.parts = [_FakePart(text)] if text else []


class _FakeCandidate:
    def __init__(self, text: str) -> None:
        self.content = _FakeContent(text)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.candidates = [_FakeCandidate(text)] if text else []
        self.function_calls = []
        self.text = text
        self.parsed = None
        self.usage_metadata = {}


class _FakeChat:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.messages_sent = 0

    def send_message(self, message: object) -> _FakeResponse:
        self.messages_sent += 1
        index = min(self.messages_sent - 1, len(self.responses) - 1)
        return self.responses[index]


class _FakeChats:
    def __init__(self, chat: _FakeChat) -> None:
        self.chat = chat

    def create(self, **kwargs: object) -> _FakeChat:
        return self.chat


class _FakeClient:
    def __init__(self, chat: _FakeChat) -> None:
        self.chats = _FakeChats(chat)


class _FakeAgent:
    def __init__(
        self,
        name: str,
        parsed: dict[str, object] | list[tuple[dict[str, object], list[str]]],
        errors: list[str] | None = None,
    ) -> None:
        self.name = name
        self.parsed = parsed
        self.errors = errors or []
        self.call_count = 0
        self.last_kwargs: dict[str, object] = {}

    def run(self, **kwargs: object) -> object:
        self.call_count += 1
        self.last_kwargs = kwargs
        parsed = self.parsed
        errors = self.errors
        if isinstance(parsed, list):
            index = min(self.call_count - 1, len(parsed) - 1)
            parsed, errors = parsed[index]
        return type(
            "Result",
            (),
            {
                "agent_name": self.name,
                "parsed": parsed,
                "raw_text": json.dumps(parsed),
                "errors": errors,
            },
        )()


class _FakeAgents:
    def __init__(self) -> None:
        self.context_planner = _FakeAgent(
            "context_planner",
            {
                "start_line": 1,
                "end_line": 1,
                "lookback_lines": 0,
                "lookahead_lines": 0,
                "reason": "test",
                "risk": "low",
            },
        )
        self.segment = _FakeAgent(
            "segment_agent",
            {
                "units": [
                    {
                        "unit_id": "U001",
                        "line_start": 1,
                        "line_end": 1,
                        "topic": "experiment data",
                        "kind_hint": ["next_meeting_focus"],
                        "needs_more_context": False,
                        "reason": "complete",
                    }
                ]
            },
        )
        self.meeting = _FakeAgent(
            "meeting_summary_agent",
            {
                "meeting_window": [
                    {
                        "meeting_id": "Bmr003",
                        "source_file": "Bmr003.txt",
                        "summary": "Prepared experiment data.",
                        "key_points": ["Prepare experiment data"],
                        "open_questions": [],
                        "evidence": "L1",
                        "confidence": 0.9,
                    }
                ]
            },
        )
        self.action = _FakeAgent("action_item_agent", {"action_items": []})
        self.method = _FakeAgent("method_change_agent", {"method_changes": []})
        self.experiment = _FakeAgent("experiment_todo_agent", {"experiment_todos": []})
        self.focus = _FakeAgent(
            "next_focus_agent",
            {
                "next_meeting_focus": [
                    {
                        "text": "準備實驗資料",
                        "evidence": "L1",
                        "confidence": 0.9,
                    }
                ]
            },
        )


class _RepeatedContextFakeAgents(_FakeAgents):
    def __init__(self) -> None:
        super().__init__()
        self.context_planner = _FakeAgent(
            "context_planner",
            {
                "start_line": 1,
                "end_line": 80,
                "lookback_lines": 0,
                "lookahead_lines": 0,
                "reason": "repeat same range",
                "risk": "medium",
            },
        )
        self.segment = _FakeAgent(
            "segment_agent",
            {
                "units": [
                    {
                        "unit_id": "U001",
                        "line_start": 1,
                        "line_end": 80,
                        "topic": "incomplete topic",
                        "kind_hint": ["next_meeting_focus"],
                        "needs_more_context": True,
                        "reason": "needs more context",
                    }
                ]
            },
        )
        self.meeting = _FakeAgent(
            "meeting_summary_agent",
            {
                "meeting_window": [
                    {
                        "meeting_id": "Bmr004",
                        "source_file": "Bmr004.txt",
                        "summary": "Repeated context meeting summary.",
                        "key_points": ["Repeated context"],
                        "open_questions": [],
                        "evidence": "L1",
                        "confidence": 0.9,
                    }
                ]
            },
        )
        self.focus = _FakeAgent("next_focus_agent", {"next_meeting_focus": []})


class _ExpandedContextFakeAgents(_FakeAgents):
    def __init__(self) -> None:
        super().__init__()
        self.context_planner = _FakeAgent(
            "context_planner",
            [
                (
                    {
                        "start_line": 1,
                        "end_line": 80,
                        "lookback_lines": 0,
                        "lookahead_lines": 0,
                        "reason": "first chunk",
                        "risk": "medium",
                    },
                    [],
                ),
                (
                    {
                        "start_line": 81,
                        "end_line": 120,
                        "lookback_lines": 0,
                        "lookahead_lines": 0,
                        "reason": "complete context",
                        "risk": "medium",
                    },
                    [],
                ),
            ],
        )
        self.segment = _FakeAgent(
            "segment_agent",
            [
                (
                    {
                        "units": [
                            {
                                "unit_id": "U001",
                                "line_start": 1,
                                "line_end": 80,
                                "topic": "first half",
                                "kind_hint": ["meeting_summary"],
                                "needs_more_context": True,
                                "reason": "needs second half",
                            }
                        ]
                    },
                    [],
                ),
                (
                    {
                        "units": [
                            {
                                "unit_id": "U002",
                                "line_start": 81,
                                "line_end": 120,
                                "topic": "second half",
                                "kind_hint": ["meeting_summary"],
                                "needs_more_context": False,
                                "reason": "complete",
                            }
                        ]
                    },
                    [],
                ),
            ],
        )
        self.meeting = _FakeAgent(
            "meeting_summary_agent",
            {
                "meeting_window": [
                    {
                        "meeting_id": "Bmr007",
                        "source_file": "Bmr007.txt",
                        "summary": "Expanded context meeting summary.",
                        "key_points": ["Expanded context"],
                        "open_questions": [],
                        "evidence": "L1, L120",
                        "confidence": 0.9,
                    }
                ]
            },
        )
        self.focus = _FakeAgent("next_focus_agent", {"next_meeting_focus": []})


class _NoMeetingSummaryFakeAgents(_FakeAgents):
    def __init__(self) -> None:
        super().__init__()
        self.meeting = _FakeAgent("meeting_summary_agent", {"meeting_window": []})


if __name__ == "__main__":
    unittest.main()
