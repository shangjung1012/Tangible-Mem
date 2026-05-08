from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))


class LongTermArchiveTests(unittest.TestCase):
    def test_active_cli_exposes_l2_commands_only(self) -> None:
        cli = importlib.import_module("cli")

        self.assertIn("build-l2-view", cli.COMMANDS)
        self.assertIn("validate-l2-view", cli.COMMANDS)
        self.assertNotIn("bridge", cli.COMMANDS)
        self.assertIn("bridge", cli.LEGACY_COMMANDS)

    def test_legacy_temporal_modules_are_archived(self) -> None:
        legacy_dir = LONG_TERM_DIR / "archive" / "legacy_temporal_l2_l3"

        self.assertFalse((LONG_TERM_DIR / "bridge.py").exists())
        self.assertFalse((LONG_TERM_DIR / "tree.json").exists())
        self.assertTrue((legacy_dir / "bridge.py").exists())
        self.assertTrue((legacy_dir / "tree.json").exists())
        self.assertTrue((legacy_dir / "snapshots").is_dir())

    def test_app_memory_context_still_imports_active_recall_stack(self) -> None:
        from app import memory_context

        self.assertTrue(callable(memory_context.retrieve_long_term_context))
        self.assertEqual(
            memory_context.LONG_TERM_TREE_PATH,
            REPO_ROOT / "share_mem" / "tree.json",
        )


if __name__ == "__main__":
    unittest.main()
