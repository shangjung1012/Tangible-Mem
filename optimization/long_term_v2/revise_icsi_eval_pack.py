from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, utc_now_iso, write_json, write_text


REVISION_OVERRIDES: dict[str, dict[str, Any]] = {
    "icsi-heldout-q002": {
        "query_type": "evidence_lookup",
        "query": "What source-side evidence did the BMR meetings contain about disk space constraints and storage decisions?",
    },
    "icsi-heldout-q003": {
        "query_type": "decision_rationale",
        "query": "What source-side rationale was discussed for microphone signal processing and beamforming choices?",
    },
    "icsi-heldout-q005": {
        "query_type": "evidence_lookup",
        "query": "Which source-side annotation tool candidates, including Mississippi State tools and XWaves, had been considered for the BMR transcription workflow?",
        "remove_expected_obj_ids": ["L1-Bmr002-114"],
    },
    "icsi-heldout-q006": {
        "query_type": "evidence_lookup",
        "query": "What source-side evidence discussed acoustic model training data and digit-reading automation?",
        "remove_expected_obj_ids": ["L1-Bmr002-239"],
    },
    "icsi-heldout-q008": {
        "query_type": "next_meeting_carryover",
        "query": "What meeting agenda items were deferred or carried forward in the source-side BMR meetings?",
    },
    "icsi-heldout-q010": {
        "query_type": "evidence_lookup",
        "query": "What source-side evidence established far-field microphone data as an important project goal?",
    },
    "icsi-heldout-q012": {
        "query_type": "evidence_lookup",
        "query": "What source-side evidence discussed digital audio file handling, file size, and transcription tooling?",
    },
}


