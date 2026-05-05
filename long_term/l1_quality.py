"""Sidecar helpers for L1 quality metadata.

The canonical long-term tree intentionally keeps memory objects compact.  This
module stores audit/quality signals beside the tree so L2/L3 summarization can
use them without changing the public L1 schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from io_utils import save_json

QUALITY_LEVELS = ("strong", "normal", "tentative", "weak")


def quality_index_default_path(tree_path: Path) -> Path:
    return tree_path.parent / "l1_quality_index.json"


def load_l1_quality_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid L1 quality index JSON: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"L1 quality index must be a JSON object: {path}")
    return data


def save_l1_quality_index(path: Path, quality_index: dict[str, Any]) -> None:
    save_json(path, quality_index)


def merge_l1_quality_index(
    path: Path,
    updates: dict[str, Any],
) -> dict[str, Any]:
    existing = load_l1_quality_index(path)
    if updates:
        existing.update(updates)
        save_l1_quality_index(path, existing)
    return existing


def derive_quality_level(
    *,
    support_score: float | None,
    source_unit_quality: list[str] | None = None,
    quality_warnings: list[str] | None = None,
) -> str:
    support = float(support_score or 0.0)
    qualities = {
        str(value or "").strip().lower()
        for value in (source_unit_quality or [])
        if str(value or "").strip()
    }
    warnings = {
        str(value or "").strip().lower()
        for value in (quality_warnings or [])
        if str(value or "").strip()
    }
    repaired_or_partial = bool(
        qualities
        & {"partial", "incomplete", "uncertain", "unknown", "fallback", "compacted"}
    ) or bool(
        warnings
        & {
            "validator_repaired_source_unit",
            "uncertain_source_unit",
            "source_unit_uncertainty_note",
        }
    )

    if support < 0.25:
        return "weak"
    if support >= 0.75 and not repaired_or_partial:
        return "strong"
    if support >= 0.45 and not ("validator_repaired_source_unit" in warnings):
        return "normal"
    return "tentative"


def format_l1_quality_tag(
    obj: dict[str, Any],
    quality_index: dict[str, Any] | None,
) -> str:
    obj_id = str(obj.get("obj_id", "")).strip()
    meta = (quality_index or {}).get(obj_id, {})
    if not isinstance(meta, dict):
        meta = {}

    level = str(meta.get("quality_level") or "unknown")
    support = meta.get("support_score")
    recurrence = meta.get("viewpoint_recurrence")
    warnings = meta.get("quality_warnings", [])

    parts = [f"quality={level}"]
    if isinstance(support, int | float):
        parts.append(f"support={float(support):.2f}")
    else:
        parts.append("support=unknown")
    if isinstance(recurrence, dict):
        episode_count = recurrence.get("episode_count")
        actual_bonus = recurrence.get("actual_bonus")
        if episode_count:
            parts.append(f"recurrence={episode_count} episodes")
        if actual_bonus:
            parts.append(f"recurrence_bonus={float(actual_bonus):.2f}")
    if isinstance(warnings, list) and warnings:
        shown = ",".join(str(item) for item in warnings[:3])
        parts.append(f"warnings={shown}")
    return "; ".join(parts)
