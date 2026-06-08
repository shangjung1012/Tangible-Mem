from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text


_SUPPRESSIBLE_REVIEW_DISPOSITIONS = {"incoherent_no_durable_topic"}
_SUPPRESSIBLE_SKIPPED_SPLIT_REASONS = {"tiny_candidate_child", "no_separable_durable_topic"}


def _l2_nodes_by_id(run_root: Path) -> dict[str, dict[str, Any]]:
    l2_path = run_root / "l2" / "l2_view.json"
    if not l2_path.exists():
        return {}
    view = load_json(l2_path)
    return {
        str(node.get("l2_id", "") or ""): node
        for node in view.get("l2_nodes", []) or []
        if isinstance(node, dict) and str(node.get("l2_id", "") or "")
    }


def _linked_obj_ids(node: dict[str, Any] | None) -> list[str]:
    if not node:
        return []
    return [str(obj_id) for obj_id in node.get("linked_obj_ids", []) or [] if str(obj_id)]


def _decision(
    *,
    source_l2_id: str,
    node: dict[str, Any] | None,
    action: str,
    reason_codes: list[str],
    reason: str,
    source: str,
    representative_l1_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    linked_obj_ids = _linked_obj_ids(node)
    return {
        "source_l2_id": source_l2_id,
        "label": str((node or {}).get("label", "") or ""),
        "action": action,
        "reason_codes": reason_codes,
        "reason": reason,
        "source": source,
        "representative_l1_ids": representative_l1_ids or [],
        "linked_l1_count": len(linked_obj_ids),
        "linked_obj_ids": linked_obj_ids,
        **(extra or {}),
    }


def _llm_review_decisions(run_root: Path, l2_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    path = run_root / "l2" / "llm_split_review_proposals.json"
    if not path.exists():
        return []
    report = load_json(path)
    decisions: list[dict[str, Any]] = []
    for row in report.get("review_only", []) or []:
        if not isinstance(row, dict):
            continue
        source_l2_id = str(row.get("source_l2_id", "") or "")
        disposition = str(row.get("review_disposition", "") or "").strip().lower()
        if not source_l2_id or disposition not in _SUPPRESSIBLE_REVIEW_DISPOSITIONS:
            continue
        decisions.append(
            _decision(
                source_l2_id=source_l2_id,
                node=l2_by_id.get(source_l2_id),
                action="suppress_from_durable_l2",
                reason_codes=[disposition],
                reason=str(row.get("reason", "") or "LLM review judged this label not durable enough for L2."),
                source="llm_focused_split_review",
                representative_l1_ids=[
                    str(obj_id)
                    for obj_id in row.get("representative_l1_ids", []) or []
                    if str(obj_id)
                ],
            )
        )
    return decisions


def _skipped_split_decisions(run_root: Path, l2_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    path = run_root / "l3" / "applied_split_review_candidates.json"
    if not path.exists():
        return []
    report = load_json(path)
    decisions: list[dict[str, Any]] = []
    for row in report.get("skipped_splits", []) or []:
        if not isinstance(row, dict):
            continue
        source_l2_id = str(row.get("source_l2_id", "") or "")
        reason_code = str(row.get("reason", "") or "").strip()
        if not source_l2_id or reason_code not in _SUPPRESSIBLE_SKIPPED_SPLIT_REASONS:
            continue
        decisions.append(
            _decision(
                source_l2_id=source_l2_id,
                node=l2_by_id.get(source_l2_id),
                action="suppress_from_durable_l2",
                reason_codes=[reason_code, "split_rejected_as_non_durable"],
                reason=(
                    "Focused split review found no stable child topic that should be materialized as durable L2. "
                    "Raw L1 remains available as evidence."
                ),
                source="split_review_application_gate",
                extra={"child_sizes": row.get("child_sizes", []) or []},
            )
        )
    return decisions


def _dedupe_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    priority = {
        "llm_focused_split_review": 0,
        "split_review_application_gate": 1,
    }
    for row in decisions:
        source_l2_id = str(row.get("source_l2_id", "") or "")
        if not source_l2_id:
            continue
        current = deduped.get(source_l2_id)
        if current is None or priority.get(str(row.get("source", "")), 99) < priority.get(str(current.get("source", "")), 99):
            deduped[source_l2_id] = row
    return [deduped[key] for key in sorted(deduped)]


def _effective_topic_index(l2_by_id: dict[str, dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    suppressed_l2_ids = sorted(
        {
            str(row.get("source_l2_id", "") or "")
            for row in decisions
            if row.get("action") == "suppress_from_durable_l2"
        }
    )
    suppressed_l2_set = set(suppressed_l2_ids)
    active_l2_ids = sorted(l2_id for l2_id in l2_by_id if l2_id not in suppressed_l2_set)
    suppressed_l1_ids = sorted(
        {
            obj_id
            for l2_id in suppressed_l2_ids
            for obj_id in _linked_obj_ids(l2_by_id.get(l2_id))
        }
    )
    return {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "active_l2_count": len(active_l2_ids),
        "suppressed_l2_count": len(suppressed_l2_ids),
        "suppressed_l1_count": len(suppressed_l1_ids),
        "active_l2_ids": active_l2_ids,
        "suppressed_l2_ids": suppressed_l2_ids,
        "suppressed_l1_ids": suppressed_l1_ids,
        "note": "This is an effective durable-topic surface only. Raw L1 and raw L2 artifacts are not modified.",
    }


def finalize_topic_review(*, run_root: Path | str, out: Path | str | None = None) -> dict[str, Any]:
    root = Path(run_root)
    out_dir = ensure_optimization_output(Path(out) if out is not None else root / "topic_review")
    l2_by_id = _l2_nodes_by_id(root)
    decisions = _dedupe_decisions(
        [
            *_llm_review_decisions(root, l2_by_id),
            *_skipped_split_decisions(root, l2_by_id),
        ]
    )
    effective = _effective_topic_index(l2_by_id, decisions)
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "decision_count": len(decisions),
        "suppressed_l2_count": effective["suppressed_l2_count"],
        "suppressed_l1_count": effective["suppressed_l1_count"],
        "decisions": decisions,
    }
    decisions_payload = {
        "schema_version": 1,
        "generated_at_utc": report["generated_at_utc"],
        "run_root": report["run_root"],
        "decisions": decisions,
    }
    write_json(out_dir / "topic_review_decisions.json", decisions_payload)
    write_json(out_dir / "effective_topic_index.json", effective)
    write_json(out_dir / "topic_review_report.json", report)
    write_text(out_dir / "topic_review_report.md", _format_report_md(report))
    return report


def _format_report_md(report: dict[str, Any]) -> str:
    lines = [
        "# Topic Review Finalization",
        "",
        f"- decision count: {report.get('decision_count', 0)}",
        f"- suppressed durable L2 count: {report.get('suppressed_l2_count', 0)}",
        f"- affected L1 count: {report.get('suppressed_l1_count', 0)}",
        "",
        "Suppression only changes the effective durable-topic surface. Raw L1/L2 artifacts remain intact.",
        "",
        "## Decisions",
        "",
    ]
    for row in report.get("decisions", []) or []:
        lines.append(
            f"- `{row.get('source_l2_id')}` {row.get('label', '')}: "
            f"`{row.get('action')}` ({', '.join(row.get('reason_codes', []) or [])})"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize optimization v2 topic review into an effective durable-topic sidecar.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    report = finalize_topic_review(run_root=args.run_root, out=args.out or None)
    print(
        "[optimization:v2] topic review finalized: "
        f"decisions={report['decision_count']} suppressed_l2={report['suppressed_l2_count']} "
        f"suppressed_l1={report['suppressed_l1_count']}"
    )


if __name__ == "__main__":
    main()
