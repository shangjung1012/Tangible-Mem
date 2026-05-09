from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from short_term.retrieval.short_term_context import retrieve_short_term_context


class ShortTermRetrievalTests(unittest.TestCase):
    def test_retrieves_relevant_active_unit_from_json_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_path = Path(tmp) / "short_term_memory.json"
            memory_path.write_text(
                json.dumps(
                    {
                        "memory_version": 7,
                        "last_updated_meeting_id": "0506",
                        "units": [
                            {
                                "unit_id": "S001",
                                "title": "Memory Retrieval Status",
                                "summary": "Recent work focuses on short-term retrieval and active memory units.",
                                "types": ["decision"],
                                "related_topics": ["memory retrieval", "short-term memory"],
                                "source_obj_ids": ["L1-0506-001", "L1-0506-002"],
                                "last_updated_meeting_id": "0506",
                                "missed_meeting_count": 0,
                            },
                            {
                                "unit_id": "S999",
                                "title": "Poster Logistics",
                                "summary": "Poster printing and reimbursement planning.",
                                "types": ["action_item"],
                                "related_topics": ["poster"],
                                "source_obj_ids": ["L1-0506-099"],
                                "last_updated_meeting_id": "0506",
                                "missed_meeting_count": 1,
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            context = retrieve_short_term_context(
                query="目前 memory retrieval 的最新狀態是什麼？",
                api_key="test-key",
                memory_path=memory_path,
            )

        self.assertIn("=== Short-Term Memory Retrieval ===", context)
        self.assertIn("[S001] Memory Retrieval Status", context)
        self.assertIn("last_updated_meeting_id: 0506", context)
        self.assertIn("source L1: L1-0506-001, L1-0506-002", context)
        self.assertNotIn("Poster Logistics", context)

    def test_missing_or_empty_memory_returns_clear_message(self) -> None:
        context = retrieve_short_term_context(
            query="目前進度？",
            api_key="test-key",
            memory_path=Path("/tmp/does-not-exist-short-term-memory.json"),
        )

        self.assertEqual(context, "（無短期記憶）")


if __name__ == "__main__":
    unittest.main()
