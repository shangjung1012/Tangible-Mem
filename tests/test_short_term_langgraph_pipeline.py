from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

for module_name in (
    "short_term.agents",
    "short_term.graph_state",
    "short_term.reducer",
    "short_term.research_logger",
    "short_term.verifier",
):
    sys.modules.pop(module_name, None)

from short_term.reducer import reduce_candidates  # noqa: E402
from short_term.research_logger import ResearchLogger  # noqa: E402
from short_term.langgraph_update import _build_graph  # noqa: E402
from short_term.genai_retry import call_with_retry  # noqa: E402
from short_term.transcript_store import import_transcript_to_sqlite  # noqa: E402
from short_term.verifier import verify_candidates  # noqa: E402


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
        self.assertNotIn("evidence", patch["action_items"][0])
        self.assertEqual(patch["next_meeting_focus"], ["追蹤實驗資料格式"])

    def test_graph_event_jsonl_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ResearchLogger(Path(tmpdir), "Bmr002", run_id="run_Bmr002")
            logger.graph_event(node="n", event="start", summary={"x": 1})
            path = Path(tmpdir) / "run_Bmr002" / "graph_events.jsonl"
            payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(payload["run_id"], "run_Bmr002")
            self.assertEqual(payload["node"], "n")

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


class _FakeAgent:
    def __init__(self, name: str, parsed: dict[str, object]) -> None:
        self.name = name
        self.parsed = parsed

    def run(self, **kwargs: object) -> object:
        return type(
            "Result",
            (),
            {
                "agent_name": self.name,
                "parsed": self.parsed,
                "raw_text": json.dumps(self.parsed),
                "errors": [],
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
        self.meeting = _FakeAgent("meeting_summary_agent", {"meeting_window": []})
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


if __name__ == "__main__":
    unittest.main()
