from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from share_mem.store import (  # noqa: E402
    build_l1_index,
    clean_generated_outputs,
    get_l1_object,
    load_recent_meetings,
    refresh_share_mem_outputs,
)
from share_mem.build_tree import (  # noqa: E402
    _run_bridge_for_transcript,
    discover_transcripts,
    infer_grace_meeting_date,
)


def _obj(
    obj_id: str,
    obj_type: str,
    content: str,
    *,
    evidence: str = "evidence",
    topics: list[str] | None = None,
) -> dict:
    return {
        "obj_id": obj_id,
        "type": obj_type,
        "content": content,
        "importance": 0.7,
        "evidence": evidence,
        "related_topics": topics or ["memory"],
        "related_obj_ids": [],
    }


def _tree() -> dict:
    return {
        "tree_version": 3,
        "last_updated_utc": "2026-05-07T00:00:00Z",
        "project_profile": {},
        "phases": [],
        "meetings": [
            {
                "meeting_id": "0307",
                "timestamp": "2026-03-07T00:00:00Z",
                "meeting_date": "2026-03-07",
                "source_file": "meeting_recording/transcript/grace/0307.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj("L1-0307-001", "decision", "Use shared L1 memory."),
                ],
            },
            {
                "meeting_id": "0408",
                "timestamp": "2026-04-08T00:00:00Z",
                "meeting_date": "2026-04-08",
                "source_file": "meeting_recording/transcript/grace/0408.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj("L1-0408-001", "method_change", "Use multi-agent L1."),
                    _obj("L1-0408-002", "todo", "Build share_mem."),
                ],
            },
            {
                "meeting_id": "0422",
                "timestamp": "2026-04-22T00:00:00Z",
                "meeting_date": "2026-04-22",
                "source_file": "meeting_recording/transcript/grace/0422.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj("L1-0422-001", "result", "Recall starts from L1."),
                ],
            },
            {
                "meeting_id": "0429",
                "timestamp": "2026-04-29T00:00:00Z",
                "meeting_date": "2026-04-29",
                "source_file": "meeting_recording/transcript/grace/0429.txt",
                "phase_id": "",
                "memory_objects": [
                    _obj("L1-0429-001", "open_question", "How should topic-tree use L1?"),
                ],
            },
        ],
    }