def _load_jsonl(path: Path | str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path | str, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _remove_ids(row: dict[str, Any], remove_ids: set[str]) -> dict[str, Any]:
    output = copy.deepcopy(row)
    for key in ("expected_obj_ids", "expected_source_obj_ids"):
        output[key] = [obj_id for obj_id in output.get(key, []) or [] if obj_id not in remove_ids]
    output["source_evidence_preview"] = [
        preview
        for preview in output.get("source_evidence_preview", []) or []
        if str(preview.get("obj_id", "")) not in remove_ids
    ]
    remaining_meetings = sorted({obj_id.split("-")[1] for obj_id in output.get("expected_obj_ids", []) or [] if obj_id.startswith("L1-")})
    if remaining_meetings:
        output["answer_from_meetings"] = remaining_meetings
    return output


def _format_report_md(report: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Revised ICSI Held-Out Eval Pack",
        "",
        "This pack applies the agent pre-review decisions to the original held-out future-meeting questions.",
        "It remains a dry-run evaluation pack: held-out triggers are used only to justify question relevance, not as answer evidence.",
        "",
        "## Summary",
        "",
        f"- total queries: `{report['total_query_count']}`",
        f"- accepted unchanged: `{report['accepted_unchanged_count']}`",
        f"- revised: `{report['revised_count']}`",
        f"- removed expected L1 ids: `{report['removed_expected_obj_ids']}`",
        f"- status: `{report['status']}`",
        "",
        "## Revised Questions",
        "",
    ]
    for row in rows:
        revision = row.get("revision", {}) or {}
        marker = "revised" if revision.get("decision") == "revise" else "accepted"
        lines.extend(
            [
                f"### {row['query_id']} `{row.get('query_type', '')}`",
                "",
                f"- status: `{marker}`",
                f"- query: {row.get('query', '')}",
                f"- expected L1: `{', '.join(row.get('expected_obj_ids', []) or [])}`",
                f"- expected L2 labels: `{', '.join(row.get('expected_l2_labels', []) or [])}`",
                f"- expected L3 labels: `{', '.join(row.get('expected_l3_labels', []) or [])}`",
                "",
            ]
        )
        if revision.get("reason"):
            lines.append(f"- review reason: {revision['reason']}")
            lines.append("")
    return "\n".join(lines)


def revise_icsi_eval_pack(
    *,
    source_pack: Path | str,
    decisions_path: Path | str,
    out_dir: Path | str,
) -> dict[str, Any]:
    out = ensure_optimization_output(out_dir)
    source_rows = _load_jsonl(source_pack)
    decisions = {str(row.get("query_id", "")): row for row in _load_jsonl(decisions_path)}
    revised_rows: list[dict[str, Any]] = []
    revision_rows: list[dict[str, Any]] = []
    removed: dict[str, list[str]] = {}
    accepted_count = 0
    revised_count = 0

    for source_row in source_rows:
        query_id = str(source_row.get("query_id", ""))
        decision = decisions.get(query_id, {})
        decision_type = str(decision.get("decision", "") or "").lower()
        row = copy.deepcopy(source_row)
        original_query = row.get("query", "")
        original_query_type = row.get("query_type", "")
        if decision_type == "accept":
            accepted_count += 1
            row["status"] = "agent_pre_review_accepted"
        elif decision_type == "revise":
            revised_count += 1
            override = REVISION_OVERRIDES.get(query_id, {})
            if override.get("query"):
                row["query"] = str(override["query"])
            elif decision.get("recommended_query"):
                row["query"] = str(decision["recommended_query"])
            if override.get("query_type"):
                row["query_type"] = str(override["query_type"])
            remove_ids = set(override.get("remove_expected_obj_ids", []) or [])
            if remove_ids:
                row = _remove_ids(row, remove_ids)
                removed[query_id] = sorted(remove_ids)
            row["status"] = "agent_revised_for_dry_run"
        else:
            row["status"] = "agent_pre_review_unclassified"

        row["provenance"] = {
            **(row.get("provenance", {}) or {}),
            "revision_pack": "icsi_bmr_full_completed29_revised_heldout_eval",
            "manual_review_required": True,
        }
        row["revision"] = {
            "decision": decision_type or "missing",
            "severity": decision.get("severity", ""),
            "reason": decision.get("reason", ""),
            "original_query": original_query,
            "original_query_type": original_query_type,
            "recommended_query": decision.get("recommended_query", ""),
            "applied_query": row.get("query", ""),
            "applied_query_type": row.get("query_type", ""),
            "removed_expected_obj_ids": removed.get(query_id, []),
        }
        revised_rows.append(row)
        revision_rows.append(
            {
                "query_id": query_id,
                "decision": row["revision"]["decision"],
                "original_query": original_query,
                "applied_query": row.get("query", ""),
                "original_query_type": original_query_type,
                "applied_query_type": row.get("query_type", ""),
                "removed_expected_obj_ids": removed.get(query_id, []),
                "status": row["status"],
            }
        )

    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": "agent_revised_dry_run_pack_human_review_required",
        "source_pack": str(Path(source_pack).resolve()),
        "decisions_path": str(Path(decisions_path).resolve()),
        "revised_queries_path": str((out / "revised_heldout_eval_queries.jsonl").resolve()),
        "approved_revised_queries_path": str((out / "approved_revised_heldout_eval_queries.jsonl").resolve()),
        "total_query_count": len(revised_rows),
        "accepted_unchanged_count": accepted_count,
        "revised_count": revised_count,
        "removed_expected_obj_ids": removed,
        "query_type_counts": {
            query_type: sum(row.get("query_type") == query_type for row in revised_rows)
            for query_type in sorted({str(row.get("query_type", "")) for row in revised_rows})
        },
        "notes": [
            "Held-out trigger objects remain excluded from expected answer evidence.",
            "This pack is agent-revised for no-LLM dry runs and still needs final human approval before professor-facing scoring.",
        ],
    }
    _write_jsonl(out / "revised_heldout_eval_queries.jsonl", revised_rows)
    _write_jsonl(out / "approved_revised_heldout_eval_queries.jsonl", revised_rows)
    _write_jsonl(out / "revision_decisions.jsonl", revision_rows)
    write_json(out / "revised_eval_pack_report.json", report)
    write_text(out / "revised_eval_pack.md", _format_report_md(report, revised_rows))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply pre-review revisions to an ICSI held-out eval pack.")
    parser.add_argument("--source-pack", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = revise_icsi_eval_pack(
        source_pack=args.source_pack,
        decisions_path=args.decisions,
        out_dir=args.out,
    )
    print(
        "[optimization:v2] revised ICSI eval pack complete: "
        f"queries={report['total_query_count']} revised={report['revised_count']}"
    )


if __name__ == "__main__":
    main()
