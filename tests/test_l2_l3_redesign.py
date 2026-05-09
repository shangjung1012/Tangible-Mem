from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
LEGACY_LONG_TERM_DIR = LONG_TERM_DIR / "archive" / "legacy_temporal_l2_l3"
sys.path.insert(0, str(LONG_TERM_DIR))
sys.path.insert(0, str(LEGACY_LONG_TERM_DIR))

import recall  # noqa: E402
import schema  # noqa: E402
import summarize  # noqa: E402


class L2L3RedesignTests(unittest.TestCase):
    def test_default_tree_uses_new_project_profile_fields(self) -> None:
        profile = schema.DEFAULT_TREE["project_profile"]

        self.assertIn("core_goal", profile)
        self.assertIn("current_phase", profile)
        self.assertIn("established_methods", profile)
        self.assertIn("long_term_open_questions", profile)
        self.assertNotIn("methodology", profile)
        self.assertNotIn("core_values", profile)
        self.assertNotIn("method_timeline", profile)

    def test_get_l3_profile_gates_on_new_fields(self) -> None:
        empty_tree = {"project_profile": {}}
        self.assertIsNone(recall.get_l3_profile(empty_tree))

        tree = {
            "project_profile": {
                "project_id": "virtual-mentor",
                "core_goal": "Build a corpus",
                "current_phase": "",
                "established_methods": [],
                "long_term_open_questions": [],
            }
        }
        profile = recall.get_l3_profile(tree)

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile["source"], "long_term_l3")
        self.assertEqual(profile["core_goal"], "Build a corpus")

    def test_format_recall_for_prompt_uses_new_l2_l3_sections(self) -> None:
        recall_result = {
            "project_profile": {
                "core_goal": "建立會議語音語料庫",
                "current_phase": "轉錄流程建立",
                "established_methods": ["錄音：16kHz 降採樣"],
                "long_term_open_questions": ["格式標準尚未決定"],
            },
            "long_term_l2": [
                {
                    "phase_id": "P-007",
                    "time_range": {"start": "Bmr027", "end": "Bmr030"},
                    "summary": "同意書流程完善與轉錄工具改進",
                    "changes": [
                        {"status": "adopted", "method": "Transcriber 截短檔案"},
                        {"status": "abandoned", "method": "遞增音調蜂鳴聲"},
                        {"status": "evolved", "method": "男性專用訓練資料"},
                    ],
                    "open_to_next": ["多波形顯示尚未實作"],
                }
            ],
            "long_term_l1": [],
            "short_term_results": [],
        }

        formatted = recall.format_recall_for_prompt(recall_result)

        self.assertIn("=== Legacy Temporal L2 Fallback ===", formatted)
        self.assertIn("[Phase P-007 | Bmr027 ~ Bmr030]", formatted)
        self.assertIn("summary: 同意書流程完善與轉錄工具改進", formatted)
        self.assertNotIn("=== 研究計畫輪廓 (L3) ===", formatted)
        self.assertNotIn("方法論：", formatted)
        self.assertNotIn("關鍵決策", formatted)

    def test_profile_prompt_uses_changes_and_slim_profile_only(self) -> None:
        prompt = summarize._build_profile_update_prompt(
            phases=[
                {
                    "phase_id": "P-001",
                    "time_range": {"start": "Bmr001", "end": "Bmr004"},
                    "summary": "建立錄音流程",
                    "changes": [{"status": "adopted", "method": "全程開麥"}],
                    "open_to_next": ["格式標準待確認"],
                }
            ],
            current_profile={
                "core_goal": "建立語料庫",
                "current_phase": "錄音系統穩定化",
                "established_methods": ["16kHz 降採樣"],
                "long_term_open_questions": ["LDC vs 自定義格式"],
                "child_phase_ids": ["P-001"],
            },
        )

        self.assertIn("[adopted] 全程開麥", prompt)
        self.assertIn("[open] 格式標準待確認", prompt)
        self.assertIn('"core_goal": "建立語料庫"', prompt)
        self.assertNotIn("child_phase_ids", prompt)


if __name__ == "__main__":
    unittest.main()
