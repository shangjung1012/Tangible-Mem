from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.audit_topic_quality import audit_topic_quality
from optimization.long_term_v2.build_view import build_view
from optimization.long_term_v2.curate_v2_native_queries import curate_v2_native_queries
from optimization.long_term_v2.evaluate_retrieval import evaluate_retrieval
from optimization.long_term_v2.validate_view import validate_run
from share_mem.store import refresh_share_mem_outputs


ICSI_BMR_ABSENT_IDS = {"Bmr004", "Bmr017"}
ICSI_BMR_EXPECTED_FULL_IDS = [
    f"Bmr{idx:03d}"
    for idx in range(1, 32)
    if f"Bmr{idx:03d}" not in ICSI_BMR_ABSENT_IDS
]

DEFAULT_EXCLUDE_RUN_NAME_MARKERS = {
    "first360",
    "first240",
    "dryrun",
    "debug",
    "probe",
    "completed_l2l3",
    "eval_probe",
    "archive_import",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run_name_is_excluded(run_root: Path, *, exclude_markers: set[str]) -> str:
    lowered = run_root.name.lower()
    for marker in sorted(exclude_markers):
        if marker and marker.lower() in lowered:
            return marker
    return ""


def _latest_status_by_meeting(batch_status_path: Path) -> dict[str, str]:
    if not batch_status_path.exists():
        return {}
    payload = _read_json(batch_status_path)
    statuses: dict[str, str] = {}
    for row in payload.get("runs", []) or []:
        if not isinstance(row, dict):
            continue
        meeting_id = str(row.get("meeting_id", "") or "").strip()
        status = str(row.get("status", "") or "").strip().lower()
        if meeting_id and status:
            statuses[meeting_id] = status
    return statuses


def _load_meetings_by_id(filtered_root: Path) -> dict[str, dict[str, Any]]:
    tree_path = filtered_root / "tree.json"
    if not tree_path.exists():
        raise FileNotFoundError(f"Missing filtered share_mem tree: {tree_path}")
    tree = _read_json(tree_path)
    meetings: dict[str, dict[str, Any]] = {}
    for meeting in tree.get("meetings", []) or []:
        if not isinstance(meeting, dict):
            continue
        meeting_id = str(meeting.get("meeting_id", "") or "").strip()
        if meeting_id:
            meetings[meeting_id] = dict(meeting)
    return meetings


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, str]:
    manifest_path = Path(str(candidate["manifest_path"]))
    try:
        modified = manifest_path.stat().st_mtime
    except OSError:
        modified = 0.0
    return (modified, str(candidate["run_root"]))