class ShareMemTests(unittest.TestCase):
    def test_discover_transcripts_returns_grace_txt_files_in_name_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript_dir = Path(tmp)
            (transcript_dir / "0429.txt").write_text("late", encoding="utf-8")
            (transcript_dir / "0307.txt").write_text("early", encoding="utf-8")
            (transcript_dir / "notes.md").write_text("ignore", encoding="utf-8")

            transcripts = discover_transcripts(transcript_dir)

            self.assertEqual([path.name for path in transcripts], ["0307.txt", "0429.txt"])

    def test_infer_grace_meeting_date_uses_2026_mmdd_filenames(self) -> None:
        self.assertEqual(infer_grace_meeting_date("0307"), "2026-03-07")
        self.assertEqual(infer_grace_meeting_date("0429"), "2026-04-29")

    def test_app_long_term_context_defaults_to_share_mem_tree(self) -> None:
        from app import memory_context

        self.assertEqual(
            memory_context.LONG_TERM_TREE_PATH,
            REPO_ROOT / "share_mem" / "tree.json",
        )

    def test_build_invokes_share_mem_l1_bridge_without_long_term_import_path(self) -> None:
        transcript_path = REPO_ROOT / "meeting_recording" / "transcript" / "grace" / "0307.txt"
        long_term_path = str(REPO_ROOT / "long_term")
        original_sys_path = sys.path[:]
        path_during_call: list[str] = []
        sys.path = [entry for entry in sys.path if entry != long_term_path]
        try:
            with patch("share_mem.l1.bridge.main") as bridge_main:
                _run_bridge_for_transcript(
                    transcript_path=transcript_path,
                    tree_path=Path("share_mem/tree.json"),
                    snapshot_dir=Path("share_mem/snapshots"),
                    research_log_dir=Path("share_mem/research_logs"),
                    dataset_profile="grace",
                    model="gemini-2.5-pro",
                )
                path_during_call = sys.path[:]
        finally:
            sys.path = original_sys_path

        self.assertNotIn(long_term_path, path_during_call)
        self.assertEqual(bridge_main.call_count, 1)
        bridge_args = bridge_main.call_args.args[0]
        self.assertIn("--mode", bridge_args)
        self.assertIn("multi-agent", bridge_args)
        self.assertIn("--meeting-date", bridge_args)
        self.assertIn("2026-03-07", bridge_args)

    def test_refresh_outputs_writes_tree_meeting_files_index_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            source_dir = REPO_ROOT / "meeting_recording" / "transcript" / "grace"

            manifest = refresh_share_mem_outputs(
                root=root,
                tree=_tree(),
                source_transcript_dir=source_dir,
            )

            tree_path = root / "tree.json"
            index_path = root / "l1_index.json"
            manifest_path = root / "manifest.json"
            meeting_path = root / "meetings" / "0408.json"

            self.assertTrue(tree_path.exists())
            self.assertTrue(index_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertTrue(meeting_path.exists())

            saved_tree = json.loads(tree_path.read_text(encoding="utf-8"))
            saved_meeting = json.loads(meeting_path.read_text(encoding="utf-8"))
            saved_index = json.loads(index_path.read_text(encoding="utf-8"))
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(saved_tree["meetings"][1]["meeting_id"], "0408")
            self.assertEqual(saved_meeting["meeting_id"], "0408")
            self.assertEqual(saved_index["L1-0408-002"]["meeting_id"], "0408")
            self.assertEqual(saved_index["L1-0408-002"]["type"], "todo")
            self.assertEqual(saved_index["L1-0408-002"]["topics"], ["memory"])
            self.assertEqual(saved_manifest["object_count"], 5)
            self.assertEqual(saved_manifest["meeting_ids"], ["0307", "0408", "0422", "0429"])
            self.assertFalse(saved_manifest["topic_view"]["exists"])
            self.assertEqual(saved_manifest["topic_view"]["topic_count"], 0)
            self.assertEqual(saved_manifest["topic_view"]["topic_event_count"], 0)
            self.assertEqual(manifest["object_count"], saved_manifest["object_count"])

    def test_clean_generated_outputs_removes_topic_view_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share_mem"
            (root / "topic_updates").mkdir(parents=True)
            (root / "topic_updates" / "0307.json").write_text("{}", encoding="utf-8")
            (root / "topic_tree.json").write_text("{}", encoding="utf-8")
            (root / "topic_index.json").write_text("{}", encoding="utf-8")

            clean_generated_outputs(root)

            self.assertFalse((root / "topic_updates").exists())
            self.assertFalse((root / "topic_tree.json").exists())
            self.assertFalse((root / "topic_index.json").exists())

    def test_build_l1_index_matches_every_meeting_object(self) -> None:
        index = build_l1_index(_tree())

        self.assertEqual(set(index), {
            "L1-0307-001",
            "L1-0408-001",
            "L1-0408-002",
            "L1-0422-001",
            "L1-0429-001",
        })
        self.assertEqual(index["L1-0422-001"]["meeting_date"], "2026-04-22")
        self.assertEqual(index["L1-0422-001"]["content"], "Recall starts from L1.")

    def test_get_l1_object_returns_object_and_parent_meeting(self) -> None:
        found = get_l1_object("L1-0408-001", tree=_tree())

        self.assertIsNotNone(found)
        assert found is not None
        meeting, obj = found
        self.assertEqual(meeting["meeting_id"], "0408")
        self.assertEqual(obj["content"], "Use multi-agent L1.")

    def test_load_recent_meetings_returns_latest_three_by_meeting_date(self) -> None:
        recent = load_recent_meetings(limit=3, tree=_tree())

        self.assertEqual([meeting["meeting_id"] for meeting in recent], ["0408", "0422", "0429"])


if __name__ == "__main__":
    unittest.main()
