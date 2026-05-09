from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROTOTYPE_DIR = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = LONG_TERM_DIR.parent
sys.path.insert(0, str(PROTOTYPE_DIR))
sys.path.insert(0, str(LONG_TERM_DIR))

from l2_topic_agents import (  # noqa: E402
    build_l0_summary_heuristic,
    route_l1_assignment,
    run_l2_topic_agents,
    should_promote_l1,
)


class L2TopicAgentsTests(unittest.TestCase):
    def test_l0_heuristic_uses_important_l1_nodes(self) -> None:
        meeting = {
            "meeting_id": "0307",
            "memory_objects": [
                {
                    "obj_id": "L1-0307-001",
                    "type": "decision",
                    "content": "The team decided to compare a memory-enhanced agent with a baseline.",
                    "importance": 0.9,
                    "related_topics": ["memory evaluation", "baseline"],
                },
                {
                    "obj_id": "L1-0307-002",
                    "type": "todo",
                    "content": "Buy snacks.",
                    "importance": 0.2,
                    "related_topics": [],
                },
            ],
        }

        summary = build_l0_summary_heuristic(meeting)

        self.assertEqual(summary["meeting_id"], "0307")
        self.assertIn("memory evaluation", summary["main_topics"])
        self.assertEqual(summary["source_l1_ids"][0], "L1-0307-001")

    def test_admin_l1_is_retained_not_promoted(self) -> None:
        node = {
            "obj_id": "L1-0307-016",
            "type": "todo",
            "content": "Remember to handle API key reimbursement.",
            "importance": 0.83,
            "related_topics": ["admin"],
        }

        promote, reason = should_promote_l1(node)
        decision = route_l1_assignment(node, [])

        self.assertFalse(promote)
        self.assertIn("administrative", reason)
        self.assertEqual(decision["action"], "retain_l1_only")

    def test_pipeline_writes_l2_named_artifacts_and_ui_graph(self) -> None:
        meeting_0307 = {
            "meeting_id": "0307",
            "timestamp": "2026-03-07T00:00:00Z",
            "memory_objects": [
                {
                    "obj_id": "L1-0307-001",
                    "type": "decision",
                    "content": "The team will evaluate long-term memory by comparing a memory-enhanced agent with a baseline.",
                    "importance": 0.88,
                    "related_topics": ["memory evaluation", "baseline"],
                    "evidence": "compare memory agent",
                }
            ],
        }
        meeting_0408 = {
            "meeting_id": "0408",
            "timestamp": "2026-04-08T00:00:00Z",
            "memory_objects": [
                {
                    "obj_id": "L1-0408-001",
                    "type": "method_change",
                    "content": "Evaluation should include a baseline comparison for the long-term memory system.",
                    "importance": 0.8,
                    "related_topics": ["memory evaluation", "baseline"],
                    "evidence": "baseline comparison",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            l1_0307 = root / "0307_final_meeting_node.json"
            l1_0408 = root / "0408_final_meeting_node.json"
            l1_0307.write_text(json.dumps(meeting_0307), encoding="utf-8")
            l1_0408.write_text(json.dumps(meeting_0408), encoding="utf-8")

            result = run_l2_topic_agents(
                l1_files=[l1_0307, l1_0408],
                output_dir=root / "l2_output",
                l0_mode="heuristic",
            )

            self.assertTrue(result.l0_summary_path.exists())
            self.assertTrue(result.topics_path.exists())
            self.assertTrue(result.assignments_path.exists())
            self.assertTrue(result.ui_graph_path.exists())

            topics = json.loads(result.topics_path.read_text(encoding="utf-8"))["topics"]
            assignments = json.loads(result.assignments_path.read_text(encoding="utf-8"))["items"]
            graph = json.loads(result.ui_graph_path.read_text(encoding="utf-8"))

            self.assertEqual(len(topics), 1)
            self.assertEqual(assignments[0]["action"], "create_thread")
            self.assertEqual(assignments[1]["action"], "attach_thread")
            self.assertEqual(len(graph["nodes"]), 5)
            self.assertEqual(graph["ui_hints"]["primary_levels"], ["meeting", "l2_topic", "l1"])


if __name__ == "__main__":
    unittest.main()