def discover_completed_bmr_filtered_meetings(
    *,
    runs_root: Path | str = Path("memory_outputs") / "icsi" / "runs",
    expected_meeting_ids: list[str] | None = None,
    allow_missing: bool = False,
    exclude_markers: set[str] | None = None,
) -> dict[str, Any]:
    """Select one effective filtered meeting payload per expected full BMR meeting.

    The selector is intentionally meeting-level, not root-level. ICSI has retry roots
    and shared roots, so combining whole roots can accidentally duplicate a meeting.
    """

    root = Path(runs_root)
    expected = expected_meeting_ids or ICSI_BMR_EXPECTED_FULL_IDS
    expected_set = set(expected)
    markers = exclude_markers if exclude_markers is not None else DEFAULT_EXCLUDE_RUN_NAME_MARKERS
    skipped_roots: list[dict[str, Any]] = []
    candidates_by_meeting: dict[str, list[dict[str, Any]]] = {meeting_id: [] for meeting_id in expected}

    for run_root in sorted([path for path in root.iterdir() if path.is_dir()] if root.exists() else []):
        excluded_marker = _run_name_is_excluded(run_root, exclude_markers=markers)
        if excluded_marker:
            skipped_roots.append(
                {
                    "run_root": str(run_root),
                    "reason": f"excluded_marker:{excluded_marker}",
                }
            )
            continue
        filtered_root = run_root / "filtered_share_mem"
        manifest_path = filtered_root / "manifest.json"
        if not manifest_path.exists():
            skipped_roots.append({"run_root": str(run_root), "reason": "missing_filtered_manifest"})
            continue
        try:
            manifest = _read_json(manifest_path)
            meeting_ids = [str(meeting_id) for meeting_id in manifest.get("meeting_ids", []) or []]
            meetings_by_id = _load_meetings_by_id(filtered_root)
        except Exception as exc:  # pragma: no cover - defensive audit record
            skipped_roots.append({"run_root": str(run_root), "reason": f"invalid_filtered_root:{exc}"})
            continue
        statuses = _latest_status_by_meeting(run_root / "batch_status.json")
        for meeting_id in meeting_ids:
            if meeting_id not in expected_set:
                continue
            if meeting_id not in meetings_by_id:
                skipped_roots.append(
                    {
                        "run_root": str(run_root),
                        "meeting_id": meeting_id,
                        "reason": "manifest_meeting_missing_from_tree",
                    }
                )
                continue
            latest_status = statuses.get(meeting_id, "")
            if latest_status and latest_status != "succeeded":
                skipped_roots.append(
                    {
                        "run_root": str(run_root),
                        "meeting_id": meeting_id,
                        "reason": f"latest_status_not_succeeded:{latest_status}",
                    }
                )
                continue
            candidates_by_meeting.setdefault(meeting_id, []).append(
                {
                    "meeting_id": meeting_id,
                    "run_root": str(run_root),
                    "filtered_root": str(filtered_root),
                    "manifest_path": str(manifest_path),
                    "manifest_meeting_count": manifest.get("meeting_count"),
                    "manifest_object_count": manifest.get("object_count"),
                    "latest_status": latest_status or "status_not_recorded",
                    "meeting": meetings_by_id[meeting_id],
                }
            )

    selected_payloads: dict[str, dict[str, Any]] = {}
    meeting_sources: dict[str, dict[str, Any]] = {}
    duplicate_candidates: dict[str, list[dict[str, Any]]] = {}
    missing: list[str] = []
    for meeting_id in expected:
        candidates = candidates_by_meeting.get(meeting_id, [])
        if not candidates:
            missing.append(meeting_id)
            continue
        candidates = sorted(candidates, key=_candidate_sort_key)
        selected = candidates[-1]
        selected_payloads[meeting_id] = selected["meeting"]
        meeting_sources[meeting_id] = {
            key: value
            for key, value in selected.items()
            if key != "meeting"
        }
        if len(candidates) > 1:
            duplicate_candidates[meeting_id] = [
                {key: value for key, value in row.items() if key != "meeting"}
                for row in candidates
            ]

    if missing and not allow_missing:
        raise ValueError(
            "Missing completed filtered ICSI BMR meetings: " + ", ".join(missing)
        )

    selected_meetings = [meeting_id for meeting_id in expected if meeting_id in selected_payloads]
    return {
        "schema_version": 1,
        "generated_at_utc": _utc_now_iso(),
        "runs_root": str(root),
        "expected_meeting_ids": expected,
        "absent_meeting_ids": sorted(ICSI_BMR_ABSENT_IDS),
        "selected_meetings": selected_meetings,
        "selected_meeting_count": len(selected_meetings),
        "missing_meeting_ids": missing,
        "allow_missing": allow_missing,
        "meeting_sources": meeting_sources,
        "selected_meeting_payloads": selected_payloads,
        "duplicate_candidates": duplicate_candidates,
        "skipped_roots": skipped_roots,
    }


def write_selected_effective_share_mem(
    *,
    discovery: dict[str, Any],
    output_root: Path | str,
    clean: bool = False,
) -> dict[str, Any]:
    output = Path(output_root)
    effective_root = output / "share_mem_effective"
    if clean and effective_root.exists():
        shutil.rmtree(effective_root)
    output.mkdir(parents=True, exist_ok=True)
    selected_meetings = [
        discovery["selected_meeting_payloads"][meeting_id]
        for meeting_id in discovery.get("selected_meetings", [])
    ]
    tree = {
        "tree_version": 1,
        "last_updated_utc": _utc_now_iso(),
        "project_profile": {
            "source": "icsi_bmr_full_selected_filtered_share_mem",
            "sidecar_only": True,
        },
        "phases": [],
        "meetings": selected_meetings,
        "source_view": {
            "source": "selected_filtered_share_mem",
            "sidecar_only": True,
            "meeting_sources": discovery.get("meeting_sources", {}),
            "raw_share_mem_ignored": True,
        },
    }
    manifest = refresh_share_mem_outputs(
        root=effective_root,
        tree=tree,
        source_transcript_dir=None,
    )
    report = {
        "schema_version": 1,
        "generated_at_utc": _utc_now_iso(),
        "mode": "icsi_bmr_full_selected_filtered_share_mem",
        "output_root": str(output),
        "share_mem_effective_root": str(effective_root),
        "discovery": {
            key: value
            for key, value in discovery.items()
            if key != "selected_meeting_payloads"
        },
        "summary": {
            "meeting_count": manifest.get("meeting_count", 0),
            "object_count": manifest.get("object_count", 0),
            "meeting_ids": manifest.get("meeting_ids", []),
            "tree_hash": manifest.get("tree_hash", ""),
            "missing_meeting_ids": discovery.get("missing_meeting_ids", []),
        },
    }
    _write_json(output / "combine_manifest.json", report)
    return report


