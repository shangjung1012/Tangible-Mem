from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text


ALLOWED_DECISIONS = {
    "correct",
    "correct_suppressed",
    "needs_label_review",
    "too_broad_watch",
    "should_suppress",
    "needs_l3_split",
    "needs_manual_decision",
}
ALLOWED_SEVERITIES = {"none", "warning", "severe"}
ALLOWED_ITEM_TYPES = {"active_l2", "suppressed_l2"}
REQUIRED_FIELDS = {
    "review_id",
    "item_type",
    "item_id",
    "decision",
    "severity",
    "reason",
    "reviewer",
    "created_at_utc",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        row["_line_no"] = line_no
        rows.append(row)
    return rows


def _review_item_ids(review: dict[str, Any]) -> dict[str, set[str]]:
    active = {
        str(row.get("l2_id", "") or "")
        for row in review.get("top_largest_active_l2", []) or []
        if isinstance(row, dict) and str(row.get("l2_id", "") or "")
    }
    suppressed = {
        str(row.get("l2_id", "") or "")
        for row in review.get("suppressed_l2", []) or []
        if isinstance(row, dict) and str(row.get("l2_id", "") or "")
    }
    return {"active_l2": active, "suppressed_l2": suppressed}


def _validate_decision(row: dict[str, Any], item_ids: dict[str, set[str]]) -> tuple[list[str], bool]:
    errors: list[str] = []
    for field in sorted(REQUIRED_FIELDS):
        if not str(row.get(field, "") or "").strip():
            errors.append(f"missing_{field}")
    item_type = str(row.get("item_type", "") or "")
    item_id = str(row.get("item_id", "") or "")
    if item_type not in ALLOWED_ITEM_TYPES:
        errors.append("invalid_item_type")
    if str(row.get("decision", "") or "") not in ALLOWED_DECISIONS:
        errors.append("invalid_decision")
    if str(row.get("severity", "") or "") not in ALLOWED_SEVERITIES:
        errors.append("invalid_severity")
    known = item_type in item_ids and item_id in item_ids[item_type]
    if item_type in ALLOWED_ITEM_TYPES and not known:
        errors.append("unknown_item_id")
    return errors, known


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# Active L2 Review Decisions Summary",
        "",
        f"- status: `{report['status']}`",
        f"- generated at: `{report['generated_at_utc']}`",
        f"- review source: `{report['review_path']}`",
        f"- decisions source: `{report['decisions_path']}`",
        f"- decision count: `{report['decision_count']}`",
        f"- warning issues: `{report['warning_issue_count']}`",
        f"- severe issues: `{report['severe_issue_count']}`",
        f"- validation errors: `{report['validation_error_count']}`",
        f"- unknown items: `{report['unknown_item_count']}`",
        "",
        "This report is a sidecar review summary. It does not mutate raw L1, active L2/L3, or canonical artifacts.",
        "",
        "## Decisions By Type",
        "",
    ]
    for decision, count in sorted(report["by_decision"].items()):
        lines.append(f"- `{decision}`: `{count}`")
    lines.extend(["", "## Review Decisions", ""])
    for row in report["decisions"]:
        lines.append(
            f"- `{row.get('item_id')}` ({row.get('item_type')}): "
            f"`{row.get('decision')}` / `{row.get('severity')}` - {row.get('reason')}"
        )
    if report["validation_errors"]:
        lines.extend(["", "## Validation Errors", ""])
        for error in report["validation_errors"]:
            lines.append(f"- line `{error.get('line_no')}` `{error.get('review_id')}`: {', '.join(error.get('errors', []))}")
    return "\n".join(lines).rstrip() + "\n"


def finalize_active_l2_review(
    *,
    review_path: Path | str,
    decisions_path: Path | str,
    out: Path | str,
) -> dict[str, Any]:
    review_file = Path(review_path)
    decisions_file = Path(decisions_path)
    out_dir = Path(out)
    review = load_json(review_file)
    decisions = _load_jsonl(decisions_file)
    item_ids = _review_item_ids(review)

    validation_errors: list[dict[str, Any]] = []
    known_item_decision_count = 0
    for row in decisions:
        errors, known = _validate_decision(row, item_ids)
        if known:
            known_item_decision_count += 1
        if errors:
            validation_errors.append(
                {
                    "review_id": row.get("review_id"),
                    "line_no": row.get("_line_no"),
                    "item_type": row.get("item_type"),
                    "item_id": row.get("item_id"),
                    "errors": errors,
                }
            )

    warning_issues = [row for row in decisions if row.get("severity") == "warning"]
    severe_issues = [row for row in decisions if row.get("severity") == "severe"]
    by_decision = dict(Counter(str(row.get("decision", "") or "") for row in decisions))
    by_item_type = dict(Counter(str(row.get("item_type", "") or "") for row in decisions))
    reviewed_active_l2_ids = {
        str(row.get("item_id", "") or "")
        for row in decisions
        if str(row.get("item_type", "") or "") == "active_l2"
    }
    missing_top_l2_decisions = sorted(item_ids["active_l2"] - reviewed_active_l2_ids)
    unknown_item_count = sum(1 for error in validation_errors if "unknown_item_id" in error["errors"])

    status = "pass"
    if validation_errors or severe_issues:
        status = "fail"
    elif not decisions or warning_issues or missing_top_l2_decisions:
        status = "warning"

    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "review_path": str(review_file),
        "decisions_path": str(decisions_file),
        "decision_count": len(decisions),
        "known_item_decision_count": known_item_decision_count,
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors,
        "warning_issue_count": len(warning_issues),
        "severe_issue_count": len(severe_issues),
        "unknown_item_count": unknown_item_count,
        "missing_top_l2_decision_count": len(missing_top_l2_decisions),
        "missing_top_l2_decisions": missing_top_l2_decisions,
        "active_l2_review_item_count": len(item_ids["active_l2"]),
        "suppressed_l2_review_item_count": len(item_ids["suppressed_l2"]),
        "by_decision": by_decision,
        "by_item_type": by_item_type,
        "allowed_decisions": sorted(ALLOWED_DECISIONS),
        "allowed_severities": sorted(ALLOWED_SEVERITIES),
        "decisions": decisions,
    }
    write_json(out_dir / "active_l2_review_decisions_summary.json", report)
    write_text(out_dir / "active_l2_review_decisions_summary.md", _format_md(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize active L2 review decisions for an optimization v2 run.")
    parser.add_argument("--review", required=True, help="Path to active_l2_manual_review.json")
    parser.add_argument("--decisions", required=True, help="Path to JSONL review decisions")
    parser.add_argument("--out", required=True, help="Output directory for summary JSON/Markdown")
    args = parser.parse_args()
    report = finalize_active_l2_review(review_path=args.review, decisions_path=args.decisions, out=args.out)
    print(f"[optimization:v2] active L2 review finalized: status={report['status']} decisions={report['decision_count']}")


if __name__ == "__main__":
    main()
