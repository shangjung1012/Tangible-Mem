"""Rebuild resumable L1 batch checkpoints from existing multi-agent API logs.

This is an offline recovery utility. It never calls an LLM and never writes
canonical share_mem files. It only writes l1_batch_checkpoints/ under an
existing research log run directory plus a JSON/Markdown report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from share_mem.l1.multi_agent_agents import clamp_float, unique_strings
from share_mem.l1.multi_agent_pipeline import write_l1_batch_checkpoint
from share_mem.l1.multi_agent_state import IdeaUnit, L1Candidate
from share_mem.l1.taxonomy import (
    normalize_legacy_type,
    normalize_taxonomy,
    type_order_for_taxonomy,
    type_set_for_taxonomy,
)

STAGE_RE = re.compile(r"^l1_(?P<agent>.+)_agent_(?P<batch_id>B-[A-Za-z0-9-]+)$")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _idea_units_by_id(run_dir: Path) -> dict[str, IdeaUnit]:
    rows = _load_json(run_dir / "idea_units.json")
    return {
        str(row["unit_id"]): IdeaUnit(
            unit_id=str(row["unit_id"]),
            segment_id=str(row["segment_id"]),
            line_start=int(row["line_start"]),
            line_end=int(row["line_end"]),
            text=str(row["text"]),
            completeness=str(row["completeness"]),
            uncertainty_note=str(row.get("uncertainty_note", "")),
        )
        for row in rows
        if isinstance(row, dict) and row.get("unit_id")
    }


def _batch_units(batch: dict[str, Any], unit_by_id: dict[str, IdeaUnit]) -> list[IdeaUnit]:
    unit_ids = [str(item) for item in batch.get("unit_ids", [])]
    if unit_ids:
        return [unit_by_id[unit_id] for unit_id in unit_ids if unit_id in unit_by_id]
    segment_ids = {str(item) for item in batch.get("segment_ids", [])}
    return [unit for unit in unit_by_id.values() if unit.segment_id in segment_ids]


def _candidate_from_agent_row(
    *,
    row: dict[str, Any],
    obj_type: str,
    index: int,
    batch_id: str,
    allowed_unit_ids: set[str],
    segment_ids: list[str],
    include_legacy_type: bool,
    allowed_types: set[str],
    fallback: bool = False,
) -> L1Candidate | None:
    row_type = str(row.get("type") or obj_type).strip().lower()
    if row_type not in allowed_types:
        return None
    if not fallback and row_type != obj_type:
        return None
    content = str(row.get("content", "")).strip()
    if not content:
        return None
    source_unit_ids = [
        unit_id
        for unit_id in unique_strings(row.get("source_unit_ids", []))
        if unit_id in allowed_unit_ids
    ]
    if not source_unit_ids:
        return None
    candidate_kind = f"fallback-{row_type}" if fallback else obj_type
    return L1Candidate(
        candidate_id=f"C-{batch_id}-{candidate_kind}-{index:03d}",
        type=row_type,
        source_unit_ids=source_unit_ids,
        content=content,
        importance=clamp_float(row.get("importance", 0.5)),
        confidence=clamp_float(row.get("confidence", 0.5)),
        rationale=str(row.get("rationale", "")).strip(),
        related_topics=unique_strings(row.get("related_topics", [])),
        extraction_scope=batch_id,
        segment_ids=segment_ids,
        legacy_type=(
            normalize_legacy_type(row.get("legacy_type"), obj_type=row_type)
            if include_legacy_type
            else ""
        ),
    )


def _load_successful_l1_calls(run_dir: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    api_calls_path = run_dir / "api_calls" / "api_calls.jsonl"
    calls: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    if not api_calls_path.exists():
        return {}
    with api_calls_path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not row.get("success"):
                continue
            match = STAGE_RE.match(str(row.get("stage", "")))
            if not match:
                continue
            parsed = row.get("parsed_json")
            if not isinstance(parsed, dict):
                continue
            candidates = parsed.get("candidates", [])
            if not isinstance(candidates, list):
                candidates = []
            calls[match.group("batch_id")][match.group("agent")] = [
                item for item in candidates if isinstance(item, dict)
            ]
    return calls


def rebuild_run_checkpoints(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    meta = _load_json(run_dir / "run_meta.json")
    taxonomy = normalize_taxonomy(meta.get("taxonomy"))
    agent_type_order = type_order_for_taxonomy(taxonomy)
    allowed_types = type_set_for_taxonomy(taxonomy)
    include_legacy_type = bool(meta.get("include_legacy_type", False))
    content_language = str(meta.get("content_language", "traditional_zh"))
    batches = [row for row in _load_json(run_dir / "extraction_batches.json") if isinstance(row, dict)]
    unit_by_id = _idea_units_by_id(run_dir)
    successful_calls = _load_successful_l1_calls(run_dir)

    rebuilt: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for batch in batches:
        batch_id = str(batch.get("batch_id", ""))
        calls_by_agent = successful_calls.get(batch_id, {})
        missing_agents = [agent for agent in agent_type_order if agent not in calls_by_agent]
        units = _batch_units(batch, unit_by_id)
        if missing_agents or not units:
            skipped.append(
                {
                    "batch_id": batch_id,
                    "reason": "missing_agent_calls" if missing_agents else "missing_batch_units",
                    "missing_agents": missing_agents,
                }
            )
            continue
        allowed_unit_ids = {unit.unit_id for unit in units}
        segment_ids = [str(item) for item in batch.get("segment_ids", [])]
        candidates: list[L1Candidate] = []
        for agent in agent_type_order:
            for index, candidate_row in enumerate(calls_by_agent.get(agent, []), start=1):
                candidate = _candidate_from_agent_row(
                    row=candidate_row,
                    obj_type=agent,
                    index=index,
                    batch_id=batch_id,
                    allowed_unit_ids=allowed_unit_ids,
                    segment_ids=segment_ids,
                    include_legacy_type=include_legacy_type,
                    allowed_types=allowed_types,
                )
                if candidate is not None:
                    candidates.append(candidate)
        fallback_rows = calls_by_agent.get("fallback", [])
        if not candidates and "fallback" not in calls_by_agent:
            skipped.append(
                {
                    "batch_id": batch_id,
                    "reason": "typed_agents_empty_without_fallback_call",
                    "missing_agents": [],
                }
            )
            continue
        for index, candidate_row in enumerate(fallback_rows, start=1):
            candidate = _candidate_from_agent_row(
                row=candidate_row,
                obj_type="",
                index=index,
                batch_id=batch_id,
                allowed_unit_ids=allowed_unit_ids,
                segment_ids=segment_ids,
                include_legacy_type=include_legacy_type,
                allowed_types=allowed_types,
                fallback=True,
            )
            if candidate is not None:
                candidates.append(candidate)
        fallback_reports = []
        if fallback_rows:
            fallback_reports.append(
                {
                    "batch_id": batch_id,
                    "extraction_packet_id": batch_id,
                    "segment_ids": segment_ids,
                    "idea_units": len(units),
                    "fallback_candidates": len(fallback_rows),
                    "reason": "typed_l1_agents_returned_no_candidates",
                }
            )
        checkpoint_path = write_l1_batch_checkpoint(
            run_dir=run_dir,
            batch=batch,
            batch_units=units,
            agent_type_order=agent_type_order,
            taxonomy=taxonomy,
            include_legacy_type=include_legacy_type,
            content_language=content_language,
            candidates=candidates,
            fallback_reports=fallback_reports,
            generated_from="api_call_rebuild",
        )
        rebuilt.append(
            {
                "batch_id": batch_id,
                "candidate_count": len(candidates),
                "checkpoint_path": str(checkpoint_path),
            }
        )

    report = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "meeting_id": meta.get("meeting_id"),
        "taxonomy": taxonomy,
        "batch_count": len(batches),
        "rebuilt_checkpoint_count": len(rebuilt),
        "skipped_batch_count": len(skipped),
        "rebuilt": rebuilt,
        "skipped": skipped,
    }
    _write_json(run_dir / "l1_batch_checkpoints" / "rebuild_report.json", report)
    return report


def write_summary_markdown(path: Path, reports: list[dict[str, Any]]) -> None:
    lines = ["# L1 Batch Checkpoint Rebuild Summary", ""]
    for report in reports:
        lines.extend(
            [
                f"## {report.get('meeting_id') or Path(str(report.get('run_dir'))).name}",
                "",
                f"- run_dir: `{report.get('run_dir')}`",
                f"- batches: `{report.get('batch_count')}`",
                f"- rebuilt checkpoints: `{report.get('rebuilt_checkpoint_count')}`",
                f"- skipped batches: `{report.get('skipped_batch_count')}`",
                "",
            ]
        )
        skipped = report.get("skipped", [])[:8]
        if skipped:
            lines.append("Skipped examples:")
            for row in skipped:
                lines.append(
                    f"- `{row.get('batch_id')}`: {row.get('reason')} "
                    f"{row.get('missing_agents') or ''}"
                )
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", action="append", default=[], help="Research log run dir.")
    parser.add_argument("--report-root", default="", help="Optional aggregate report output dir.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.run_dir:
        raise SystemExit("At least one --run-dir is required.")
    reports = [rebuild_run_checkpoints(Path(run_dir)) for run_dir in args.run_dir]
    if args.report_root:
        root = Path(args.report_root)
        _write_json(root / "checkpoint_rebuild_summary.json", {"runs": reports})
        write_summary_markdown(root / "checkpoint_rebuild_summary.md", reports)
    print(json.dumps({"run_count": len(reports), "reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
