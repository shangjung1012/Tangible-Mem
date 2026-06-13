from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import load_json


def _load_optional_json(path: Path, fallback: Any) -> Any:
    return load_json(path) if path.exists() else fallback


def _suppressed_l2_ids(run_root: Path) -> list[str]:
    path = run_root / "topic_review" / "effective_topic_index.json"
    if not path.exists():
        return []
    payload = load_json(path)
    return sorted(
        {
            str(l2_id)
            for l2_id in payload.get("suppressed_l2_ids", []) or []
            if str(l2_id).strip()
        }
    )


def _filter_l2_view(l2_view: dict[str, Any], suppressed: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    active_nodes: list[dict[str, Any]] = []
    suppressed_nodes: list[dict[str, Any]] = []
    for node in l2_view.get("l2_nodes", []) or []:
        if not isinstance(node, dict):
            continue
        l2_id = str(node.get("l2_id", "") or "")
        if l2_id in suppressed:
            suppressed_nodes.append(node)
        else:
            active_nodes.append(node)
    return {**l2_view, "l2_nodes": active_nodes}, suppressed_nodes


def _filter_l2_index(l2_index: dict[str, Any], suppressed: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    active: dict[str, Any] = {}
    suppressed_index: dict[str, Any] = {}
    for obj_id, assignment in l2_index.items():
        if not isinstance(assignment, dict):
            active[str(obj_id)] = assignment
            continue
        l2_id = str(assignment.get("l2_id", "") or "")
        if l2_id in suppressed:
            suppressed_index[str(obj_id)] = assignment
        else:
            active[str(obj_id)] = assignment
    return active, suppressed_index


def _suppressed_l3_parent_ids(l3_view: dict[str, Any], suppressed_l2_ids: set[str]) -> set[str]:
    parent_ids: set[str] = set()
    for parent in l3_view.get("l3_parents", []) or []:
        if not isinstance(parent, dict):
            continue
        source_l2_id = str(parent.get("source_l2_id", "") or parent.get("promoted_from_l2_id", "") or "")
        parent_l3_id = str(parent.get("l3_id", "") or "")
        if source_l2_id in suppressed_l2_ids and parent_l3_id:
            parent_ids.add(parent_l3_id)
    return parent_ids


def _filter_l3_view(l3_view: dict[str, Any], suppressed_l2_ids: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
    active: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    suppressed_parent_ids = _suppressed_l3_parent_ids(l3_view, suppressed_l2_ids)
    for parent in l3_view.get("l3_parents", []) or []:
        if not isinstance(parent, dict):
            continue
        parent_l3_id = str(parent.get("l3_id", "") or "")
        if parent_l3_id in suppressed_parent_ids:
            suppressed.append(parent)
        else:
            active.append(parent)
    return {**l3_view, "l3_parents": active}, suppressed, suppressed_parent_ids


def _filter_l3_index(l3_index: dict[str, Any], suppressed_parent_ids: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    active: dict[str, Any] = {}
    suppressed: dict[str, Any] = {}
    for obj_id, assignment in l3_index.items():
        if not isinstance(assignment, dict):
            active[str(obj_id)] = assignment
            continue
        parent_id = str(assignment.get("parent_l3_id", "") or assignment.get("l3_id", "") or "")
        if parent_id in suppressed_parent_ids:
            suppressed[str(obj_id)] = assignment
        else:
            active[str(obj_id)] = assignment
    return active, suppressed


def load_effective_topic_surface(run_root: Path | str) -> dict[str, Any]:
    root = Path(run_root)
    raw_l2_view = _load_optional_json(root / "l2" / "l2_view.json", {"l2_nodes": []})
    raw_l2_index = _load_optional_json(root / "l2" / "l2_index.json", {})
    effective_l3_view_path = root / "l3" / "effective_l3_view.json"
    effective_l3_index_path = root / "l3" / "effective_l3_index.json"
    has_l3_child_review = effective_l3_view_path.exists() and effective_l3_index_path.exists()
    raw_l3_view = _load_optional_json(
        effective_l3_view_path if has_l3_child_review else root / "l3" / "l3_view.json",
        {"l3_parents": []},
    )
    raw_l3_index = _load_optional_json(
        effective_l3_index_path if has_l3_child_review else root / "l3" / "l3_index.json",
        {},
    )
    suppressed_l2_ids = _suppressed_l2_ids(root)
    suppressed_l2_set = set(suppressed_l2_ids)

    l2_view, suppressed_l2_nodes = _filter_l2_view(raw_l2_view, suppressed_l2_set)
    l2_index, suppressed_l2_index = _filter_l2_index(raw_l2_index, suppressed_l2_set)
    l3_view, suppressed_l3_parents, suppressed_parent_ids = _filter_l3_view(raw_l3_view, suppressed_l2_set)
    l3_index, suppressed_l3_index = _filter_l3_index(raw_l3_index, suppressed_parent_ids)

    return {
        "schema_version": 1,
        "run_root": str(root.resolve()),
        "source": "optimization_v2_effective_topic_surface",
        "has_topic_review": bool(suppressed_l2_ids),
        "has_l3_child_review": has_l3_child_review,
        "suppressed_l2_ids": suppressed_l2_ids,
        "suppressed_l3_parent_ids": sorted(suppressed_parent_ids),
        "l2_view": l2_view,
        "l2_index": l2_index,
        "l3_view": l3_view,
        "l3_index": l3_index,
        "suppressed_l2_nodes": suppressed_l2_nodes,
        "suppressed_l2_index": suppressed_l2_index,
        "suppressed_l3_parents": suppressed_l3_parents,
        "suppressed_l3_index": suppressed_l3_index,
        "active_l2_count": len(l2_view.get("l2_nodes", []) or []),
        "active_l2_index_count": len(l2_index),
        "suppressed_l2_count": len(suppressed_l2_ids),
        "suppressed_l2_index_count": len(suppressed_l2_index),
        "review_only_l3_child_count": sum(
            len(parent.get("review_only_child_l2_nodes", []) or [])
            for parent in l3_view.get("l3_parents", []) or []
            if isinstance(parent, dict)
        ),
    }
