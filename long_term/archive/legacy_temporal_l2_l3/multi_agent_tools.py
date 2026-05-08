"""Compatibility alias for share_mem.l1.multi_agent_tools."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from share_mem.l1 import multi_agent_tools as _impl

sys.modules[__name__] = _impl
