from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text


ALLOWED_DECISIONS = {
    "correct",
    "too_broad",
    "too_fragmented",
    "wrong_assignment",
    "generic_bucket",
    "unsupported_label",
    "should_unlink_noise",
    "needs_l3_split",
    "needs_merge_review",
}
ALLOWED_SEVERITIES = {"none", "warning", "severe"}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        row["_line_no"] = line_no
        rows.append(row)
    return rows


def _validate_decision(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("review_id", "item_type", "item_id", "decision", "severity", "reason", "reviewer", "created_at_utc"):
        if not str(row.get(field, "") or "").strip():
            errors.append(f"missing_{field}")
    if str(row.get("decision", "")) not in ALLOWED_DECISIONS:
        errors.append("invalid_decision")
    if str(row.get("severity", "")) not in ALLOWED_SEVERITIES:
        errors.append("invalid_severity")
    return errors


def finalize_manual_review(*, run_root: Path | str, decisions_path: Path | str | None = None) -> dict[str, Any]:
    root = ensure_optimization_output(run_root)
    review_dir = root / "manual_review"
    protocol_path = review_dir / "manual_review_protocol.json"
    protocol = load_json(protocol_path) if protocol_path.exists() else {}
    source = Path(decisions_path) if decisions_path else review_dir / "review_decisions.jsonl"
    decisions = _load_jsonl(source)
    validation_errors: list[dict[str, Any]] = []
    for row in decisions:
        errors = _validate_decision(row)
        if errors:
            validation_errors.append({"review_id": row.get("review_id"), "line_no": row.get("_line_no"), "errors": errors})
    severe = [row for row in decisions if row.get("severity") == "severe"]
    warnings = [row for row in decisions if row.get("severity") == "warning"]
    wrong_assignment = [row for row in decisions if row.get("decision") == "wrong_assignment"]
    generic_bucket = [row for row in decisions if row.get("decision") == "generic_bucket"]
    unsupported = [row for row in decisions if row.get("decision") == "unsupported_label"]
    reviewed = max(len(decisions), 1)
    wrong_assignment_rate = round(len(wrong_assignment) / reviewed, 4)
    unlinked_high = (
        protocol.get("high_importance_unlinked_l1_sample", [])
        or protocol.get("unlinked_l1_sample", [])
        or []
    )
    unlinked_reviewed = {
        str(row.get("item_id"))
        for row in decisions
        if str(row.get("item_type", "")) in {"unlinked_l1", "l1_object"}
    }
    missing_high_unlinked = [
        row.get("obj_id")
        for row in unlinked_high
        if str(row.get("obj_id")) not in unlinked_reviewed
    ]
    status = "pass"
    if validation_errors or severe or wrong_assignment_rate > 0.05 or generic_bucket or unsupported or missing_high_unlinked:
        status = "fail"
    if not decisions:
        status = "warning"
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "protocol_path": str(protocol_path),
        "decisions_path": str(source),
        "status": status,
        "decision_count": len(decisions),
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors,
        "severe_issue_count": len(severe),
        "warning_issue_count": len(warnings),
        "wrong_assignment_count": len(wrong_assignment),
        "wrong_assignment_rate": wrong_assignment_rate,
        "generic_bucket_count": len(generic_bucket),
        "unsupported_label_count": len(unsupported),
        "missing_high_importance_unlinked_review_count": len(missing_high_unlinked),
        "missing_high_importance_unlinked_reviews": missing_high_unlinked,
        "decisions": decisions,
    }
    write_json(review_dir / "final_manual_review_report.json", report)
    lines = [
        "# Optimization v2 Final Manual Review Report",
        "",
        f"- status: `{status}`",
        f"- decisions: {len(decisions)}",
        f"- severe issues: {len(severe)}",
        f"- wrong assignment rate: {wrong_assignment_rate}",
        f"- generic buckets: {len(generic_bucket)}",
        f"- unsupported labels: {len(unsupported)}",
        "",
    ]
    write_text(review_dir / "final_manual_review_report.md", "\n".join(lines))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize a human manual review for an optimization v2 run.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--decisions")
    args = parser.parse_args()
    report = finalize_manual_review(run_root=args.run_root, decisions_path=args.decisions)
    print(f"[optimization:v2] manual review finalized: status={report['status']}")


if __name__ == "__main__":
    main()