def _report_lines(
    *,
    combine_report: dict[str, Any],
    run_root: Path,
    build_result: dict[str, Any],
    validation: dict[str, Any],
    topic_audit: dict[str, Any],
    query_report: dict[str, Any] | None,
    retrieval: dict[str, Any] | None,
) -> list[str]:
    manifest = build_result["manifest"]
    summary = combine_report["summary"]
    lines = [
        "# ICSI BMR Full Optimization v2 Evaluation Pipeline",
        "",
        "This is a sidecar-only pipeline output. It reads filtered effective L1 roots and does not modify canonical `share_mem/` or `long_term/` artifacts.",
        "",
        "## Inputs",
        "",
        f"- effective meetings: {summary['meeting_count']}",
        f"- effective L1 objects: {summary['object_count']}",
        f"- missing expected meetings: {', '.join(summary.get('missing_meeting_ids', [])) or 'none'}",
        f"- combined effective root: `{combine_report['share_mem_effective_root']}`",
        "",
        "## Optimization v2 Build",
        "",
        f"- run root: `{run_root}`",
        f"- L1 count: {manifest['source_l1_count']}",
        f"- L2 topics: {manifest['l2_topic_count']}",
        f"- L3 parents: {manifest['l3_parent_count']}",
        f"- linked L1: {manifest['linked_l1_count']}",
        f"- unlinked L1: {manifest['unlinked_l1_count']}",
        "",
        "## Validation",
        "",
        f"- severe: {validation['severe_count']}",
        f"- warnings: {validation['warning_count']}",
        f"- topic audit severe: {topic_audit['severe_count']}",
        f"- topic audit warnings: {topic_audit['warning_count']}",
        f"- topic manual review items: {topic_audit['manual_review_count']}",
        "",
    ]
    if query_report and retrieval:
        retrieval_summary = retrieval["summary"]
        lines.extend(
            [
                "## Retrieval Diagnostic",
                "",
                f"- generated native queries: {query_report['query_count']}",
                f"- avg expected L1 recall: {retrieval_summary['avg_expected_obj_recall_at_context']}",
                f"- expected L2 semantic hit: {retrieval_summary['expected_l2_semantic_hit_rate']}",
                f"- expected L3 semantic hit: {retrieval_summary['expected_l3_semantic_hit_rate']}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Retrieval Diagnostic",
                "",
                "- skipped",
                "",
            ]
        )
    lines.extend(
        [
            "## Next Review Targets",
            "",
            "Inspect large or broad L2/L3 topics before claiming final ICSI benchmark quality. This runner intentionally prepares the evidence and diagnostics, but does not auto-promote generated topics.",
            "",
        ]
    )
    return lines


