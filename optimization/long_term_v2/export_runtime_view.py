from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.effective_view import load_effective_topic_surface
from optimization.long_term_v2.io_utils import load_json, tree_hash, utc_now_iso, write_json


RUNTIME_SCHEMA = "canonical_recall_v1"


def _copy_json_if_exists(source: Path, target: Path, fallback: Any) -> Any:
    if source.exists():
        payload = load_json(source)
    else:
        payload = fallback
    write_json(target, payload)
    return payload


def _runtime_child_l2(child: dict[str, Any], *, promoted_from_l2_id: str) -> dict[str, Any]:
    child_id = str(child.get("l2_id") or child.get("child_l2_id") or "").strip()
    return {
        **child,
        "l2_id": child_id,
        "child_l2_id": child_id,
        "source": child.get("source", "optimization_v2_runtime_child_l2"),
        "promoted_from_l2_id": promoted_from_l2_id,
    }


def _runtime_l3_node(parent: dict[str, Any]) -> dict[str, Any]:
    promoted_from_l2_id = str(
        parent.get("promoted_from_l2_id") or parent.get("source_l2_id") or ""
    ).strip()
    children = [
        _runtime_child_l2(child, promoted_from_l2_id=promoted_from_l2_id)
        for child in parent.get("child_l2_nodes", [])
        if isinstance(child, dict)
    ]
    return {
        "l3_id": str(parent.get("l3_id", "") or ""),
        "label": str(parent.get("label", "") or ""),
        "source": "optimization_v2_runtime_export",
        "promoted_from_l2_id": promoted_from_l2_id,
        "reason_codes": parent.get("reason_codes", []),
        "metrics": parent.get("metrics", {}),
        "child_l2_nodes": children,
    }


def _convert_l3_view(v2_l3_view: dict[str, Any]) -> dict[str, Any]:
    if isinstance(v2_l3_view.get("l3_nodes"), list):
        return {
            **v2_l3_view,
            "runtime_schema": RUNTIME_SCHEMA,
        }
    parents = [
        parent
        for parent in v2_l3_view.get("l3_parents", [])
        if isinstance(parent, dict)
    ]
    nodes = [_runtime_l3_node(parent) for parent in parents]
    return {
        "schema_version": 1,
        "runtime_schema": RUNTIME_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "source": "optimization_v2_runtime_export",
        "materialized_l3_count": len(nodes),
        "l3_nodes": nodes,
    }


def _convert_l3_index(v2_l3_index: dict[str, Any]) -> dict[str, Any]:
    runtime: dict[str, Any] = {}
    for obj_id, assignment in v2_l3_index.items():
        if not isinstance(assignment, dict):
            continue
        l3_id = str(
            assignment.get("l3_id") or assignment.get("parent_l3_id") or ""
        ).strip()
        if not l3_id:
            continue
        runtime[str(obj_id)] = {
            **assignment,
            "l3_id": l3_id,
            "parent_l3_id": str(assignment.get("parent_l3_id") or l3_id),
            "child_l2_id": str(assignment.get("child_l2_id", "") or ""),
        }
    return runtime


def _convert_l3_promotions(v2_l3_view: dict[str, Any]) -> dict[str, Any]:
    parents = v2_l3_view.get("l3_parents", [])
    if not isinstance(parents, list):
        parents = []
    promotions = []
    for parent in parents:
        if not isinstance(parent, dict):
            continue
        children = []
        for child in parent.get("child_l2_nodes", []) or []:
            if not isinstance(child, dict):
                continue
            child_id = str(child.get("child_l2_id") or child.get("l2_id") or "")
            if not child_id:
                continue
            children.append(
                {
                    "child_l2_id": child_id,
                    "label": str(child.get("label", "") or ""),
                    "split_reason": str(child.get("split_reason", "") or ""),
                }
            )
        promotions.append(
            {
                "proposed_l3_id": str(parent.get("l3_id", "") or ""),
                "status": "materialized_runtime_export",
                "source_l2_id": str(
                    parent.get("source_l2_id") or parent.get("promoted_from_l2_id") or ""
                ),
                "child_l2_candidates": children,
                "mapping": {},
            }
        )
    return {
        "schema_version": 1,
        "runtime_schema": RUNTIME_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "source": "optimization_v2_runtime_export",
        "promotions": promotions,
    }


