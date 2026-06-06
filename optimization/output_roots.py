from __future__ import annotations

import re
from pathlib import Path


CANONICAL_ROOT_NAMES = {"share_mem", "long_term"}


def _slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    clean = clean.strip("._-")
    if not clean:
        raise ValueError("run path component cannot be empty")
    return clean


def _has_canonical_part(path: Path) -> bool:
    return any(part in CANONICAL_ROOT_NAMES for part in path.parts)


def resolve_memory_run_root(
    *,
    base_root: Path | str,
    dataset: str,
    run_kind: str,
    run_id: str,
) -> Path:
    base = Path(base_root)
    if _has_canonical_part(base):
        raise ValueError(f"Refusing canonical output root: {base}")
    return base / _slug(dataset) / "runs" / f"{_slug(run_kind)}_{_slug(run_id)}"
