from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

import current_state_context  # noqa: E402


class CurrentStateContextTests(unittest.TestCase):
    def test_current_implementation_query_triggers_current_state_context(self) -> None:
        self.assertTrue(
            current_state_context.should_include_current_state_context(
                "L1 到 L2 的分群現在是怎麼決定的？"
            )
        )
        self.assertTrue(
            current_state_context.should_include_current_state_context(
                "What is the current repo implementation for L2 grouping?"
            )
        )

    def test_historical_query_does_not_force_current_state_context(self) -> None:
        self.assertFalse(
            current_state_context.should_include_current_state_context(
                "我們之前為什麼要把 transcript 拆成 segment / idea units？"
            )
        )

    def test_context_block_describes_current_topic_l2_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "long_term" / "l2").mkdir(parents=True)
            (root / "long_term" / "l3").mkdir(parents=True)
            (root / "long_term" / "eval").mkdir(parents=True)
            (root / "share_mem").mkdir(parents=True)
            (root / "share_mem" / "manifest.json").write_text(
                json.dumps({"meeting_count": 7, "object_count": 448}),
                encoding="utf-8",
            )
            (root / "long_term" / "l2" / "manifest.json").write_text(
                json.dumps({"topic_count": 15, "linked_l1_count": 411}),
                encoding="utf-8",
            )
            (root / "long_term" / "l3" / "l3_view.json").write_text(
                json.dumps({"l3_nodes": [{"l3_id": "L3-memory", "child_l2_nodes": [{"l2_id": "L2-child"}]}]}),
                encoding="utf-8",
            )
            (root / "long_term" / "eval" / "retrieval_eval_report.json").write_text(
                json.dumps({"budget_profile": "generous_layered"}),
                encoding="utf-8",
            )

            block = current_state_context.build_current_state_context(root)

        self.assertIn("=== Current Implementation State ===", block)
        self.assertIn("share_mem/tree.json", block)
        self.assertIn("long_term/l2/l2_view.json", block)
        self.assertIn("topic-based", block)
        self.assertIn("L3 promotion", block)
        self.assertIn("generous_layered", block)


if __name__ == "__main__":
    unittest.main()
