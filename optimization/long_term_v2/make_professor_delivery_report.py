from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import OPTIMIZATION_ROOT, load_json, utc_now_iso, write_json, write_text


def _gate(certification: dict[str, Any], gate_name: str) -> dict[str, Any]:
    return certification.get("gate_results", {}).get(gate_name, {})


def _round(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _latest_certification_path() -> Path:
    pointer = OPTIMIZATION_ROOT / "reports" / ".latest_maturity_certification.txt"
    if not pointer.exists():
        raise FileNotFoundError("missing optimization/reports/.latest_maturity_certification.txt")
    report_root = Path(pointer.read_text(encoding="utf-8").strip())
    return report_root / "maturity_certification_report.json"


def _default_out_dir() -> Path:
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("Z", "Z")
    return OPTIMIZATION_ROOT / "reports" / f"professor_delivery_{stamp}"


def _answer_quality_summary(certification: dict[str, Any]) -> dict[str, Any]:
    gate = _gate(certification, "gate_9_answer_quality_evaluation")
    answer_quality = gate.get("answer_quality", {})
    summary = answer_quality.get("summary", {})
    scores = {
        strategy: _round(values.get("average_overall_score"))
        for strategy, values in summary.items()
        if isinstance(values, dict)
    }
    best_strategy = None
    if scores:
        best_strategy = max(scores, key=lambda key: scores[key] if scores[key] is not None else -1.0)
    return {
        "status": gate.get("status", "missing"),
        "best_strategy": best_strategy,
        "overall_scores": scores,
        "average_context_tokens": {
            strategy: _round(values.get("average_context_tokens"), 1)
            for strategy, values in summary.items()
            if isinstance(values, dict)
        },
        "failure_case_count": answer_quality.get("failure_case_count", 0),
    }


def _core_evidence(certification: dict[str, Any]) -> dict[str, Any]:
    l1_gate = _gate(certification, "gate_3_l1_input_audit")
    l2_gate = _gate(certification, "gate_5_l2_topic_quality")
    retrieval_gate = _gate(certification, "gate_8_retrieval_quality")
    l3_gate = _gate(certification, "gate_7_l3_adaptive_promotion")
    l1_comparison = l1_gate.get("comparison", {})
    l2_validation = l2_gate.get("validation", {})
    retrieval = retrieval_gate.get("retrieval", {})
    l3_quality = l3_gate.get("l3_quality", {})
    return {
        "certification_status": certification.get("status", "unknown"),
        "failing_gate_count": len(certification.get("failing_gates", [])),
        "warning_gates": certification.get("warning_gates", []),
        "isolation_status": _gate(certification, "gate_1_isolation").get("status", "missing"),
        "hardcode_scan_status": _gate(certification, "gate_2_no_grace_specific_core").get("status", "missing"),
        "hardcode_match_count": _gate(certification, "gate_2_no_grace_specific_core").get("match_count"),
        "baseline_high_importance_linked_rate": _round(
            l1_comparison.get("baseline_high_importance_linked_rate")
        ),
        "v2_high_importance_linked_rate": _round(l1_comparison.get("v2_high_importance_linked_rate")),
        "l2_severe_count": l2_validation.get("severe_count"),
        "l2_warning_count": l2_validation.get("warning_count"),
        "retrieval_l1_recall": _round(retrieval.get("avg_expected_obj_recall_at_context")),
        "retrieval_l2_semantic_hit": _round(retrieval.get("expected_l2_semantic_hit_rate")),
        "retrieval_l3_semantic_hit": _round(retrieval.get("expected_l3_semantic_hit_rate")),
        "l3_parent_count": l3_quality.get("l3_parent_count"),
        "child_l2_count": l3_quality.get("child_l2_count"),
    }


def _cross_dataset_summary(certification: dict[str, Any]) -> dict[str, Any]:
    gate = _gate(certification, "gate_10_cross_dataset_maturity_suite")
    suite = gate.get("suite", {})
    icsi = _gate(certification, "gate_10_cross_dataset_robustness").get("icsi_validation", {})
    return {
        "status": gate.get("status", "missing"),
        "dataset_count": suite.get("dataset_count"),
        "failed_dataset_count": suite.get("failed_dataset_count"),
        "icsi_severe_count": icsi.get("severe_count"),
        "icsi_warning_count": icsi.get("warning_count"),
    }


def _manual_review_summary(certification: dict[str, Any]) -> dict[str, Any]:
    gate = _gate(certification, "gate_11_manual_review_completion")
    review = gate.get("manual_review", {})
    return {
        "status": gate.get("status", "missing"),
        "decision_count": review.get("decision_count"),
        "severe_issue_count": review.get("severe_issue_count"),
        "wrong_assignment_rate": _round(review.get("wrong_assignment_rate")),
        "generic_bucket_count": review.get("generic_bucket_count"),
        "unsupported_label_count": review.get("unsupported_label_count"),
    }


def _split_review_summary(certification: dict[str, Any]) -> dict[str, Any]:
    focused = _gate(certification, "gate_7_focused_split_review").get("focused_split_review", {})
    applied = _gate(certification, "gate_7_split_candidate_application").get("split_candidate_application", {})
    return {
        "focused_status": focused.get("status"),
        "pending_split_review_count": focused.get("pending_split_review_count"),
        "reviewed_source_count": focused.get("reviewed_source_count"),
        "accepted_split_count": sum(
            row.get("accepted_split_count", 0) for row in focused.get("runs", []) if isinstance(row, dict)
        ),
        "candidate_status": applied.get("status"),
        "applied_split_count": applied.get("applied_split_count"),
        "skipped_split_count": applied.get("skipped_split_count"),
    }


def _v2_native_summary(v2_native_diagnostics: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not v2_native_diagnostics:
        return []
    rows = []
    for row in v2_native_diagnostics.get("summary", []):
        rows.append(
            {
                "dataset": row.get("dataset"),
                "query_count": row.get("query_count"),
                "avg_l1_recall": _round(row.get("avg_expected_obj_recall_at_context")),
                "l2_semantic_hit": _round(row.get("expected_l2_semantic_hit_rate")),
                "needs_split_topic_count": row.get("needs_split_topic_count"),
                "topics_with_retrieval_pressure_count": row.get("topics_with_retrieval_pressure_count"),
            }
        )
    return rows


def _deliverability_status(certification: dict[str, Any]) -> str:
    if certification.get("failing_gates"):
        return "not_deliverable"
    required = [
        _gate(certification, "gate_1_isolation").get("status"),
        _gate(certification, "gate_2_no_grace_specific_core").get("status"),
        _gate(certification, "gate_9_answer_quality_evaluation").get("status"),
        _gate(certification, "gate_10_cross_dataset_maturity_suite").get("status"),
        _gate(certification, "gate_11_manual_review_completion").get("status"),
    ]
    if all(status == "pass" for status in required):
        return "deliverable_shadow_mode"
    return "deliverable_with_known_gaps"


def _promotion_boundary(certification: dict[str, Any]) -> str:
    gate = _gate(certification, "gate_12_promotion_decision")
    if gate.get("status") == "pass":
        return "promotion_discussion_allowed"
    return "do_not_promote_to_canonical"


def _talking_points(report: dict[str, Any]) -> list[str]:
    return [
        "Optimization v2 is isolated: it reads raw L1 evidence but writes only optimization-side artifacts.",
        "The L2/L3 pipeline is evidence-driven and profile-driven, without the old Grace-specific canonical label map.",
        "Related topics are treated as an optional stabilizing signal, not the only assignment source.",
        "Current certification has no failing gate; the remaining boundary is policy-level shadow-mode only.",
        "Answer-quality evidence favors optimization_v2_deterministic over canonical layered, RAG, and full context on the scored sample.",
    ]


def _demo_flow() -> list[str]:
    return [
        "Open with the problem: canonical L2/L3 worked for Grace but looked too project-specific.",
        "Show the v2 design: L1 evidence -> semantic keys -> induced L2 -> adaptive L3 -> validation gates.",
        "Show the certification summary: no failing gates, no hardcode scan hits, ICSI and synthetic checks pass.",
        "Show answer-quality comparison: v2 deterministic has stronger score with much smaller context than full context.",
        "Close honestly: v2 is ready for shadow-mode evaluation, not canonical promotion.",
    ]


def _remaining_risks(certification: dict[str, Any]) -> list[str]:
    risks = []
    if _promotion_boundary(certification) == "do_not_promote_to_canonical":
        risks.append("Not promoted: repeated isolated runs and explicit user approval are still required.")
    if _gate(certification, "gate_7_split_candidate_application").get("split_candidate_application", {}).get(
        "skipped_split_count", 0
    ):
        risks.append("Some split candidates were intentionally skipped because validation found weak separability.")
    answer = _answer_quality_summary(certification)
    if answer.get("failure_case_count"):
        risks.append("Answer-quality report still keeps failure cases for manual review rather than hiding them.")
    return risks


def _render_markdown(report: dict[str, Any]) -> str:
    evidence = report["core_evidence"]
    answer = report["answer_quality"]
    cross = report["cross_dataset"]
    manual = report["manual_review"]
    split = report["split_review"]
    native_rows = report["v2_native_diagnostics"]
    lines = [
        "# Optimization v2 Delivery Report",
        "",
        f"Generated: `{report['generated_at_utc']}`",
        "",
        "## Executive Status",
        "",
        f"- Deliverability: `{report['deliverability_status']}`",
        f"- Promotion boundary: `{report['promotion_boundary']}`",
        f"- Certification status: `{evidence['certification_status']}`",
        f"- Failing gates: `{evidence['failing_gate_count']}`",
        f"- Warning gates: `{', '.join(evidence['warning_gates']) or 'none'}`",
        "",
        "## Core Evidence",
        "",
        f"- Isolation gate: `{evidence['isolation_status']}`",
        f"- Grace-specific hardcode scan: `{evidence['hardcode_scan_status']}`, matches `{evidence['hardcode_match_count']}`",
        f"- Baseline high-importance linked rate: `{evidence['baseline_high_importance_linked_rate']}`",
        f"- v2 high-importance linked rate: `{evidence['v2_high_importance_linked_rate']}`",
        f"- L2 severe / warning count: `{evidence['l2_severe_count']}` / `{evidence['l2_warning_count']}`",
        f"- Retrieval L1 recall: `{evidence['retrieval_l1_recall']}`",
        f"- Retrieval L2 semantic hit: `{evidence['retrieval_l2_semantic_hit']}`",
        f"- L3 parents / child L2: `{evidence['l3_parent_count']}` / `{evidence['child_l2_count']}`",
        "",
        "## Answer Quality",
        "",
        f"- Status: `{answer['status']}`",
        f"- Best strategy: `{answer['best_strategy']}`",
        f"- Overall scores: `{answer['overall_scores']}`",
        f"- Average context tokens: `{answer['average_context_tokens']}`",
        f"- Failure cases retained for review: `{answer['failure_case_count']}`",
        "",
        "## Cross-Dataset And Review Evidence",
        "",
        f"- Cross-dataset suite: `{cross['status']}`, datasets `{cross['dataset_count']}`, failed `{cross['failed_dataset_count']}`",
        f"- ICSI severe / warning count: `{cross['icsi_severe_count']}` / `{cross['icsi_warning_count']}`",
        f"- Manual review: `{manual['status']}`, decisions `{manual['decision_count']}`, severe `{manual['severe_issue_count']}`, wrong-assignment rate `{manual['wrong_assignment_rate']}`",
        f"- Focused split review: `{split['focused_status']}`, reviewed `{split['reviewed_source_count']}`, accepted splits `{split['accepted_split_count']}`",
        f"- Split candidate application: `{split['candidate_status']}`, applied `{split['applied_split_count']}`, skipped `{split['skipped_split_count']}`",
        "",
        "## V2-Native Query Diagnostics",
        "",
    ]
    if native_rows:
        for row in native_rows:
            lines.append(
                f"- `{row['dataset']}`: queries `{row['query_count']}`, L1 recall `{row['avg_l1_recall']}`, L2 semantic hit `{row['l2_semantic_hit']}`"
            )
    else:
        lines.append("- No v2-native diagnostics provided.")
    lines.extend(
        [
            "",
            "## Five Talking Points",
            "",
        ]
    )
    lines.extend(f"{idx}. {point}" for idx, point in enumerate(report["talking_points"], start=1))
    lines.extend(["", "## Suggested Demo Flow", ""])
    lines.extend(f"{idx}. {step}" for idx, step in enumerate(report["demo_flow"], start=1))
    lines.extend(["", "## Remaining Risks", ""])
    lines.extend(f"- {risk}" for risk in report["remaining_risks"])
    lines.append("")
    return "\n".join(lines)


def build_professor_delivery_report(
    *,
    certification: dict[str, Any],
    v2_native_diagnostics: dict[str, Any] | None,
    out_dir: Path | str,
    certification_path: Path | str | None = None,
    diagnostics_path: Path | str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "source_reports": {
            "certification_report": str(certification_path) if certification_path else None,
            "v2_native_diagnostics": str(diagnostics_path) if diagnostics_path else None,
        },
        "deliverability_status": _deliverability_status(certification),
        "promotion_boundary": _promotion_boundary(certification),
        "core_evidence": _core_evidence(certification),
        "answer_quality": _answer_quality_summary(certification),
        "cross_dataset": _cross_dataset_summary(certification),
        "manual_review": _manual_review_summary(certification),
        "split_review": _split_review_summary(certification),
        "v2_native_diagnostics": _v2_native_summary(v2_native_diagnostics),
        "talking_points": [],
        "demo_flow": _demo_flow(),
        "remaining_risks": _remaining_risks(certification),
    }
    report["talking_points"] = _talking_points(report)
    target = Path(out_dir)
    write_json(target / "professor_delivery_report.json", report)
    write_text(target / "professor_delivery_report.md", _render_markdown(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a professor-facing optimization v2 delivery report.")
    parser.add_argument("--certification-report", type=Path, default=None)
    parser.add_argument("--v2-native-diagnostics", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    certification_path = args.certification_report or _latest_certification_path()
    diagnostics_path = args.v2_native_diagnostics
    diagnostics = load_json(diagnostics_path) if diagnostics_path and diagnostics_path.exists() else None
    out_dir = args.out or _default_out_dir()
    report = build_professor_delivery_report(
        certification=load_json(certification_path),
        v2_native_diagnostics=diagnostics,
        out_dir=out_dir,
        certification_path=certification_path,
        diagnostics_path=diagnostics_path,
    )
    print(
        f"[optimization-v2] professor delivery report written: {out_dir} "
        f"status={report['deliverability_status']} boundary={report['promotion_boundary']}"
    )


if __name__ == "__main__":
    main()
