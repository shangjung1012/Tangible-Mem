from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROTOTYPE_DIR = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = LONG_TERM_DIR.parent
sys.path.insert(0, str(PROTOTYPE_DIR))
sys.path.insert(0, str(LONG_TERM_DIR))

from thread_l2 import (  # noqa: E402
    apply_thread_decisions,
    heuristic_thread_decisions,
    l1_nodes_for_meeting,
    prefilter_threads,
    run_thread_l2_demo,
    select_meetings,
)


class ThreadL2Tests(unittest.TestCase):
    def test_select_meetings_preserves_requested_order(self) -> None:
        tree = {
            "meetings": [
                {"meeting_id": "0408", "memory_objects": []},
                {"meeting_id": "0307", "memory_objects": []},
            ]
        }

        meetings = select_meetings(tree, ["0307", "0408"])

        self.assertEqual([m["meeting_id"] for m in meetings], ["0307", "0408"])

    def test_apply_thread_decisions_creates_and_appends_episode(self) -> None:
        meeting = {"meeting_id": "0307"}
        l1_nodes = [
            {
                "obj_id": "L1-0307-001",
                "type": "decision",
                "content": "晚會時間可能安排在週五晚上。",
                "related_topics": ["晚會", "時間"],
            }
        ]
        decisions = [
            {
                "source_l1_id": "L1-0307-001",
                "action": "create_thread",
                "target_thread_id": "",
                "title": "晚會時間安排",
                "topic_path": ["營隊", "晚會", "時間"],
                "reason": "new planning topic",
                "episode_summary": "晚會時間可能安排在週五晚上。",
                "change_type": "new_information",
                "current_status": "晚會時間尚未決定。",
                "current_facts": ["候選時間包含週五晚上"],
                "constraints": [],
                "open_questions": ["晚會時間尚未決定"],
            }
        ]

        threads, applied, next_index = apply_thread_decisions(
            meeting=meeting,
            l1_nodes=l1_nodes,
            threads=[],
            decisions=decisions,
            next_thread_index=1,
        )

        self.assertEqual(next_index, 2)
        self.assertEqual(threads[0]["thread_id"], "T-001")
        self.assertEqual(threads[0]["episodes"][0]["source_l1_ids"], ["L1-0307-001"])
        self.assertEqual(applied[0]["target_thread_id"], "T-001")

    def test_heuristic_demo_builds_replayable_steps(self) -> None:
        tree = {
            "meetings": [
                {
                    "meeting_id": "0307",
                    "memory_objects": [
                        {
                            "obj_id": "L1-0307-001",
                            "type": "decision",
                            "content": "晚會時間可能安排在週五晚上。",
                            "importance": 0.7,
                            "related_topics": ["晚會", "時間"],
                        }
                    ],
                },
                {
                    "meeting_id": "0408",
                    "memory_objects": [
                        {
                            "obj_id": "L1-0408-001",
                            "type": "method_change",
                            "content": "晚會時間需要避開期中考週。",
                            "importance": 0.72,
                            "related_topics": ["晚會", "時間"],
                        }
                    ],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            result = run_thread_l2_demo(
                tree=tree,
                meeting_ids=["0307", "0408"],
                out_dir=Path(tmp),
                heuristic_only=True,
            )

            self.assertTrue(result.artifact_path.exists())
            self.assertTrue(result.viewer_path.exists())
            self.assertEqual(len(result.demo["steps"]), 2)
            self.assertGreaterEqual(len(result.demo["final_threads"]), 1)
            self.assertEqual(result.demo["steps"][0]["meeting_id"], "0307")


if __name__ == "__main__":
    unittest.main()
