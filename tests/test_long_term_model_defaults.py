from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
LEGACY_LONG_TERM_DIR = LONG_TERM_DIR / "archive" / "legacy_temporal_l2_l3"
sys.path.insert(0, str(LONG_TERM_DIR))
sys.path.insert(0, str(LEGACY_LONG_TERM_DIR))

from bridge import resolve_model_name as resolve_bridge_model_name  # noqa: E402
from build_tree import resolve_model_name as resolve_build_tree_model_name  # noqa: E402
from rebuild_snapshots import resolve_model_name as resolve_rebuild_model_name  # noqa: E402
from schema import DEFAULT_MODEL_NAME  # noqa: E402
from summarize import resolve_model_name as resolve_summarize_model_name  # noqa: E402


class LongTermModelDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_model = os.environ.get("GEMINI_MODEL")

    def tearDown(self) -> None:
        if self.original_model is None:
            os.environ.pop("GEMINI_MODEL", None)
        else:
            os.environ["GEMINI_MODEL"] = self.original_model

    def test_bridge_model_default_uses_loaded_env_value(self) -> None:
        os.environ["GEMINI_MODEL"] = "gemini-2.5-pro"

        self.assertEqual(resolve_bridge_model_name(None), "gemini-2.5-pro")
        self.assertEqual(resolve_bridge_model_name("gemini-2.5-flash"), "gemini-2.5-flash")

    def test_summarize_model_default_uses_loaded_env_value(self) -> None:
        os.environ["GEMINI_MODEL"] = "gemini-2.5-pro"

        self.assertEqual(resolve_summarize_model_name(None), "gemini-2.5-pro")
        self.assertEqual(resolve_summarize_model_name("gemini-2.5-flash"), "gemini-2.5-flash")

    def test_batch_tools_share_model_default_resolution(self) -> None:
        os.environ["GEMINI_MODEL"] = "gemini-2.5-pro"

        self.assertEqual(resolve_build_tree_model_name(None), "gemini-2.5-pro")
        self.assertEqual(resolve_rebuild_model_name(None), "gemini-2.5-pro")
        self.assertEqual(resolve_build_tree_model_name("gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(resolve_rebuild_model_name("gemini-2.5-flash"), "gemini-2.5-flash")

    def test_model_default_falls_back_to_schema_default(self) -> None:
        os.environ.pop("GEMINI_MODEL", None)

        self.assertEqual(resolve_bridge_model_name(None), DEFAULT_MODEL_NAME)
        self.assertEqual(resolve_summarize_model_name(None), DEFAULT_MODEL_NAME)
        self.assertEqual(resolve_build_tree_model_name(None), DEFAULT_MODEL_NAME)
        self.assertEqual(resolve_rebuild_model_name(None), DEFAULT_MODEL_NAME)


if __name__ == "__main__":
    unittest.main()
