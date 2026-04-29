from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .graph_state import memory_summary
    from .sqlite_store import load_memory_from_sqlite
    from .staging_store import write_staged_candidate
except ImportError:  # pragma: no cover
    from graph_state import memory_summary
    from sqlite_store import load_memory_from_sqlite
    from staging_store import write_staged_candidate


DEFAULT_PAGE_SIZE = 50


@dataclass(slots=True)
class AgentToolPolicy:
    agent_name: str
    read_sections: set[str] = field(default_factory=set)
    required_read_sections: set[str] = field(default_factory=set)
    write_sections: set[str] = field(default_factory=set)


@dataclass(slots=True)
class AgentToolContext:
    db_path: Path
    run_id: str
    meeting_id: str
    policy: AgentToolPolicy
    read_sections: set[str] = field(default_factory=set)


def read_short_term_memory_tool(
    context: AgentToolContext,
    *,
    section: str = "overview",
    offset: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
    ids: list[str] | None = None,
) -> dict[str, Any]:
    normalized = str(section or "overview").strip()
    if normalized not in context.policy.read_sections:
        return {
            "ok": False,
            "error": "section_not_allowed",
            "section": normalized,
            "allowed_sections": sorted(context.policy.read_sections),
        }

    memory = load_memory_from_sqlite(context.db_path)
    context.read_sections.add(normalized)
    if normalized == "overview":
        return {"ok": True, "section": normalized, "overview": memory_summary(memory)}

    rows = memory.get(normalized, [])
    if normalized == "next_meeting_focus":
        rows = [
            {"index": index, "text": value}
            for index, value in enumerate(rows if isinstance(rows, list) else [], start=1)
        ]
    elif not isinstance(rows, list):
        rows = []

    filtered = _filter_rows_by_ids(normalized, rows, ids)
    safe_offset = max(0, int(offset or 0))
    safe_limit = max(1, min(200, int(limit or DEFAULT_PAGE_SIZE)))
    page = filtered[safe_offset : safe_offset + safe_limit]
    return {
        "ok": True,
        "section": normalized,
        "offset": safe_offset,
        "limit": safe_limit,
        "returned_count": len(page),
        "total_count": len(filtered),
        "has_more": safe_offset + safe_limit < len(filtered),
        "items": page,
    }


def write_memory_candidate_tool(
    context: AgentToolContext,
    *,
    operation: str,
    target_section: str,
    candidate_payload: dict[str, Any],
    target_id: str = "",
    confidence: float = 0.0,
    note: str = "",
    evidence_lines: list[Any] | None = None,
    evidence_quote: str = "",
) -> dict[str, Any]:
    section = str(target_section or "").strip()
    if section not in context.policy.write_sections:
        return {
            "ok": False,
            "error": "section_not_allowed",
            "section": section,
            "allowed_sections": sorted(context.policy.write_sections),
        }

    missing_reads = sorted(context.policy.required_read_sections - context.read_sections)
    if missing_reads:
        return {
            "ok": False,
            "error": "missing_required_read",
            "missing_sections": missing_reads,
        }

    return write_staged_candidate(
        context.db_path,
        run_id=context.run_id,
        meeting_id=context.meeting_id,
        agent_name=context.policy.agent_name,
        target_section=section,
        operation=operation,
        target_id=target_id,
        candidate_payload=candidate_payload,
        evidence_lines=evidence_lines,
        evidence_quote=evidence_quote,
        confidence=confidence,
        note=note,
    )


def _filter_rows_by_ids(
    section: str,
    rows: list[Any],
    ids: list[str] | None,
) -> list[Any]:
    if not ids:
        return rows
    wanted = {str(value).strip() for value in ids if str(value).strip()}
    if not wanted:
        return rows
    id_key = {
        "meeting_window": "meeting_id",
        "action_items": "item_id",
        "method_changes": "change_id",
        "experiment_todos": "todo_id",
        "next_meeting_focus": "index",
    }.get(section, "")
    if not id_key:
        return rows
    output: list[Any] = []
    for row in rows:
        if isinstance(row, dict) and str(row.get(id_key, "")).strip() in wanted:
            output.append(row)
    return output