def run_icsi_full_eval_pipeline(
    *,
    runs_root: Path | str,
    effective_output_root: Path | str,
    optimization_run_root: Path | str,
    report_path: Path | str,
    profile_path: Path | str,
    expected_meeting_ids: list[str] | None = None,
    allow_missing: bool = False,
    clean: bool = False,
    run_retrieval_eval: bool = True,
    max_queries: int = 12,
    top_k_l1: int = 60,
) -> dict[str, Any]:
    discovery = discover_completed_bmr_filtered_meetings(
        runs_root=runs_root,
        expected_meeting_ids=expected_meeting_ids,
        allow_missing=allow_missing,
    )
    combine_report = write_selected_effective_share_mem(
        discovery=discovery,
        output_root=effective_output_root,
        clean=clean,
    )
    effective_root = Path(combine_report["share_mem_effective_root"])
    run_root = Path(optimization_run_root)
    build_result = build_view(
        share_mem_root=effective_root,
        profile_path=profile_path,
        out_root=run_root,
        mode="deterministic",
        clean=clean,
    )
    validation = validate_run(run_root=run_root)
    topic_audit = audit_topic_quality(run_root=run_root)

    query_report: dict[str, Any] | None = None
    retrieval: dict[str, Any] | None = None
    if run_retrieval_eval:
        query_report = curate_v2_native_queries(
            run_root=run_root,
            topic_source="largest",
            max_queries=max_queries,
            out_path=run_root / "retrieval_eval" / "v2_native_queries.jsonl",
        )
        retrieval = evaluate_retrieval(
            run_root=run_root,
            queries_path=query_report["queries_path"],
            share_mem_root=effective_root,
            top_k_l1=top_k_l1,
            out_subdir="retrieval_eval/native_eval",
        )

    summary = {
        "schema_version": 1,
        "generated_at_utc": _utc_now_iso(),
        "combine_report_path": str(Path(effective_output_root) / "combine_manifest.json"),
        "share_mem_effective_root": str(effective_root),
        "optimization_run_root": str(run_root),
        "profile_path": str(Path(profile_path).resolve()),
        "meeting_count": combine_report["summary"]["meeting_count"],
        "object_count": combine_report["summary"]["object_count"],
        "missing_meeting_ids": combine_report["summary"].get("missing_meeting_ids", []),
        "l2_topic_count": build_result["manifest"]["l2_topic_count"],
        "l3_parent_count": build_result["manifest"]["l3_parent_count"],
        "validation_severe_count": validation["severe_count"],
        "validation_warning_count": validation["warning_count"],
        "topic_audit_severe_count": topic_audit["severe_count"],
        "topic_audit_warning_count": topic_audit["warning_count"],
        "topic_manual_review_count": topic_audit["manual_review_count"],
        "retrieval_summary": retrieval["summary"] if retrieval else {},
        "sidecar_only": True,
    }
    _write_json(run_root / "pipeline_summary.json", summary)
    report = Path(report_path)
    _write_text(
        report,
        "\n".join(
            _report_lines(
                combine_report=combine_report,
                run_root=run_root,
                build_result=build_result,
                validation=validation,
                topic_audit=topic_audit,
                query_report=query_report,
                retrieval=retrieval,
            )
        )
        + "\n",
    )
    summary["report_path"] = str(report)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the sidecar-only ICSI full BMR optimization v2 eval pipeline.")
    parser.add_argument("--runs-root", default=str(Path("memory_outputs") / "icsi" / "runs"))
    parser.add_argument("--effective-output-root", required=True)
    parser.add_argument("--optimization-run-root", required=True)
    parser.add_argument("--report-path", required=True)
    parser.add_argument("--profile", default=str(Path("optimization") / "long_term_v2" / "profiles" / "isci_meeting.yaml"))
    parser.add_argument("--expected-meeting-id", action="append", default=[])
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--skip-retrieval-eval", action="store_true")
    parser.add_argument("--max-queries", type=int, default=12)
    parser.add_argument("--top-k-l1", type=int, default=60)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    summary = run_icsi_full_eval_pipeline(
        runs_root=args.runs_root,
        effective_output_root=args.effective_output_root,
        optimization_run_root=args.optimization_run_root,
        report_path=args.report_path,
        profile_path=args.profile,
        expected_meeting_ids=args.expected_meeting_id or None,
        allow_missing=bool(args.allow_missing),
        clean=bool(args.clean),
        run_retrieval_eval=not bool(args.skip_retrieval_eval),
        max_queries=args.max_queries,
        top_k_l1=args.top_k_l1,
    )
    print(
        "[optimization:v2] ICSI full eval pipeline complete: "
        f"meetings={summary['meeting_count']} l1={summary['object_count']} "
        f"l2={summary['l2_topic_count']} l3={summary['l3_parent_count']} "
        f"report={summary['report_path']}"
    )


if __name__ == "__main__":
    main()
