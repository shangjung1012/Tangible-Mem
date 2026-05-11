"""Deterministic current-implementation context for retrieval prompts.

Meeting L1 evidence is immutable history. This module adds a small repo-state
layer for questions that explicitly ask about the current implementation, so
old meeting discussions do not override the active handoff.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CURRENT_STATE_QUERY_TERMS = (
    "現在",
    "目前",
    "當前",
    "current",
    "implementation",
    "implemented",
    "repo",
    "active",
    "canonical",
    "實作",
    "實現",
    "狀態",
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def should_include_current_state_context(query: str) -> bool:
    text = str(query or "").lower()
    if any(term.lower() in text for term in CURRENT_STATE_QUERY_TERMS):
        return True
    # L1/L2/L3 architecture questions are usually asking about the active
    # implementation contract even when the locale text is unavailable or
    # degraded by a Windows console encoding path.
    layer_terms = {"l1", "l2", "l3"}
    return len({term for term in layer_terms if term in text}) >= 2


def _count_l3_children(l3_view: dict[str, Any]) -> int:
    total = 0
    for node in l3_view.get("l3_nodes", []) or []:
        if isinstance(node, dict):
            children = node.get("child_l2_nodes", [])
            if isinstance(children, list):
                total += len(children)
    return total


def _json_metric(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return str(value)
    return "unknown"


def build_current_state_context(repo_root: Path | str) -> str:
    root = Path(repo_root)
    share_manifest = _load_json(root / "share_mem" / "manifest.json")
    l2_manifest = _load_json(root / "long_term" / "l2" / "manifest.json")
    l3_view = _load_json(root / "long_term" / "l3" / "l3_view.json")
    eval_report = _load_json(root / "long_term" / "eval" / "retrieval_eval_report.json")

    l3_count = len(l3_view.get("l3_nodes", []) or [])
    child_l2_count = _count_l3_children(l3_view)
    budget_profile = eval_report.get("budget_profile") or "unknown"

    lines = [
        "=== Current Implementation State ===",
        "This section describes the current repo implementation / canonical handoff.",
        "For current-state questions, use this section over older meeting discussion when they conflict.",
        "- L1 source: share_mem/tree.json and share_mem/meetings/*.json are immutable meeting evidence.",
        (
            "- L2 active view: long_term/l2/l2_view.json and long_term/l2/l2_index.json. "
            "The active L2 grouping is topic-based over immutable L1 objects, not four-meeting temporal batching "
            "and not one meeting per L2."
        ),
        (
            "- L3 promotion: long_term/l3/l3_view.json and long_term/l3/l3_index.json are sidecars that promote "
            "oversized L2 topic families and materialize child L2 nodes."
        ),
        (
            "- Retrieval: evidence-first layered retrieval starts from L1 seeds, then expands to relevant "
            "L2 / child-L2 / L3 navigation context."
        ),
        (
            "- Current counts: "
            f"meetings={_json_metric(share_manifest, 'meeting_count')}, "
            f"L1_objects={_json_metric(share_manifest, 'object_count')}, "
            f"L2_topics={_json_metric(l2_manifest, 'l2_count', 'topic_count', 'l2_topic_count')}, "
            f"linked_L1={_json_metric(l2_manifest, 'linked_l1_count')}, "
            f"L3_families={l3_count}, child_L2={child_l2_count}, "
            f"retrieval_budget_profile={budget_profile}."
        ),
    ]
    return "\n".join(lines)


def current_state_context_for_query(query: str, repo_root: Path | str) -> str:
    if not should_include_current_state_context(query):
        return ""
    return build_current_state_context(repo_root)
