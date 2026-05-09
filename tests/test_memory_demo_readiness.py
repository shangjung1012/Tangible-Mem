from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
LONG_TERM_DIR = REPO_ROOT / "long_term"
for path in (REPO_ROOT, APP_DIR, LONG_TERM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import memory_context  # noqa: E402
import recall  # noqa: E402


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class MemoryDemoReadinessTests(unittest.TestCase):
    def test_retrieve_long_term_context_formats_l1_hit_l2_and_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree_path = root / "share_mem" / "tree.json"
            l2_index_path = root / "long_term" / "l2" / "l2_index.json"
            l2_view_path = root / "long_term" / "l2" / "l2_view.json"
            _write_json(
                tree_path,
                {
                    "meetings": [
                        {
                            "meeting_id": "0307",
                            "meeting_date": "2026-03-07",
                            "memory_objects": [
                                {
                                    "obj_id": "L1-0307-001",
                                    "type": "decision",
                                    "content": "Use semantic L1 hits before expanding to L2.",
                                    "evidence": "The meeting decided L1 evidence is the recall entrypoint.",
                                    "importance": 0.9,
                                    "related_topics": ["memory retrieval"],
                                }
                            ],
                        }
                    ]
                },
            )
            _write_json(
                l2_index_path,
                {
                    "L1-0307-001": {
                        "obj_id": "L1-0307-001",
                        "l2_id": "L2-memory-retrieval",
                        "l2_label": "memory retrieval",
                        "confidence": 0.91,
                        "assignment_reason": "concept_rule",
                    }
                },
            )
            _write_json(
                l2_view_path,
                {
                    "l2_nodes": [
                        {
                            "l2_id": "L2-memory-retrieval",
                            "label": "memory retrieval",
                            "current_state": "Recall expands from L1 evidence into compact L2 context.",
                            "timeline_digest": [
                                {
                                    "meeting_id": "0307",
                                    "meeting_date": "2026-03-07",
                                    "obj_id": "L1-0307-001",
                                    "summary": "The team chose semantic L1 hits as the recall entrypoint.",
                                }
                            ],
                            "linked_obj_ids": ["L1-0307-001"],
                            "meeting_ids": ["0307"],
                        }
                    ]
                },
            )

            with patch.object(memory_context, "LONG_TERM_TREE_PATH", tree_path), patch.object(
                memory_context,
                "LONG_TERM_L2_INDEX_PATH",
                l2_index_path,
            ), patch.object(
                memory_context,
                "LONG_TERM_L2_VIEW_PATH",
                l2_view_path,
            ), patch.object(
                memory_context,
                "plan_recall",
                return_value={
                    "complexity": "simple",
                    "search_targets": ["long_term_l1", "long_term_l2"],
                    "keywords": ["memory retrieval"],
                },
            ), patch.object(
                recall,
                "embed_text",
                return_value=[1.0],
            ), patch.object(
                recall,
                "search_l1_semantic",
                return_value=[
                    {
                        "source": "long_term_l1",
                        "meeting_id": "0307",
                        "meeting_date": "2026-03-07",
                        "obj_id": "L1-0307-001",
                        "type": "decision",
                        "content": "Use semantic L1 hits before expanding to L2.",
                        "evidence": "The meeting decided L1 evidence is the recall entrypoint.",
                        "importance": 0.9,
                        "related_topics": ["memory retrieval"],
                        "score": 0.94,
                    }
                ],
            ):
                context = memory_context.retrieve_long_term_context(
                    query="How does memory retrieval expand from L1 to L2?",
                    api_key="test-key",
                    model_name="test-model",
                )

        self.assertIn("=== Global Topic Map ===", context)
        self.assertIn("=== L1 Evidence Seeds ===", context)
        self.assertIn("=== L2 / Child-L2 Evolution Context ===", context)
        self.assertIn("matched L1: L1-0307-001", context)
        self.assertIn("timeline_digest:", context)
        self.assertIn("The team chose semantic L1 hits", context)
        self.assertIn("Use semantic L1 hits before expanding to L2.", context)


if __name__ == "__main__":
    unittest.main()
