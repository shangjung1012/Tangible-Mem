from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.effective_view import load_effective_topic_surface
from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text
from share_mem.store import build_l1_index, load_share_tree


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compare_with_baseline(
    *,
    run_root: Path | str,
    baseline_l2_root: Path | str,
    baseline_l3_root: Path | str,
    share_mem_root: Path | str = "share_mem",
    high_importance_threshold: float = 0.7,
) -> dict[str, Any]:
    root = Path(run_root)
    baseline_l2_index_path = Path(baseline_l2_root) / "l2_index.json"
    baseline_l3_index_path = Path(baseline_l3_root) / "l3_index.json"
    baseline_l2_index = load_json(baseline_l2_index_path) if baseline_l2_index_path.exists() else {}
    baseline_l3_index = load_json(baseline_l3_index_path) if baseline_l3_index_path.exists() else {}
    effective_surface = load_effective_topic_surface(root)
    v2_l2_index = effective_surface["l2_index"]
    v2_l3_index = effective_surface["l3_index"]
    l1_index = build_l1_index(load_share_tree(share_mem_root))
    high_ids = {
        obj_id
        for obj_id, row in l1_index.items()
        if _safe_float(row.get("importance")) >= high_importance_threshold
    }
    baseline_high_linked = high_ids & set(baseline_l2_index)
    v2_high_linked = high_ids & set(v2_l2_index)
    changed_high = [
        {
            "obj_id": obj_id,
            "baseline": baseline_l2_index.get(obj_id),
            "v2": v2_l2_index.get(obj_id),
            "content": l1_index.get(obj_id, {}).get("content", "")[:240],
        }
        for obj_id in sorted(high_ids)
        if (obj_id in baseline_l2_index) != (obj_id in v2_l2_index)
    ]
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "baseline_l2_count": len(set(row.get("l2_id", "") for row in baseline_l2_index.values() if isinstance(row, dict))),
        "v2_l2_count": len(set(row.get("l2_id", "") for row in v2_l2_index.values() if isinstance(row, dict))),
        "baseline_l3_assigned_l1": len(baseline_l3_index),
        "v2_l3_assigned_l1": len(v2_l3_index),
        "effective_topic_surface": {
            "has_topic_review": effective_surface["has_topic_review"],
            "suppressed_l2_count": effective_surface["suppressed_l2_count"],
            "suppressed_l2_index_count": effective_surface["suppressed_l2_index_count"],
        },
        "high_importance_l1_count": len(high_ids),
        "baseline_high_importance_linked_rate": round(len(baseline_high_linked) / max(len(high_ids), 1), 4),
        "v2_high_importance_linked_rate": round(len(v2_high_linked) / max(len(high_ids), 1), 4),
        "changed_high_importance_l1_count": len(changed_high),
        "changed_high_importance_l1": changed_high,
        "manual_regression_queue": changed_high,
    }
    out = root / "comparison"
    write_json(out / "baseline_vs_v2_l2.json", report)
    write_json(out / "baseline_vs_v2_retrieval.json", {"note": "retrieval comparison is produced by evaluate_retrieval.py"})
    write_json(out / "changed_high_importance_l1.json", changed_high)
    write_json(out / "manual_regression_queue.json", {"items": changed_high})
    write_text(
        out / "baseline_vs_v2_l2.md",
        "\n".join(
            [
                "# Baseline vs Optimization v2 L2",
                "",
                f"- baseline L2 count: {report['baseline_l2_count']}",
                f"- v2 L2 count: {report['v2_l2_count']}",
                f"- baseline high-importance linked rate: {report['baseline_high_importance_linked_rate']}",
                f"- v2 high-importance linked rate: {report['v2_high_importance_linked_rate']}",
                f"- changed high-importance L1: {report['changed_high_importance_l1_count']}",
                "",
            ]
        ),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare optimization v2 L2/L3 outputs with active baseline.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--baseline-l2-root", required=True)
    parser.add_argument("--baseline-l3-root", required=True)
    parser.add_argument("--share-mem-root", default="share_mem")
    args = parser.parse_args()
    report = compare_with_baseline(
        run_root=args.run_root,
        baseline_l2_root=args.baseline_l2_root,
        baseline_l3_root=args.baseline_l3_root,
        share_mem_root=args.share_mem_root,
    )
    print(
        "[optimization:v2] comparison complete: "
        f"v2_high_linked={report['v2_high_importance_linked_rate']}"
    )


if __name__ == "__main__":
    main()
