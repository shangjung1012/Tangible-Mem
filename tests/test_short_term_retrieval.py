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
                l1_index_path=Path(tmp) / "missing_l1_index.json",
            )

        self.assertIn("=== Short-Term Memory Retrieval ===", context)
        self.assertIn("[S001] Memory Retrieval Status", context)
        self.assertIn("last_updated_meeting_id: 0506", context)
        self.assertIn("source L1: L1-0506-001, L1-0506-002", context)
        self.assertNotIn("Poster Logistics", context)

    def test_source_l1_preview_is_ranked_by_query_relevance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_path = root / "short_term_memory.json"
            l1_index_path = root / "l1_index.json"
            memory_path.write_text(
                json.dumps(
                    {
                        "memory_version": 7,
                        "last_updated_meeting_id": "0506",
                        "units": [
                            {
                                "unit_id": "S001",
                                "title": "Transcript Segmentation Pipeline",
                                "summary": "Tracks transcript segmentation and idea-unit extraction status.",
                                "types": ["approach_change"],
                                "related_topics": ["transcript segmentation", "idea units"],
                                "source_obj_ids": [
                                    "L1-0307-001",
                                    "L1-0307-002",
                                    "L1-0307-003",
                                    "L1-0307-004",
                                    "L1-0506-001",
                                    "L1-0506-002",
                                ],
                                "last_updated_meeting_id": "0506",
                                "missed_meeting_count": 0,
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            l1_index_path.write_text(
                json.dumps(
                    {
                        "L1-0307-001": {"content": "Poster budget and meeting logistics."},
                        "L1-0307-002": {"content": "Speaker identity assumption."},
                        "L1-0307-003": {"content": "Dataset sourcing note."},
                        "L1-0307-004": {"content": "Administrative reminder."},
                        "L1-0506-001": {
                            "content": "Context Planner creates transcript segmentation windows before candidate L1 extraction.",
                            "related_topics": ["transcript segmentation", "Context Planner"],
                        },
                        "L1-0506-002": {
                            "content": "Segment Agent converts transcript segments into idea units.",
                            "related_topics": ["idea units", "Segment Agent"],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            context = retrieve_short_term_context(
                query="Context Planner transcript segmentation candidate L1",
                api_key="test-key",
                memory_path=memory_path,
                l1_index_path=l1_index_path,
                source_preview_limit=2,
            )

        source_line = next(
            line for line in context.splitlines() if line.strip().startswith("source L1:")
        )
        self.assertIn("source L1: L1-0506-001, L1-0506-002", source_line)
        self.assertNotIn("L1-0307-001", source_line)

    def test_retrieval_uses_active_sources_before_historical_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_path = root / "short_term_memory.json"
            l1_index_path = root / "l1_index.json"
            memory_path.write_text(
                json.dumps(
                    {
                        "memory_version": 8,
                        "last_updated_meeting_id": "0506",
                        "units": [
                            {
                                "unit_id": "S001",
                                "title": "Active state for memory retrieval",
                                "summary": "Current active retrieval work is about query-aware source previews.",
                                "types": ["action_item"],
                                "related_topics": ["memory retrieval"],
                                "source_obj_ids": [
                                    "L1-0307-001",
                                    "L1-0318-001",
                                    "L1-0506-001",
                                ],
                                "active_source_obj_ids": ["L1-0506-001"],
                                "historical_source_obj_ids": ["L1-0307-001", "L1-0318-001"],
                                "status": "active",
                                "last_updated_meeting_id": "0506",
                                "missed_meeting_count": 0,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            l1_index_path.write_text(
                json.dumps(
                    {
                        "L1-0307-001": {"content": "Old retrieval architecture note."},
                        "L1-0318-001": {"content": "Old retrieval topic note."},
                        "L1-0506-001": {
                            "content": "Current active retrieval work uses query-aware source previews.",
                            "related_topics": ["memory retrieval"],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            context = retrieve_short_term_context(
                query="current active retrieval source preview",
                api_key="test-key",
                memory_path=memory_path,
                l1_index_path=l1_index_path,
                source_preview_limit=4,
            )

        self.assertIn("source_scope: active", context)
        self.assertIn("source L1: L1-0506-001", context)
        self.assertIn("historical_source_count: 2", context)
        self.assertNotIn("source L1: L1-0307-001", context)

    def test_legacy_units_derive_active_sources_from_recent_meeting_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_path = root / "short_term_memory.json"
            l1_index_path = root / "l1_index.json"
            memory_path.write_text(
                json.dumps(
                    {
                        "memory_version": 8,
                        "last_updated_meeting_id": "0506",
                        "meeting_history_ids": ["0307", "0318", "0325", "0408", "0422", "0429", "0506"],
                        "units": [
                            {
                                "unit_id": "S001",
                                "title": "Legacy memory retrieval unit",
                                "summary": "Legacy unit without explicit active sources.",
                                "types": ["action_item"],
                                "related_topics": ["memory retrieval"],
                                "source_obj_ids": [
                                    "L1-0307-001",
                                    "L1-0318-001",
                                    "L1-0429-001",
                                    "L1-0506-001",
                                ],
                                "last_updated_meeting_id": "0506",
                                "missed_meeting_count": 0,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            l1_index_path.write_text(
                json.dumps(
                    {
                        "L1-0307-001": {"content": "Old memory retrieval source."},
                        "L1-0318-001": {"content": "Older memory retrieval source."},
                        "L1-0429-001": {"content": "Recent memory retrieval source."},
                        "L1-0506-001": {"content": "Latest memory retrieval source."},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            context = retrieve_short_term_context(
                query="memory retrieval source",
                api_key="test-key",
                memory_path=memory_path,
                l1_index_path=l1_index_path,
                source_preview_limit=4,
            )

        self.assertIn("source_scope: derived_recent_active", context)
        self.assertIn("source L1: L1-0429-001, L1-0506-001", context)
        self.assertIn("historical_source_count: 2", context)
        self.assertNotIn("source L1: L1-0307-001", context)

    def test_retrieval_skips_resolved_or_superseded_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_path = Path(tmp) / "short_term_memory.json"
            memory_path.write_text(
                json.dumps(
                    {
                        "memory_version": 8,
                        "last_updated_meeting_id": "0506",
                        "units": [
                            {
                                "unit_id": "S001",
                                "title": "Resolved memory retrieval task",
                                "summary": "This old task has been resolved.",
                                "types": ["action_item"],
                                "related_topics": ["memory retrieval"],
                                "source_obj_ids": ["L1-0506-001"],
                                "status": "resolved",
                                "last_updated_meeting_id": "0506",
                                "missed_meeting_count": 0,
                            },
                            {
                                "unit_id": "S002",
                                "title": "Active memory retrieval task",
                                "summary": "This active task should remain visible.",
                                "types": ["action_item"],
                                "related_topics": ["memory retrieval"],
                                "source_obj_ids": ["L1-0506-002"],
                                "status": "active",
                                "last_updated_meeting_id": "0506",
                                "missed_meeting_count": 0,
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            context = retrieve_short_term_context(
                query="memory retrieval task",
                api_key="test-key",
                memory_path=memory_path,
                l1_index_path=Path(tmp) / "missing_l1_index.json",
            )

        self.assertIn("Active memory retrieval task", context)
        self.assertNotIn("Resolved memory retrieval task", context)

    def test_missing_or_empty_memory_returns_clear_message(self) -> None:
        context = retrieve_short_term_context(
            query="目前進度？",
            api_key="test-key",
            memory_path=Path("/tmp/does-not-exist-short-term-memory.json"),
        )

        self.assertEqual(context, "（無短期記憶）")


if __name__ == "__main__":
    unittest.main()
