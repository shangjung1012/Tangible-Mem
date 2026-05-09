from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROTOTYPE_DIR = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = LONG_TERM_DIR.parent
THREAD_PROTOTYPE_DIR = LONG_TERM_DIR / "archive" / "prototype_l2_threads"
sys.path.insert(0, str(PROTOTYPE_DIR))
sys.path.insert(0, str(THREAD_PROTOTYPE_DIR))
sys.path.insert(0, str(LONG_TERM_DIR))

from l2_debug_viewer import build_l2_debug_viewer  # noqa: E402


class L2DebugViewerTests(unittest.TestCase):
    def test_builds_static_html_with_l1_and_l2_data(self) -> None:
        meeting = {
            "meeting_id": "0307",
            "memory_objects": [
                {
                    "obj_id": "L1-0307-001",
                    "type": "decision",
                    "content": "Compare a memory-enhanced agent with a baseline.",
                    "importance": 0.88,
                    "related_topics": ["memory evaluation"],
                    "evidence": "compare memory agent",
                }
            ],
        }
        topics = {
            "topics": [
                {
                    "thread_id": "T-L2-001",
                    "title": "Memory Evaluation",
                    "description": "Evaluation topic.",
                    "keywords": ["memory evaluation"],
                    "importance": 0.88,
                    "source_l1_ids": ["L1-0307-001"],
                }
            ]
        }
        assignments = {
            "items": [
                {
                    "source_l1_id": "L1-0307-001",
                    "action": "create_thread",
                    "target_thread_id": "T-L2-001",
                    "confidence": 0.8,
                    "reason": "new evaluation topic",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            l1_file = root / "final_meeting_node.json"
            l2_dir = root / "l2"
            l2_dir.mkdir()
            l1_file.write_text(json.dumps(meeting), encoding="utf-8")
            (l2_dir / "05_l2_l1_assignments.json").write_text(
                json.dumps(assignments),
                encoding="utf-8",
            )
            (l2_dir / "06_l2_topic_threads.json").write_text(
                json.dumps(topics),
                encoding="utf-8",
            )
            (l2_dir / "08_l2_validation_report.json").write_text(
                json.dumps({"valid": True, "errors": [], "warnings": []}),
                encoding="utf-8",
            )

            result = build_l2_debug_viewer(
                l1_files=[l1_file],
                l2_dir=l2_dir,
                out_path=root / "viewer.html",
            )

            html = result.html_path.read_text(encoding="utf-8")
            self.assertIn("L1 / L2 Memory Debug Viewer", html)
            self.assertIn("Memory Evaluation", html)
            self.assertIn("L1-0307-001", html)
            self.assertIn("create_thread", html)


if __name__ == "__main__":
    unittest.main()
