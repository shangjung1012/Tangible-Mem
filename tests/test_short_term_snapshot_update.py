from __future__ import annotations

import json
import os
import signal
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from short_term.merge import GeminiMergeDecider, apply_merge_decision, run_with_timeout
from short_term.snapshot_loader import load_snapshot_tree, select_latest_meeting
from short_term.update_memory import update_memory_from_snapshot


def _obj(
    obj_id: str,
    content: str,
    *,
    obj_type: str = "decision",
    topics: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "obj_id": obj_id,
        "type": obj_type,
        "content": content,
        "importance": 0.7,
        "evidence": f"Evidence for {obj_id}",
        "related_topics": topics if topics is not None else ["memory architecture"],
        "related_obj_ids": [],
    }


def _meeting(
    meeting_id: str,
    *,
    meeting_date: str = "",
    objects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "meeting_id": meeting_id,
        "meeting_date": meeting_date,
        "timestamp": f"2026-05-08T00:00:00Z-{meeting_id}",
        "source_file": f"{meeting_id}.txt",
        "phase_id": "",
        "memory_objects": objects or [],
    }


def _write_snapshot(path: Path, meetings: list[dict[str, Any]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "tree_version": len(meetings),
                "last_updated_utc": "2026-05-08T00:00:00Z",
                "project_profile": {},
                "phases": [],
                "meetings": meetings,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _topic_decider(
    source_obj: dict[str, Any],
    candidates: list[dict[str, Any]],
    _meeting: dict[str, Any],
) -> dict[str, Any]:
    if source_obj["related_topics"] and candidates:
        return {
            "action": "merge_existing",
            "unit_id": candidates[0]["unit_id"],
            "title": candidates[0]["title"],
            "summary": f"{candidates[0]['summary']} / {source_obj['content']}",
            "related_topics": sorted(
                set(candidates[0].get("related_topics", []))
                | set(source_obj.get("related_topics", []))
            ),
        }
    return {
        "action": "create_new",
        "title": source_obj["content"][:40],
        "summary": source_obj["content"],
        "related_topics": source_obj.get("related_topics", []),
    }


class ShortTermSnapshotLoaderTests(unittest.TestCase):
    def test_missing_snapshot_reports_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing_bridge_0318.json"

            with self.assertRaisesRegex(RuntimeError, "snapshot file not found"):
                load_snapshot_tree(missing)

    def test_select_latest_meeting_uses_date_then_meeting_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = _write_snapshot(
                Path(tmpdir) / "snapshot.json",
                [
                    _meeting("m-no-date", objects=[_obj("L1-x-001", "No date")]),
                    _meeting("0318", meeting_date="2026-03-18"),
                    _meeting("0307", meeting_date="2026-03-07"),
                ],
            )

            tree = load_snapshot_tree(snapshot)
            latest = select_latest_meeting(tree)

            self.assertEqual(latest["meeting_id"], "0318")

    def test_select_latest_meeting_falls_back_to_meeting_id(self) -> None:
        tree = {
            "meetings": [
                _meeting("0307"),
                _meeting("0318"),
            ]
        }

        latest = select_latest_meeting(tree)

        self.assertEqual(latest["meeting_id"], "0318")


class ShortTermSnapshotUpdateTests(unittest.TestCase):
    def test_update_merges_related_units_and_drops_after_two_missed_meetings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            memory_path = base / "short_term_memory.json"
            snapshot_dir = base / "snapshots"

            s1 = _write_snapshot(
                base / "s1.json",
                [
                    _meeting(
                        "0307",
                        meeting_date="2026-03-07",
                        objects=[
                            _obj(
                                "L1-0307-001",
                                "Shared memory design starts.",
                                topics=["shared memory"],
                            )
                        ],
                    )
                ],
            )
            s2 = _write_snapshot(
                base / "s2.json",
                [
                    _meeting("0307", meeting_date="2026-03-07"),
                    _meeting(
                        "0318",
                        meeting_date="2026-03-18",
                        objects=[
                            _obj(
                                "L1-0318-001",
                                "Shared memory design is updated.",
                                topics=["shared memory"],
                            )
                        ],
                    ),
                ],
            )
            s3 = _write_snapshot(
                base / "s3.json",
                [
                    _meeting("0307", meeting_date="2026-03-07"),
                    _meeting("0318", meeting_date="2026-03-18"),
                    _meeting(
                        "0325",
                        meeting_date="2026-03-25",
                        objects=[_obj("L1-0325-001", "Poster task.", topics=[])],
                    ),
                ],
            )
            s4 = _write_snapshot(
                base / "s4.json",
                [
                    _meeting("0307", meeting_date="2026-03-07"),
                    _meeting("0318", meeting_date="2026-03-18"),
                    _meeting("0325", meeting_date="2026-03-25"),
                    _meeting(
                        "0408",
                        meeting_date="2026-04-08",
                        objects=[_obj("L1-0408-001", "Schedule task.", topics=[])],
                    ),
                ],
            )

            after_0307 = update_memory_from_snapshot(
                snapshot_path=s1,
                memory_json_path=memory_path,
                snapshot_dir=snapshot_dir,
                merge_decider=_topic_decider,
            )
            after_0318 = update_memory_from_snapshot(
                snapshot_path=s2,
                memory_json_path=memory_path,
                snapshot_dir=snapshot_dir,
                merge_decider=_topic_decider,
            )
            after_0325 = update_memory_from_snapshot(
                snapshot_path=s3,
                memory_json_path=memory_path,
                snapshot_dir=snapshot_dir,
                merge_decider=_topic_decider,
            )
            after_0408 = update_memory_from_snapshot(
                snapshot_path=s4,
                memory_json_path=memory_path,
                snapshot_dir=snapshot_dir,
                merge_decider=_topic_decider,
            )

            self.assertEqual(len(after_0307["units"]), 1)
            self.assertEqual(len(after_0318["units"]), 1)
            self.assertEqual(
                after_0318["units"][0]["source_obj_ids"],
                ["L1-0307-001", "L1-0318-001"],
            )
            self.assertEqual(after_0318["units"][0]["missed_meeting_count"], 0)
            self.assertEqual(len(after_0325["units"]), 2)
            self.assertEqual(
                {
                    unit["unit_id"]: unit["missed_meeting_count"]
                    for unit in after_0325["units"]
                },
                {"S001": 1, "S002": 0},
            )
            self.assertEqual([unit["unit_id"] for unit in after_0408["units"]], ["S002", "S003"])
            self.assertTrue(memory_path.exists())
            self.assertTrue((snapshot_dir / "0408.json").exists())

    def test_dry_run_does_not_write_memory_or_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            snapshot = _write_snapshot(
                base / "s1.json",
                [
                    _meeting(
                        "0307",
                        meeting_date="2026-03-07",
                        objects=[_obj("L1-0307-001", "Dry run unit.")],
                    )
                ],
            )

            memory = update_memory_from_snapshot(
                snapshot_path=snapshot,
                memory_json_path=base / "short_term_memory.json",
                snapshot_dir=base / "snapshots",
                merge_decider=_topic_decider,
                dry_run=True,
            )

            self.assertEqual(memory["last_updated_meeting_id"], "0307")
            self.assertFalse((base / "short_term_memory.json").exists())
            self.assertFalse((base / "snapshots").exists())


class ShortTermMergeSafetyTests(unittest.TestCase):
    def test_gemini_decider_sets_http_timeout_from_merge_timeout(self) -> None:
        with (
            patch.dict(os.environ, {"SHORT_TERM_MERGE_TIMEOUT_S": "13"}, clear=True),
            patch("short_term.merge.load_api_keys", return_value=["test-key"]),
            patch("short_term.merge.create_gemini_client", return_value=object()),
        ):
            GeminiMergeDecider()

            self.assertEqual(os.environ.get("GEMINI_HTTP_TIMEOUT_S"), "13")

    def test_gemini_decider_retries_transient_worker_errors(self) -> None:
        with (
            patch.dict(os.environ, {"SHORT_TERM_MERGE_RETRIES": "1"}, clear=True),
            patch("short_term.merge.load_api_keys", return_value=["test-key"]),
            patch("short_term.merge.create_gemini_client", return_value=object()),
            patch(
                "short_term.merge.run_with_timeout",
                side_effect=[
                    RuntimeError("short-term Gemini merge decision failed in worker (ClientError): 499 CANCELLED"),
                    {
                        "action": "create_new",
                        "title": "Recovered",
                        "summary": "Recovered after retry.",
                        "related_topics": [],
                    },
                ],
            ) as run_merge,
        ):
            decider = GeminiMergeDecider(timeout_s=1)
            decision = decider(_obj("L1-0307-001", "Retry object."), [], _meeting("0307"))

            self.assertEqual(decision["title"], "Recovered")
            self.assertEqual(run_merge.call_count, 2)

    def test_run_with_timeout_raises_timeout_error(self) -> None:
        with self.assertRaisesRegex(TimeoutError, "timed out"):
            run_with_timeout(lambda: time.sleep(1), timeout_s=0.01, operation_name="slow merge")

    def test_run_with_timeout_stops_function_that_ignores_alarm(self) -> None:
        if hasattr(signal, "SIGALRM"):
            def ignore_alarm_then_sleep() -> dict[str, Any]:
                signal.signal(signal.SIGALRM, signal.SIG_IGN)
                time.sleep(0.3)
                return {}
        else:
            def ignore_alarm_then_sleep() -> dict[str, Any]:
                time.sleep(0.3)
                return {}

        started_at = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "timed out"):
            run_with_timeout(
                ignore_alarm_then_sleep,
                timeout_s=0.05,
                operation_name="signal ignoring merge",
            )

        self.assertLess(time.monotonic() - started_at, 0.25)

    def test_unknown_merge_unit_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown unit_id"):
            apply_merge_decision(
                memory={
                    "meeting_history_ids": ["0307"],
                    "units": [],
                },
                source_obj=_obj("L1-0307-001", "Cannot merge."),
                meeting=_meeting("0307"),
                decision={
                    "action": "merge_existing",
                    "unit_id": "S999",
                    "title": "Invalid",
                    "summary": "Invalid",
                    "related_topics": [],
                },
            )

    def test_create_new_assigns_next_id_and_dedupes_source_ids(self) -> None:
        memory = {
            "meeting_history_ids": ["0307"],
            "units": [
                {
                    "unit_id": "S009",
                    "title": "Existing",
                    "summary": "Existing",
                    "types": ["decision"],
                    "related_topics": [],
                    "source_obj_ids": ["L1-old-001"],
                    "created_meeting_id": "0307",
                    "last_updated_meeting_id": "0307",
                    "last_seen_meeting_index": 0,
                    "missed_meeting_count": 0,
                    "update_history": [],
                }
            ],
        }

        created = apply_merge_decision(
            memory=memory,
            source_obj=_obj("L1-0307-001", "New unit."),
            meeting=_meeting("0307"),
            decision={
                "action": "create_new",
                "title": "New",
                "summary": "New unit.",
                "related_topics": ["memory"],
            },
        )

        self.assertEqual(created["unit_id"], "S010")
        self.assertEqual(created["source_obj_ids"], ["L1-0307-001"])
        self.assertEqual(created["update_history"][0]["source_obj_ids"], ["L1-0307-001"])


if __name__ == "__main__":
    unittest.main()
