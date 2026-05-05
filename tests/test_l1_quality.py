from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
sys.path.insert(0, str(LONG_TERM_DIR))

from l1_quality import merge_l1_quality_index  # noqa: E402
from summarize import _build_phase_summary_prompt  # noqa: E402


class L1QualitySidecarTests(unittest.TestCase):
    def test_quality_index_merge_preserves_unrelated_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l1_quality_index.json"
            merge_l1_quality_index(
                path,
                {
                    "L1-A-001": {
                        "meeting_id": "A",
                        "quality_level": "normal",
                        "support_score": 0.61,
                    }
                },
            )
            merged = merge_l1_quality_index(
                path,
                {
                    "L1-B-001": {
                        "meeting_id": "B",
                        "quality_level": "strong",
                        "support_score": 0.84,
                    }
                },
            )

        self.assertEqual(set(merged), {"L1-A-001", "L1-B-001"})
        self.assertEqual(merged["L1-A-001"]["quality_level"], "normal")
        self.assertEqual(merged["L1-B-001"]["quality_level"], "strong")

    def test_l2_prompt_includes_compact_quality_tags_and_rules(self) -> None:
        meetings = [
            {
                "meeting_id": "M1",
                "memory_objects": [
                    {
                        "obj_id": "L1-M1-001",
                        "type": "method_change",
                        "importance": 0.78,
                        "content": "Use tool calling to incrementally read transcript spans.",
                        "evidence": "The model can read a span, update candidates, and continue.",
                    }
                ],
            }
        ]
        quality_index = {
            "L1-M1-001": {
                "quality_level": "tentative",
                "support_score": 0.42,
                "viewpoint_recurrence": {
                    "episode_count": 3,
                    "actual_bonus": 0.04,
                },
                "quality_warnings": ["source_unit_uncertainty_note"],
            }
        }

        prompt = _build_phase_summary_prompt("P-001", meetings, quality_index)

        self.assertIn("quality=tentative", prompt)
        self.assertIn("support=0.42", prompt)
        self.assertIn("recurrence=3 episodes", prompt)
        self.assertIn("quality=tentative 的 L1 只能當背景", prompt)
        self.assertIn("argument 不要直接升級成 change", prompt)


if __name__ == "__main__":
    unittest.main()
