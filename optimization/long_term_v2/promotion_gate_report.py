from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _decision(value: dict[str, Any]) -> str:
    if "decision" in value:
        return str(value.get("decision") or "")
    summary = value.get("summary")
    if isinstance(summary, dict):
        return str(summary.get("decision") or "")
    return ""


def _answer_quality_passed(report: dict[str, Any]) -> bool:
    decision = _decision(report)
    status = str(report.get("status") or "")
    return decision == "answer_quality_pass" or status == "pass"


def decide_promotion_status(
    *,
    shadow_reports: list[dict[str, Any]],
    answer_quality_reports: list[dict[str, Any]],
    label_polish_report: dict[str, Any] | None,
    longer_icsi_report: dict[str, Any] | None,
    tests_passed: bool,
    scans_passed: bool,
    canonical_mutation: bool,
) -> dict[str, Any]:
    blocking: list[str] = []
    warnings: list[str] = []

    if not shadow_reports:
        blocking.append("missing_shadow_qa_report")
    for index, report in enumerate(shadow_reports, start=1):
        if _decision(report) != "shadow_qa_pass":
            blocking.append(f"shadow_qa_not_pass_{index}")

    if not answer_quality_reports:
        blocking.append("missing_answer_quality_report")
    elif not all(_answer_quality_passed(report) for report in answer_quality_reports):
        blocking.append("answer_quality_not_pass")

    if not label_polish_report:
        blocking.append("missing_label_polish_report")
    else:
        label_decision = _decision(label_polish_report)
        if label_decision == "label_polish_review_needed":
            warnings.append("label_polish_review_needed")
        elif label_decision not in {"label_polish_ready", "label_polish_review_needed", "label_polish_finalized"}:
            blocking.append("label_polish_report_invalid")

    if not longer_icsi_report:
        blocking.append("missing_longer_icsi_report")
    else:
        longer_decision = _decision(longer_icsi_report)
        accepted_blocked = longer_decision == "blocked_missing_input"
        if longer_decision not in {"longer_icsi_pass", "shadow_qa_pass"} and not accepted_blocked:
            blocking.append("longer_icsi_not_pass_or_accepted")
        if accepted_blocked:
            warnings.append("longer_scope_not_available")

    if not tests_passed:
        blocking.append("tests_not_passed")
    if not scans_passed:
        blocking.append("scans_not_passed")
    if canonical_mutation:
        blocking.append("canonical_mutation_detected")

    if blocking:
        decision = "do_not_promote"
    elif warnings:
        decision = "new_dataset_default_l2_l3"
    else:
        decision = "canonical_replacement_candidate"
    runtime_shadow_ready = not any(code.startswith("shadow_qa_not_pass") for code in blocking) and "missing_shadow_qa_report" not in blocking
    canonical_replacement_eligible = decision == "canonical_replacement_candidate"
    legacy_archive_allowed = canonical_replacement_eligible
    return {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "promotion_decision": decision,
        "runtime_shadow_ready": runtime_shadow_ready,
        "new_dataset_default_l2_l3": decision in {"new_dataset_default_l2_l3", "canonical_replacement_candidate"},
        "canonical_replacement_eligible": canonical_replacement_eligible,
        "legacy_archive_allowed": legacy_archive_allowed,
        "blocking_reasons": blocking,
        "warning_reasons": warnings,
        "gate_inputs": {
            "shadow_report_count": len(shadow_reports),
            "answer_quality_report_count": len(answer_quality_reports),
            "label_polish_decision": _decision(label_polish_report or {}),
            "longer_icsi_decision": _decision(longer_icsi_report or {}),
            "tests_passed": tests_passed,
            "scans_passed": scans_passed,
            "canonical_mutation": canonical_mutation,
        },
        "promotion_boundary": (
            "new_dataset_default_l2_l3 is allowed before canonical replacement. "
            "Canonical runtime replacement still requires explicit user approval."
        ),
    }


