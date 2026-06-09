from __future__ import annotations

from pathlib import Path
from typing import Any


def default_backend_specs(*, optimization_run_root: Path | str) -> dict[str, dict[str, Any]]:
    run_root = Path(optimization_run_root).as_posix()
    return {
        "canonical": {
            "backend_name": "canonical",
            "role": "active_baseline",
            "env": {},
            "expected_backend": "canonical",
        },
        "optimization_v2": {
            "backend_name": "optimization_v2",
            "role": "shadow_candidate",
            "env": {
                "LONG_TERM_BACKEND": "optimization_v2",
                "OPTIMIZATION_V2_RUN_ROOT": run_root,
            },
            "expected_backend": "optimization_v2",
        },
    }
