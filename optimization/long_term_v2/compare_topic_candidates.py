from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text


def _load_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return load_json(path)


def _topic_quality_issues(run_root: Path) -> list[dict[str, Any]]:
    report = _load_optional_json(run_root / "topic_quality" / "topic_quality_report.json", {"issues": []})
    return [issue for issue in report.get("issues", []) or [] if isinstance(issue, dict)]


def _validation_issues(run_root: Path) -> list[dict[str, Any]]:
    report = _load_optional_json(run_root / "validation" / "l2_validation_report.json", {"issues": []})
    return [issue for issue in report.get("issues", []) or [] if isinstance(issue, dict)]


def _unlinked_objects(run_root: Path) -> list[dict[str, Any]]:
    report = _load_optional_json(run_root / "l2" / "unlinked_l1_report.json", {"unlinked_objects": []})
    return [row for row in report.get("unlinked_objects", []) or [] if isinstance(row, dict)]


def _merge_reviews(run_root: Path) -> list[dict[str, Any]]:
    report = _load_optional_json(run_root / "l3" / "l2_merge_review.json", {"merge_reviews": []})
    return [row for row in report.get("merge_reviews", []) or [] if isinstance(row, dict)]


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _run_metrics(run_root: Path) -> dict[str, Any]:
    manifest = _load_optional_json(run_root / "manifest.json", {})
    quality_issues = _topic_quality_issues(run_root)
    validation_issues = _validation_issues(run_root)
    unlinked = _unlinked_objects(run_root)
    merge_reviews = _merge_reviews(run_root)
    broad_count = sum(1 for issue in quality_issues if issue.get("code") == "broad_l2_mixed_signatures")
    function_word_label_count = sum(
        1
        for issue in quality_issues + validation_issues
        if str(issue.get("code", "")).endswith("_label") or str(issue.get("code", "")).endswith("_child_l2_label")
    )
    explained_review_only = sum(1 for row in unlinked if str(row.get("reason", "") or "").strip())
    unexplained_high = sum(
        1
        for row in unlinked
        if _safe_float(row.get("importance")) >= 0.7 and not str(row.get("reason", "") or "").strip()
    )
    weak_l3_materialized = sum(
        1
        for row in merge_reviews
        if row.get("action") == "needs_merge_review" and "too_few_l1_nodes" in (row.get("reason_codes", []) or [])
    )
    needs_split_review = sum(1 for row in merge_reviews if row.get("action") == "needs_split_review")
    score = 0.0
    score -= broad_count * 2.0
    score -= function_word_label_count * 5.0
    score -= weak_l3_materialized * 3.0
    score += needs_split_review * 1.0
    score += explained_review_only * 0.5
    score -= unexplained_high * 5.0
    return {
        "run_root": str(run_root.resolve()),
        "score": round(score, 3),
        "l1_count": int(manifest.get("source_l1_count", 0) or 0),
        "l2_topic_count": int(manifest.get("l2_topic_count", 0) or 0),
        "l3_parent_count": int(manifest.get("l3_parent_count", 0) or 0),
        "broad_l2_review_count": broad_count,
        "function_word_label_count": function_word_label_count,
        "explained_review_only_l1_count": explained_review_only,
        "unexplained_high_importance_unlinked_count": unexplained_high,
        "weak_l3_materialized_count": weak_l3_materialized,
        "needs_split_review_count": needs_split_review,
    }


def _compare_rows(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    improvements: list[str] = []
    regressions: list[str] = []
    if candidate["broad_l2_review_count"] < baseline["broad_l2_review_count"]:
        improvements.append("reduced_broad_topic_risk")
    if candidate["explained_review_only_l1_count"] > baseline["explained_review_only_l1_count"]:
        improvements.append("review_only_l1_has_reason")
    if candidate["weak_l3_materialized_count"] < baseline["weak_l3_materialized_count"]:
        improvements.append("reduced_weak_l3_materialization")
    if candidate["unexplained_high_importance_unlinked_count"]:
        regressions.append("unexplained_high_importance_unlinked")
    if candidate["function_word_label_count"] > baseline["function_word_label_count"]:
        regressions.append("more_function_word_or_generic_labels")
    if candidate["broad_l2_review_count"] > baseline["broad_l2_review_count"]:
        regressions.append("increased_broad_topic_risk")
    return {
        **candidate,
        "score_delta": round(candidate["score"] - baseline["score"], 3),
        "improvements": improvements,
        "regressions": regressions,
    }


def compare_topic_candidates(
    *,
    baseline_run_root: Path | str,
    candidate_run_roots: list[Path | str],
    out: Path | str | None = None,
) -> dict[str, Any]:
    baseline_root = Path(baseline_run_root)
    baseline = _run_metrics(baseline_root)
    candidates = [
        _compare_rows(baseline, _run_metrics(Path(candidate_root)))
        for candidate_root in candidate_run_roots
    ]
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "baseline": baseline,
        "candidates": candidates,
        "decision": "review_required",
    }
    if out is not None:
        out_dir = ensure_optimization_output(out)
        write_json(out_dir / "candidate_comparison.json", report)
        lines = [
            "# Topic Candidate Comparison",
            "",
            f"- baseline score: {baseline['score']}",
            f"- candidates: {len(candidates)}",
            "",
            "| Candidate | Score Delta | Improvements | Regressions |",
            "|---|---:|---|---|",
        ]
        for row in candidates:
            lines.append(
                "| {name} | {delta} | {improvements} | {regressions} |".format(
                    name=Path(row["run_root"]).name,
                    delta=row["score_delta"],
                    improvements=", ".join(row["improvements"]) or "-",
                    regressions=", ".join(row["regressions"]) or "-",
                )
            )
        write_text(out_dir / "candidate_comparison.md", "\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare optimization v2 topic candidate runs.")
    parser.add_argument("--baseline-run-root", required=True)
    parser.add_argument("--candidate-run-root", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = compare_topic_candidates(
        baseline_run_root=args.baseline_run_root,
        candidate_run_roots=args.candidate_run_root,
        out=args.out,
    )
    print(f"[optimization:v2] compared {len(report['candidates'])} candidate run(s): out={args.out}")


if __name__ == "__main__":
    main()
