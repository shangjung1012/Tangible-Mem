from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_DIR = REPO_ROOT / "long_term"
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

from embedder import EmbedCache  # noqa: E402


class EmbedderTests(unittest.TestCase):
    def test_embed_cache_save_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "cache.json"
            cache = EmbedCache(path)
            cache.set("hello", [1.0, 2.0], model="test-model")

            cache.save()

            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
