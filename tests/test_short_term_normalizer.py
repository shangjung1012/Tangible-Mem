from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHORT_TERM_DIR = REPO_ROOT / "short_term"
sys.path.insert(0, str(SHORT_TERM_DIR))
for module_name in ("core.schema", "storage.io_utils", "core.normalizer"):
    sys.modules.pop(module_name, None)

from core.normalizer import normalize_memory  # noqa: E402


class ShortTermNormalizerTests(unittest.TestCase):
    def test_partial_action_update_preserves_existing_fields(self) -> None:
        previous = {
            "memory_version": 7,
            "meeting_history_ids": ["Bmr001", "Bmr002", "Bmr003"],
            "meeting_window": [
                {
                    "meeting_id": "Bmr003",
                    "source_file": "old.txt",
                    "summary": "old summary",
                    "key_points": ["old point"],
                    "open_questions": ["old question"],
                }
            ],
            "action_items": [
                {
                    "item_id": "A010",
                    "title": "Old title",
                    "detail": "Old detail",
                    "proposer": "Alice",
                    "owner": "Bob",
                    "created_meeting_id": "Bmr001",
                    "created_time_hint": "early",
                    "dependencies": ["A001"],
                    "status": "open",
                    "priority": "high",
                    "evidence": "old evidence",
                    "last_updated_meeting_id": "Bmr001",
                    "history": [
                        {
                            "version": 0,
                            "meeting_id": "Bmr001",
                            "change": "created",
                        }
                    ],
                }
            ],
        }

        updated = normalize_memory(
            updated_memory={
                "action_items": [
                    {
                        "item_id": "A010",
                        "status": "completed",
                        "evidence": "done in this meeting",
                    }
                ]
            },
            previous_memory=previous,
            meeting_id="Bmr004",
            source_file="Bmr004.txt",
        )

        item = updated["action_items"][0]
        self.assertEqual(item["item_id"], "A010")
        self.assertEqual(item["title"], "Old title")
        self.assertEqual(item["detail"], "Old detail")
        self.assertEqual(item["owner"], "Bob")
        self.assertEqual(item["status"], "completed")
        self.assertEqual(item["evidence"], "done in this meeting")
        self.assertEqual(item["last_updated_meeting_id"], "Bmr004")
        self.assertEqual(item["history"][-1]["version"], 1)
        self.assertEqual(item["history"][-1]["meeting_id"], "Bmr004")

    def test_new_action_without_id_uses_next_existing_id(self) -> None:
        previous = {
            "memory_version": 1,
            "meeting_history_ids": ["Bmr010"],
            "action_items": [
                {
                    "item_id": "A001",
                    "title": "Keep me",
                    "detail": "Existing detail",
                    "proposer": "unknown",
                    "owner": "unknown",
                    "created_meeting_id": "Bmr010",
                    "created_time_hint": "",
                    "dependencies": [],
                    "status": "open",
                    "priority": "medium",
                    "evidence": "",
                    "last_updated_meeting_id": "Bmr010",
                    "history": [],
                },
                {
                    "item_id": "A009",
                    "title": "Highest old id",
                    "detail": "Existing detail",
                    "proposer": "unknown",
                    "owner": "unknown",
                    "created_meeting_id": "Bmr010",
                    "created_time_hint": "",
                    "dependencies": [],
                    "status": "open",
                    "priority": "medium",
                    "evidence": "",
                    "last_updated_meeting_id": "Bmr010",
                    "history": [],
                },
            ],
        }

        updated = normalize_memory(
            updated_memory={
                "action_items": [
                    {
                        "title": "New item",
                        "detail": "New detail",
                    }
                ]
            },
            previous_memory=previous,
            meeting_id="Bmr011",
            source_file="Bmr011.txt",
        )

        items_by_id = {item["item_id"]: item for item in updated["action_items"]}
        self.assertEqual(items_by_id["A001"]["title"], "Keep me")
        self.assertEqual(items_by_id["A010"]["title"], "New item")
        self.assertNotEqual(items_by_id["A001"]["detail"], "New detail")

    def test_partial_meeting_window_update_preserves_lists(self) -> None:
        previous = {
            "memory_version": 3,
            "meeting_history_ids": ["Bmr020"],
            "meeting_window": [
                {
                    "meeting_id": "Bmr020",
                    "source_file": "old.txt",
                    "summary": "old summary",
                    "key_points": ["keep point"],
                    "open_questions": ["keep question"],
                }
            ],
        }

        updated = normalize_memory(
            updated_memory={
                "meeting_window": [
                    {
                        "meeting_id": "Bmr020",
                        "summary": "new summary",
                    }
                ]
            },
            previous_memory=previous,
            meeting_id="Bmr020",
            source_file="new.txt",
        )

        meeting = updated["meeting_window"][0]
        self.assertEqual(meeting["summary"], "new summary")
        self.assertEqual(meeting["key_points"], ["keep point"])
        self.assertEqual(meeting["open_questions"], ["keep question"])

    def test_action_history_collapses_repeated_updates_in_same_meeting(self) -> None:
        previous = {
            "memory_version": 1,
            "meeting_history_ids": ["Bmr001"],
            "action_items": [
                {
                    "item_id": "A003",
                    "title": "Plan data workflow",
                    "detail": "Initial detail",
                    "proposer": "me011",
                    "owner": "me011",
                    "created_meeting_id": "Bmr001",
                    "created_time_hint": "",
                    "dependencies": [],
                    "status": "open",
                    "priority": "medium",
                    "evidence": "L384",
                    "last_updated_meeting_id": "Bmr001",
                    "history": [
                        {
                            "version": 0,
                            "meeting_id": "Bmr001",
                            "change": "imported or created",
                        },
                        {
                            "version": 1,
                            "meeting_id": "Bmr001",
                            "change": "updated fields: detail",
                        },
                    ],
                }
            ],
        }

        updated = normalize_memory(
            updated_memory={
                "action_items": [
                    {
                        "item_id": "A003",
                        "detail": "Expanded detail",
                        "priority": "high",
                    }
                ]
            },
            previous_memory=previous,
            meeting_id="Bmr001",
            source_file="Bmr001.txt",
        )

        history = updated["action_items"][0]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["version"], 0)
        self.assertEqual(history[0]["meeting_id"], "Bmr001")
        self.assertEqual(
            history[0]["change"],
            "imported or created; updated fields: detail, priority",
        )

    def test_experiment_todo_update_accepts_item_id_alias(self) -> None:
        previous = {
            "memory_version": 1,
            "meeting_history_ids": ["Bmr002"],
            "experiment_todos": [
                {
                    "todo_id": "E008",
                    "description": "Original stress-tag experiment",
                    "status": "open",
                    "owner": "fe008",
                    "related_action_item_ids": ["A007"],
                    "meeting_id": "Bmr002",
                    "evidence": "L1666-1676",
                }
            ],
        }

        updated = normalize_memory(
            updated_memory={
                "experiment_todos": [
                    {
                        "item_id": "E008",
                        "description": "Refined stress-tag pilot",
                        "evidence": "L1666-1676, L1744-1773",
                    }
                ]
            },
            previous_memory=previous,
            meeting_id="Bmr002",
            source_file="Bmr002.txt",
        )

        todos = updated["experiment_todos"]
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]["todo_id"], "E008")
        self.assertEqual(todos[0]["description"], "Refined stress-tag pilot")
        self.assertEqual(todos[0]["owner"], "fe008")


if __name__ == "__main__":
    unittest.main()