def build_promotion_gate_report(
    *,
    out: Path | str,
    shadow_report_paths: list[Path | str],
    answer_quality_paths: list[Path | str],
    label_polish_path: Path | str | None,
    longer_icsi_path: Path | str | None,
    tests_passed: bool,
    scans_passed: bool,
    canonical_mutation: bool,
) -> dict[str, Any]:
    out_root = ensure_optimization_output(out)
    shadow_reports = [load_json(path) for path in shadow_report_paths if Path(path).exists()]
    answer_reports = [load_json(path) for path in answer_quality_paths if Path(path).exists()]
    label_report = load_json(label_polish_path) if label_polish_path and Path(label_polish_path).exists() else None
    longer_report = load_json(longer_icsi_path) if longer_icsi_path and Path(longer_icsi_path).exists() else None
    report = decide_promotion_status(
        shadow_reports=shadow_reports,
        answer_quality_reports=answer_reports,
        label_polish_report=label_report,
        longer_icsi_report=longer_report,
        tests_passed=tests_passed,
        scans_passed=scans_passed,
        canonical_mutation=canonical_mutation,
    )
    report["input_paths"] = {
        "shadow_reports": [str(Path(path).resolve()) for path in shadow_report_paths],
        "answer_quality_reports": [str(Path(path).resolve()) for path in answer_quality_paths],
        "label_polish_report": str(Path(label_polish_path).resolve()) if label_polish_path else "",
        "longer_icsi_report": str(Path(longer_icsi_path).resolve()) if longer_icsi_path else "",
    }
    write_json(out_root / "summary.json", report)
    write_text(out_root / "summary.md", _format_markdown(report))
    return report


def _format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Optimization V2 Promotion Gate Report",
        "",
        f"- promotion decision: `{report.get('promotion_decision')}`",
        f"- new dataset default L2/L3: `{report.get('new_dataset_default_l2_l3')}`",
        f"- runtime shadow ready: `{report.get('runtime_shadow_ready')}`",
        f"- canonical replacement eligible: `{report.get('canonical_replacement_eligible')}`",
        f"- legacy archive allowed: `{report.get('legacy_archive_allowed')}`",
        f"- blocking reasons: {', '.join(report.get('blocking_reasons', [])) or 'none'}",
        f"- warning reasons: {', '.join(report.get('warning_reasons', [])) or 'none'}",
        "",
        "## Gate Inputs",
        "",
    ]
    for key, value in (report.get("gate_inputs") or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- `new_dataset_default_l2_l3` means v2 can be the default L2/L3 pipeline for new datasets.",
            "- `canonical_replacement_eligible` remains false until longer-scope validation and explicit user approval.",
            "- `legacy_archive_allowed` remains false until canonical replacement is eligible.",
            "- Canonical runtime remains unchanged until explicit user approval.",
            "- Rollback remains config-only because this report does not move generated artifacts.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate optimization v2 promotion gates.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--shadow-report", action="append", default=[])
    parser.add_argument("--answer-quality-report", action="append", default=[])
    parser.add_argument("--label-polish-report", default=None)
    parser.add_argument("--longer-icsi-report", default=None)
    parser.add_argument("--tests-passed", action="store_true")
    parser.add_argument("--scans-passed", action="store_true")
    parser.add_argument("--canonical-mutation", action="store_true")
    args = parser.parse_args()
    report = build_promotion_gate_report(
        out=args.out,
        shadow_report_paths=args.shadow_report,
        answer_quality_paths=args.answer_quality_report,
        label_polish_path=args.label_polish_report,
        longer_icsi_path=args.longer_icsi_report,
        tests_passed=args.tests_passed,
        scans_passed=args.scans_passed,
        canonical_mutation=args.canonical_mutation,
    )
    print(f"[optimization:v2] promotion gate report complete: decision={report['promotion_decision']}")


if __name__ == "__main__":
    main()
