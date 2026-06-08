from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.effective_view import load_effective_topic_surface
from optimization.long_term_v2.io_utils import utc_now_iso, write_json, write_text
from share_mem.store import build_l1_index, load_share_tree


ALLOWED_DECISIONS = [
    "correct",
    "too_broad",
    "too_fragmented",
    "wrong_assignment",
    "generic_bucket",
    "should_suppress",
    "needs_l3_split",
]


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _obj_preview(obj_id: str, l1_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    obj = l1_index.get(str(obj_id), {})
    return {
        "obj_id": str(obj_id),
        "meeting_id": obj.get("meeting_id", ""),
        "meeting_date": obj.get("meeting_date", ""),
        "type": obj.get("type", ""),
        "importance": _safe_float(obj.get("importance")),
        "content": str(obj.get("content", "") or "")[:360],
        "evidence": str(obj.get("evidence", "") or "")[:420],
    }


def _linked_obj_ids(node: dict[str, Any]) -> list[str]:
    ids = [str(obj_id) for obj_id in node.get("linked_obj_ids", []) or [] if str(obj_id)]
    if ids:
        return ids
    return [
        str(event.get("obj_id", "") or "")
        for event in node.get("timeline_digest", []) or []
        if isinstance(event, dict) and str(event.get("obj_id", "") or "")
    ]


def _meeting_spread(node: dict[str, Any], l1_index: dict[str, dict[str, Any]]) -> int:
    meetings = {
        str(l1_index.get(obj_id, {}).get("meeting_id", "") or "")
        for obj_id in _linked_obj_ids(node)
    }
    return len({meeting for meeting in meetings if meeting})


def _topic_row(node: dict[str, Any], l1_index: dict[str, dict[str, Any]], *, sample_limit: int = 5) -> dict[str, Any]:
    obj_ids = _linked_obj_ids(node)
    return {
        "l2_id": str(node.get("l2_id", "") or ""),
        "label": str(node.get("label", "") or ""),
        "linked_l1_count": len(obj_ids),
        "meeting_spread": _meeting_spread(node, l1_index),
        "current_state": str(node.get("current_state", "") or "")[:500],
        "evolution_summary": str(node.get("evolution_summary", "") or "")[:700],
        "representative_l1": [_obj_preview(obj_id, l1_index) for obj_id in obj_ids[:sample_limit]],
    }


def _suppressed_topic_rows(surface: dict[str, Any], l1_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [_topic_row(node, l1_index) for node in surface.get("suppressed_l2_nodes", []) or [] if isinstance(node, dict)]
    rows.sort(key=lambda row: (-row["linked_l1_count"], row["l2_id"]))
    return rows


def _random_linked_l1(surface: dict[str, Any], l1_index: dict[str, dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    linked = sorted(str(obj_id) for obj_id in surface.get("l2_index", {}))
    rng = random.Random(20260609)
    rng.shuffle(linked)
    return [_obj_preview(obj_id, l1_index) for obj_id in linked[:limit]]


def _high_importance_l1(surface: dict[str, Any], l1_index: dict[str, dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    linked = [
        obj_id
        for obj_id in surface.get("l2_index", {})
        if _safe_float(l1_index.get(str(obj_id), {}).get("importance")) >= 0.7
    ]
    linked.sort(key=lambda obj_id: (-_safe_float(l1_index.get(str(obj_id), {}).get("importance")), str(obj_id)))
    return [_obj_preview(obj_id, l1_index) for obj_id in linked[:limit]]


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# Active L2 Manual Review Queue",
        "",
        f"- generated at: `{report['generated_at_utc']}`",
        f"- active L2 reviewed: `{len(report['top_largest_active_l2'])}`",
        f"- suppressed L2 listed: `{len(report['suppressed_l2'])}`",
        "",
        "Allowed decisions: " + ", ".join(f"`{value}`" for value in report["review_schema"]["allowed_decisions"]),
        "",
        "## Top Largest Active L2",
        "",
    ]
    for row in report["top_largest_active_l2"]:
        lines.append(f"### `{row['l2_id']}` {row['label']}")
        lines.append(f"- linked L1: `{row['linked_l1_count']}`")
        lines.append(f"- meeting spread: `{row['meeting_spread']}`")
        lines.append("- representative L1:")
        for obj in row["representative_l1"][:5]:
            lines.append(f"  - `{obj['obj_id']}` {obj['meeting_id']}: {obj['content']}")
        lines.append("")
    lines.append("## Suppressed L2")
    lines.append("")
    for row in report["suppressed_l2"]:
        lines.append(f"- `{row['l2_id']}` {row['label']} ({row['linked_l1_count']} L1)")
    lines.append("")
    lines.append("## High-Importance L1 Sample")
    lines.append("")
    for obj in report["high_importance_l1_sample"]:
        lines.append(f"- `{obj['obj_id']}` {obj['meeting_id']} importance={obj['importance']}: {obj['content']}")
    return "\n".join(lines).rstrip() + "\n"


def build_active_l2_manual_review(
    *,
    run_root: Path | str,
    share_mem_root: Path | str,
    out: Path | str,
    top_l2_limit: int = 20,
    random_l1_limit: int = 20,
    high_importance_limit: int = 20,
) -> dict[str, Any]:
    root = Path(run_root)
    out_dir = Path(out)
    l1_index = build_l1_index(load_share_tree(share_mem_root))
    surface = load_effective_topic_surface(root)
    active_nodes = [node for node in surface["l2_view"].get("l2_nodes", []) or [] if isinstance(node, dict)]
    active_nodes.sort(
        key=lambda node: (
            -len(_linked_obj_ids(node)),
            -_meeting_spread(node, l1_index),
            str(node.get("label", "") or ""),
        )
    )
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "share_mem_root": str(Path(share_mem_root).resolve()),
        "effective_topic_surface": {
            "active_l2_count": surface["active_l2_count"],
            "suppressed_l2_count": surface["suppressed_l2_count"],
            "suppressed_l2_index_count": surface["suppressed_l2_index_count"],
        },
        "review_schema": {
            "allowed_decisions": ALLOWED_DECISIONS,
            "decision_format": {
                "item_id": "L2 id or obj_id",
                "decision": "one allowed decision",
                "severity": "none|warning|severe",
                "reason": "human-readable review reason",
            },
        },
        "top_largest_active_l2": [
            _topic_row(node, l1_index)
            for node in active_nodes[:top_l2_limit]
        ],
        "suppressed_l2": _suppressed_topic_rows(surface, l1_index),
        "random_linked_l1": _random_linked_l1(surface, l1_index, limit=random_l1_limit),
        "high_importance_l1_sample": _high_importance_l1(surface, l1_index, limit=high_importance_limit),
    }
    write_json(out_dir / "active_l2_manual_review.json", report)
    write_text(out_dir / "active_l2_manual_review.md", _format_md(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a standardized manual review queue for optimization v2 active L2 topics.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--share-mem-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--top-l2-limit", type=int, default=20)
    parser.add_argument("--random-l1-limit", type=int, default=20)
    parser.add_argument("--high-importance-limit", type=int, default=20)
    args = parser.parse_args()
    report = build_active_l2_manual_review(
        run_root=args.run_root,
        share_mem_root=args.share_mem_root,
        out=args.out,
        top_l2_limit=args.top_l2_limit,
        random_l1_limit=args.random_l1_limit,
        high_importance_limit=args.high_importance_limit,
    )
    print(
        "[optimization:v2] active L2 manual review queue complete: "
        f"active_review={len(report['top_largest_active_l2'])} "
        f"suppressed={len(report['suppressed_l2'])}"
    )


if __name__ == "__main__":
    main()
