from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHORT_TERM_DIR = REPO_ROOT / "short_term"
sys.path.insert(0, str(SHORT_TERM_DIR))
for module_name in ("schema", "normalizer", "llm_client"):
    sys.modules.pop(module_name, None)

from llm_client import (  # noqa: E402
    _patch_adds_unknown_action_item,
    _record_memory_read,
    _section_fully_read,
    _slice_memory_section,
    build_tool_call_prompt,
)


def _memory_with_action_items(count: int) -> dict[str, object]:
    return {
        "memory_version": 1,
        "meeting_history_ids": ["Bmr001"],
        "meeting_window": [],
        "action_items": [
            {
                "item_id": f"A{index:03d}",
                "title": f"Task {index}",
                "detail": f"Detail for task {index}",
                "status": "open",
                "priority": "medium",
                "owner": "unknown",
                "created_meeting_id": "Bmr001",
                "last_updated_meeting_id": "Bmr001",
                "history": [],
            }
            for index in range(1, count + 1)
        ],
        "method_changes": [],
        "experiment_todos": [],
        "next_meeting_focus": [],
    }


class ShortTermLlmClientTests(unittest.TestCase):
    def test_overview_includes_compact_action_item_index(self) -> None:
        overview = _slice_memory_section(
            memory=_memory_with_action_items(2),
            section="overview",
            offset=0,
            limit=10,
        )

        self.assertEqual(overview["summary"]["action_items_count"], 2)
        self.assertFalse(overview["action_item_index_truncated"])
        self.assertEqual(
            [row["item_id"] for row in overview["action_item_index"]],
            ["A001", "A002"],
        )
        self.assertEqual(overview["action_item_index"][0]["title"], "Task 1")

    def test_read_tracking_requires_all_pages_for_full_coverage(self) -> None:
        state = {
            "read_sections": set(),
            "read_ranges": {},
            "read_totals": {},
            "fully_read_sections": set(),
        }
        memory = _memory_with_action_items(12)

        first_page = _slice_memory_section(memory, "action_items", offset=0, limit=10)
        _record_memory_read(state, "action_items", first_page)
        self.assertFalse(_section_fully_read(state, "action_items"))

        second_page = _slice_memory_section(memory, "action_items", offset=10, limit=10)
        _record_memory_read(state, "action_items", second_page)
        self.assertTrue(_section_fully_read(state, "action_items"))

    def test_unknown_action_patch_detection(self) -> None:
        memory = _memory_with_action_items(2)

        self.assertFalse(
            _patch_adds_unknown_action_item(
                {"action_items": [{"item_id": "A001", "status": "completed"}]},
                memory,
            )
        )
        self.assertTrue(
            _patch_adds_unknown_action_item(
                {"action_items": [{"title": "New task"}]},
                memory,
            )
        )
        self.assertTrue(
            _patch_adds_unknown_action_item(
                {"action_items": [{"item_id": "A999", "title": "New task"}]},
                memory,
            )
        )

    def test_tool_prompt_describes_transcript_fields(self) -> None:
        prompt = build_tool_call_prompt(
            meeting_id="Bmr001",
            source_file="meeting_recording/transcript/ISCI/Bmr001.txt",
            transcript_line_count=917,
        )

        self.assertIn("read_transcript_lines", prompt)
        self.assertIn("speaker", prompt)
        self.assertIn("text", prompt)
        self.assertIn("raw_line", prompt)
        self.assertIn("next_start_line", prompt)

    def test_max_tool_rounds_constant_defaults_to_unlimited(self) -> None:
        from llm_client import MAX_TOOL_ROUNDS  # noqa: PLC0415

        self.assertIsNone(MAX_TOOL_ROUNDS)


if __name__ == "__main__":
    unittest.main()
