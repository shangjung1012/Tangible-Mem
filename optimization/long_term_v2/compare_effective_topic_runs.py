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


def _load_optional(path: Path, default: Any) -> Any:
    return load_json(path) if path.exists() else default


def _l2_labels(run_root: Path) -> dict[str, str]:
    surface = load_effective_topic_surface(run_root)
    return {
        str(node.get("l2_id", "") or ""): str(node.get("label", "") or "")
        for node in surface["l2_view"].get("l2_nodes", []) or []
        if isinstance(node, dict) and str(node.get("l2_id", "") or "")
    }


def _metrics(run_root: Path) -> dict[str, Any]:
    manifest = _load_optional(run_root / "manifest.json", {})
    surface = load_effective_topic_surface(run_root)
    retrieval = _load_optional(run_root / "retrieval_eval_icsi_effective" / "retrieval_eval_report.json", {"summary": {}})
    validation = _load_optional(run_root / "validation" / "l2_validation_report.json", {})
    return {
        "run_root": str(run_root.resolve()),
        "source_l1_count": int(manifest.get("source_l1_count", 0) or 0),
        "linked_l1_count": int(manifest.get("linked_l1_count", 0) or 0),
        "active_l2_count": surface["active_l2_count"],
        "suppressed_l2_count": surface["suppressed_l2_count"],
        "l3_parent_count": len(surface["l3_view"].get("l3_parents", []) or []),
        "l3_assigned_l1_count": len(surface["l3_index"]),
        "validation_severe_count": int(validation.get("severe_count", 0) or 0),
        "validation_warning_count": int(validation.get("warning_count", 0) or 0),
        "retrieval_summary": retrieval.get("summary", {}) or {},
    }


def _metric_delta(base: dict[str, Any], cand: dict[str, Any], key: str) -> float:
    try:
        return round(float(cand.get(key, 0.0) or 0.0) - float(base.get(key, 0.0) or 0.0), 4)
    except (TypeError, ValueError):
        return 0.0


def compare_effective_topic_runs(*, baseline: Path | str, candidate: Path | str, out: Path | str | None = None) -> dict[str, Any]:
    baseline_root = Path(baseline)
    candidate_root = Path(candidate)
    base_metrics = _metrics(baseline_root)
    candidate_metrics = _metrics(candidate_root)
    base_labels = _l2_labels(baseline_root)
    candidate_labels = _l2_labels(candidate_root)
    changed_labels = [
        {"l2_id": l2_id, "baseline_label": label, "candidate_label": candidate_labels[l2_id]}
        for l2_id, label in sorted(base_labels.items())
        if l2_id in candidate_labels and candidate_labels[l2_id] != label
    ]
    base_retrieval = base_metrics["retrieval_summary"]
    candidate_retrieval = candidate_metrics["retrieval_summary"]
    retrieval_deltas = {
        key: _metric_delta(base_retrieval, candidate_retrieval, key)
        for key in sorted(set(base_retrieval) | set(candidate_retrieval))
        if isinstance(base_retrieval.get(key, candidate_retrieval.get(key)), (int, float))
        or isinstance(candidate_retrieval.get(key), (int, float))
    }
    regressions: list[str] = []
    if candidate_metrics["validation_severe_count"] > base_metrics["validation_severe_count"]:
        regressions.append("more_validation_severe_issues")
    for key in ("avg_expected_obj_recall_at_context", "expected_l2_semantic_hit_rate", "expected_l3_semantic_hit_rate"):
        if retrieval_deltas.get(key, 0.0) < -0.0001:
            regressions.append(f"retrieval_regressed_{key}")
    decision = "candidate_kept_isolated" if not regressions else "candidate_rejected"
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "baseline": base_metrics,
        "candidate": candidate_metrics,
        "changed_label_count": len(changed_labels),
        "changed_labels": changed_labels,
        "retrieval_metric_deltas": retrieval_deltas,
        "regressions": regressions,
        "decision": decision,
    }
    if out is not None:
        out_dir = Path(out)
        write_json(out_dir / "effective_topic_run_comparison.json", report)
        write_text(out_dir / "effective_topic_run_comparison.md", _format_md(report))
    return report


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# Effective Topic Run Comparison",
        "",
        f"- decision: `{report['decision']}`",
        f"- changed labels: `{report['changed_label_count']}`",
        f"- regressions: {', '.join(report['regressions']) or '`none`'}",
        "",
        "## Retrieval Metric Deltas",
        "",
    ]
    for key, value in report["retrieval_metric_deltas"].items():
        lines.append(f"- `{key}`: `{value}`")
    if report["changed_labels"]:
        lines.extend(["", "## Changed Labels", ""])
        for row in report["changed_labels"]:
            lines.append(f"- `{row['l2_id']}`: `{row['baseline_label']}` -> `{row['candidate_label']}`")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare an optimization v2 baseline run and candidate run.")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = compare_effective_topic_runs(baseline=args.baseline, candidate=args.candidate, out=args.out)
    print(f"[optimization:v2] effective topic comparison complete: decision={report['decision']}")


if __name__ == "__main__":
    main()
