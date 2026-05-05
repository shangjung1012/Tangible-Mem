from __future__ import annotations

from typing import Any, TypedDict


class ShortTermGraphState(TypedDict, total=False):
    run_id: str
    meeting_id: str
    source_file: str
    model_name: str
    db_path: str
    transcript_db_path: str
    checkpoint_db_path: str
    research_log_dir: str
    log_level: str
    keep_full_prompts: bool
    dry_run: bool
    chunk_size: int
    max_lookback_lines: int
    max_lookahead_lines: int
    max_context_rounds: int

    transcript_line_count: int
    transcript_overview: dict[str, Any]
    current_memory: dict[str, Any]
    memory_source: str
    processed_until_line: int
    planner_history: list[dict[str, Any]]
    context_rounds: int
    current_plan: dict[str, Any]
    current_window: dict[str, Any]
    current_units: list[dict[str, Any]]
    context_units_buffer: list[dict[str, Any]]
    context_items_buffer: list[dict[str, Any]]
    needs_more_context: bool
    unresolved_context: list[dict[str, Any]]
    read_line_numbers: list[int]
    meeting_window_candidates_buffer: list[dict[str, Any]]
    action_items_candidates_buffer: list[dict[str, Any]]
    method_changes_candidates_buffer: list[dict[str, Any]]
    experiment_todos_candidates_buffer: list[dict[str, Any]]
    next_meeting_focus_candidates_buffer: list[dict[str, Any]]

    raw_candidates: list[dict[str, Any]]
    tool_reads: dict[str, list[str]]
    verified_candidates: list[dict[str, Any]]
    rejected_candidates: list[dict[str, Any]]
    final_patch: dict[str, Any]
    final_memory: dict[str, Any]
    report: dict[str, Any]
    persisted: bool


def memory_summary(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_version": int(memory.get("memory_version", 0) or 0),
        "last_updated_meeting_id": str(memory.get("last_updated_meeting_id", "")),
        "meeting_history_count": len(memory.get("meeting_history_ids", [])),
        "meeting_window_count": len(memory.get("meeting_window", [])),
        "action_items_count": len(memory.get("action_items", [])),
        "method_changes_count": len(memory.get("method_changes", [])),
        "experiment_todos_count": len(memory.get("experiment_todos", [])),
        "next_meeting_focus_count": len(memory.get("next_meeting_focus", [])),
    }


def action_item_index(memory: dict[str, Any], limit: int = 120) -> list[dict[str, str]]:
    index: list[dict[str, str]] = []
    for row in memory.get("action_items", []):
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("item_id", "")).strip()
        if not item_id:
            continue
        index.append(
            {
                "item_id": item_id,
                "title": _short(row.get("title"), 100),
                "detail_hint": _short(row.get("detail"), 160),
                "status": str(row.get("status", "")).strip(),
                "priority": str(row.get("priority", "")).strip(),
                "owner": _short(row.get("owner"), 80),
                "created_meeting_id": str(row.get("created_meeting_id", "")).strip(),
                "last_updated_meeting_id": str(
                    row.get("last_updated_meeting_id", "")
                ).strip(),
            }
        )
        if len(index) >= limit:
            break
    return index


def transcript_items_text(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        line_number = item.get("line_number", "")
        speaker = str(item.get("speaker", "")).strip()
        text = str(item.get("text", "")).strip()
        prefix = f"L{line_number}"
        if speaker:
            prefix += f" [{speaker}]"
        lines.append(f"{prefix}: {text}")
    return "\n".join(lines)


def _short(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."
