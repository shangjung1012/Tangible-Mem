from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
sys.path.insert(0, str(LONG_TERM_DIR))

from l1_quality import (  # noqa: E402
    l1_quality_hashes,
    merge_l1_quality_index,
    remove_l1_quality_for_meeting,
)
from memory_activity import build_memory_activity_update  # noqa: E402
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

    def test_remove_quality_index_entries_for_one_meeting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l1_quality_index.json"
            merge_l1_quality_index(
                path,
                {
                    "L1-A-001": {"meeting_id": "A", "quality_level": "normal"},
                    "L1-B-001": {"meeting_id": "B", "quality_level": "strong"},
                },
            )
            filtered = remove_l1_quality_for_meeting(path, "A")

        self.assertEqual(set(filtered), {"L1-B-001"})

    def test_l2_prompt_includes_compact_quality_tags_and_rules(self) -> None:
        obj = {
            "obj_id": "L1-M1-001",
            "type": "method_change",
            "importance": 0.78,
            "content": "Use tool calling to incrementally read transcript spans.",
            "evidence": "The model can read a span, update candidates, and continue.",
        }
        meetings = [
            {
                "meeting_id": "M1",
                "memory_objects": [obj],
            }
        ]
        quality_index = {
            "L1-M1-001": {
                "quality_level": "tentative",
                "support_score": 0.42,
                **l1_quality_hashes(obj),
                "viewpoint_recurrence": {
                    "episode_count": 3,
                    "actual_bonus": 0.04,
                },
                "quality_warnings": ["source_unit_uncertainty_note"],
            }
        }
        activity_index = build_memory_activity_update(
            tree={"meetings": [{"meeting_id": "M1", "meeting_date": "2026-05-01", "memory_objects": [obj]}]},
            meeting_id="M1",
        )
        relations_index = {
            "L1-M1-001": [
                {
                    "target_obj_id": "L1-M0-001",
                    "relation": "continues",
                    "confidence": 0.76,
                }
            ]
        }

        prompt = _build_phase_summary_prompt(
            "P-001",
            meetings,
            quality_index,
            activity_index,
            relations_index,
        )

        self.assertIn("quality=tentative", prompt)
        self.assertIn("support=0.42", prompt)
        self.assertIn("activity=active", prompt)
        self.assertIn("relations=continues:L1-M0-001", prompt)
        self.assertIn("recurrence=3 episodes", prompt)
        self.assertIn("quality=tentative 的 L1 只能當背景", prompt)
        self.assertIn("relations=supersedes:*", prompt)
        self.assertIn("argument 不要直接升級成 change", prompt)

    def test_l2_prompt_ignores_stale_quality_metadata(self) -> None:
        old_obj = {
            "obj_id": "L1-M1-001",
            "type": "method_change",
            "content": "Old content",
            "evidence": "Old evidence",
        }
        new_obj = {
            "obj_id": "L1-M1-001",
            "type": "method_change",
            "importance": 0.7,
            "content": "New content after rerun",
            "evidence": "New evidence after rerun",
        }
        prompt = _build_phase_summary_prompt(
            "P-001",
            [{"meeting_id": "M1", "memory_objects": [new_obj]}],
            {
                "L1-M1-001": {
                    "quality_level": "strong",
                    "support_score": 0.92,
                    **l1_quality_hashes(old_obj),
                }
            },
        )

        self.assertIn(
            "(quality=unknown; support=unknown; activity=unknown; relations=none) New content after rerun",
            prompt,
        )
        self.assertNotIn("(quality=strong", prompt)


if __name__ == "__main__":
    unittest.main()