def export_runtime_view(run_root: Path | str, *, clean: bool = False) -> dict[str, Any]:
    root = Path(run_root)
    runtime_root = root / "runtime"
    if clean and runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)

    tree = _copy_json_if_exists(
        root / "input_snapshot" / "tree.json",
        runtime_root / "input_snapshot" / "tree.json",
        {"meetings": []},
    )
    effective_surface = load_effective_topic_surface(root)
    l2_view = effective_surface["l2_view"]
    l2_index = effective_surface["l2_index"]
    write_json(runtime_root / "l2" / "l2_view.json", l2_view)
    write_json(runtime_root / "l2" / "l2_index.json", l2_index)
    if (root / "topic_review" / "effective_topic_index.json").exists():
        _copy_json_if_exists(
            root / "topic_review" / "effective_topic_index.json",
            runtime_root / "topic_review" / "effective_topic_index.json",
            {},
        )
    _copy_json_if_exists(
        root / "l2" / "l2_secondary_links.json",
        runtime_root / "l2" / "l2_secondary_links.json",
        {"schema_version": 1, "links": []},
    )

    v2_l3_view = effective_surface["l3_view"]
    v2_l3_index = effective_surface["l3_index"]
    runtime_l3_view = _convert_l3_view(v2_l3_view if isinstance(v2_l3_view, dict) else {})
    runtime_l3_index = _convert_l3_index(v2_l3_index if isinstance(v2_l3_index, dict) else {})
    runtime_l3_promotions = _convert_l3_promotions(v2_l3_view if isinstance(v2_l3_view, dict) else {})
    write_json(runtime_root / "l3" / "l3_view.json", runtime_l3_view)
    write_json(runtime_root / "l3" / "l3_index.json", runtime_l3_index)
    write_json(runtime_root / "l3" / "l3_promotions.json", runtime_l3_promotions)

    manifest = {
        "schema_version": 1,
        "runtime_schema": RUNTIME_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "source": "optimization_v2_runtime_export",
        "source_run_root": str(root.resolve()),
        "runtime_root": str(runtime_root.resolve()),
        "source_tree_hash": tree_hash(tree) if isinstance(tree, dict) else "",
        "l2_topic_count": len(l2_view.get("l2_nodes", [])) if isinstance(l2_view, dict) else 0,
        "l2_index_count": len(l2_index) if isinstance(l2_index, dict) else 0,
        "l3_parent_count": len(runtime_l3_view.get("l3_nodes", [])),
        "l3_index_count": len(runtime_l3_index),
        "effective_topic_surface": {
            "has_topic_review": effective_surface["has_topic_review"],
            "has_corpus_theme_l3": effective_surface.get("has_corpus_theme_l3", False),
            "has_l3_child_review": effective_surface.get("has_l3_child_review", False),
            "l3_surface_source": effective_surface.get("l3_surface_source", "raw_l3"),
            "suppressed_l2_count": effective_surface["suppressed_l2_count"],
            "suppressed_l2_index_count": effective_surface["suppressed_l2_index_count"],
        },
        "canonical_mutation": False,
    }
    write_json(runtime_root / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export an isolated optimization v2 run into canonical recall-compatible runtime sidecars."
    )
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    manifest = export_runtime_view(args.run_root, clean=args.clean)
    print(
        "[optimization:v2] runtime export complete: "
        f"l2={manifest['l2_topic_count']} l3={manifest['l3_parent_count']} "
        f"runtime={manifest['runtime_root']}"
    )


if __name__ == "__main__":
    main()
