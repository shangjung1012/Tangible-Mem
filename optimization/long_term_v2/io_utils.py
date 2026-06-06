from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
OPTIMIZATION_ROOT = REPO_ROOT / "optimization"


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path | str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path | str, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def tree_hash(tree: dict[str, Any]) -> str:
    payload = json.dumps(tree, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_clean_dir(path: Path | str) -> Path:
    target = Path(path)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_optimization_output(path: Path | str) -> Path:
    target = Path(path)
    resolved = target.resolve()
    if "optimization" not in {part.lower() for part in resolved.parts}:
        raise ValueError(f"optimization v2 outputs must be under an optimization/ root: {resolved}")
    target.mkdir(parents=True, exist_ok=True)
    return target


def copy_input_snapshot(*, share_mem_root: Path | str, run_root: Path | str) -> dict[str, Any]:
    source = Path(share_mem_root) / "tree.json"
    snapshot_dir = Path(run_root) / "input_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    target = snapshot_dir / "tree.json"
    if source.exists():
        shutil.copy2(source, target)
    manifest = {
        "source_tree_path": str(source.resolve()),
        "snapshot_tree_path": str(target.resolve()),
        "snapshot_exists": target.exists(),
        "generated_at_utc": utc_now_iso(),
    }
    write_json(snapshot_dir / "manifest.json", manifest)
    return manifest
