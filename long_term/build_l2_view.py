from __future__ import annotations

import sys
from pathlib import Path

_ARCHIVE_DIR = Path(__file__).resolve().parent / "archive" / "canonical_l2_l3_builder_legacy"
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ARCHIVE_DIR) not in sys.path:
    sys.path.insert(0, str(_ARCHIVE_DIR))

from archive.canonical_l2_l3_builder_legacy.build_l2_view import *  # noqa: F401,F403,E402


if __name__ == "__main__":
    _main = globals().get("main")
    if callable(_main):
        _main()
