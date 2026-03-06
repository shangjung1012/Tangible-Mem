from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from io_utils import utc_now_iso
from schema import (
    ACTION_ITEM_STATUS,
    DEFAULT_MEMORY,
    EXPERIMENT_STATUS,
    METHOD_CHANGE_STATUS,
    PRIORITY_LEVELS,
)


def next_seq_id(prefix: str, used_ids: set[str]) -> str:
    max_num = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for value in used_ids:
        match = pattern.match(value)
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"{prefix}{max_num + 1:03d}"


def normalize_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = normalize_str(item)
        if text:
            cleaned.append(text)
    return cleaned


def normalize_meeting_window(
    raw_window: Any, meeting_id: str, source_file: str
) -> list[dict[str, Any]]:
    if not isinstance(raw_window, list):
        raw_window = []

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in raw_window:
        if not isinstance(row, dict):
            continue
        mid = normalize_str(row.get("meeting_id"))
        if not mid:
            continue
        item = {
            "meeting_id": mid,
            "source_file": normalize_str(row.get("source_file"), source_file),
            "summary": normalize_str(row.get("summary")),
            "key_points": normalize_str_list(row.get("key_points")),
            "open_questions": normalize_str_list(row.get("open_questions")),
        }
        if mid in seen:
            ordered = [x for x in ordered if x["meeting_id"] != mid]
        seen.add(mid)
        ordered.append(item)

    if meeting_id not in seen:
        ordered.append(
            {
                "meeting_id": meeting_id,
                "source_file": source_file,
                "summary": "Summary pending from transcript extraction.",
                "key_points": [],
                "open_questions": [],
            }
        )

    return ordered[-3:]


def normalize_action_items(raw_items: Any, meeting_id: str) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        raw_items = []

    normalized: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for row in raw_items:
        if not isinstance(row, dict):
            continue
        raw_id = normalize_str(row.get("item_id"))
        item_id = raw_id if raw_id and raw_id not in used_ids else next_seq_id("A", used_ids)
        used_ids.add(item_id)

        status = normalize_str(row.get("status"), "open").lower()
        if status not in ACTION_ITEM_STATUS:
            status = "open"

        priority = normalize_str(row.get("priority"), "medium").lower()
        if priority not in PRIORITY_LEVELS:
            priority = "medium"

        history_rows = row.get("history")
        history: list[dict[str, Any]] = []
        if isinstance(history_rows, list):
            for h in history_rows:
                if not isinstance(h, dict):
                    continue
                history.append(
                    {
                        "version": int(h.get("version", 0) or 0),
                        "meeting_id": normalize_str(h.get("meeting_id"), meeting_id),
                        "change": normalize_str(h.get("change")),
                    }
                )
        if not history:
            history = [
                {
                    "version": 0,
                    "meeting_id": meeting_id,
                    "change": "imported or created",
                }
            ]

        normalized.append(
            {
                "item_id": item_id,
                "title": normalize_str(row.get("title")),
                "detail": normalize_str(row.get("detail")),
                "proposer": normalize_str(row.get("proposer"), "unknown"),
                "owner": normalize_str(row.get("owner"), "unknown"),
                "created_meeting_id": normalize_str(
                    row.get("created_meeting_id"), meeting_id
                ),
                "created_time_hint": normalize_str(row.get("created_time_hint")),
                "dependencies": normalize_str_list(row.get("dependencies")),
                "status": status,
                "priority": priority,
                "evidence": normalize_str(row.get("evidence")),
                "last_updated_meeting_id": normalize_str(
                    row.get("last_updated_meeting_id"), meeting_id
                ),
                "history": history,
            }
        )

    return normalized


def normalize_method_changes(raw_items: Any, meeting_id: str) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        raw_items = []
    normalized: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for row in raw_items:
        if not isinstance(row, dict):
            continue
        raw_id = normalize_str(row.get("change_id"))
        change_id = (
            raw_id if raw_id and raw_id not in used_ids else next_seq_id("M", used_ids)
        )
        used_ids.add(change_id)
        status = normalize_str(row.get("status"), "active").lower()
        if status not in METHOD_CHANGE_STATUS:
            status = "active"

        normalized.append(
            {
                "change_id": change_id,
                "topic": normalize_str(row.get("topic")),
                "before": normalize_str(row.get("before")),
                "after": normalize_str(row.get("after")),
                "reason": normalize_str(row.get("reason")),
                "status": status,
                "meeting_id": normalize_str(row.get("meeting_id"), meeting_id),
                "evidence": normalize_str(row.get("evidence")),
            }
        )

    return normalized


def normalize_experiment_todos(raw_items: Any, meeting_id: str) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        raw_items = []
    normalized: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for row in raw_items:
        if not isinstance(row, dict):
            continue
        raw_id = normalize_str(row.get("todo_id"))
        todo_id = raw_id if raw_id and raw_id not in used_ids else next_seq_id("E", used_ids)
        used_ids.add(todo_id)

        status = normalize_str(row.get("status"), "open").lower()
        if status not in EXPERIMENT_STATUS:
            status = "open"

        normalized.append(
            {
                "todo_id": todo_id,
                "description": normalize_str(row.get("description")),
                "status": status,
                "owner": normalize_str(row.get("owner"), "unknown"),
                "related_action_item_ids": normalize_str_list(
                    row.get("related_action_item_ids")
                ),
                "meeting_id": normalize_str(row.get("meeting_id"), meeting_id),
                "evidence": normalize_str(row.get("evidence")),
            }
        )

    return normalized


def normalize_memory(
    updated_memory: dict[str, Any],
    previous_memory: dict[str, Any],
    meeting_id: str,
    source_file: str,
) -> dict[str, Any]:
    merged: dict[str, Any] = deepcopy(DEFAULT_MEMORY)
    merged.update(previous_memory)
    merged.update(updated_memory)

    previous_version = int(previous_memory.get("memory_version", 0) or 0)
    version = int(merged.get("memory_version", previous_version + 1) or previous_version + 1)
    if version <= previous_version:
        version = previous_version + 1

    previous_meeting_window = normalize_meeting_window(
        previous_memory.get("meeting_window"), meeting_id, source_file
    )
    updated_meeting_window = normalize_meeting_window(
        merged.get("meeting_window"), meeting_id, source_file
    )
    meeting_window = normalize_meeting_window(
        previous_meeting_window + updated_meeting_window, meeting_id, source_file
    )

    previous_action_items = normalize_action_items(
        previous_memory.get("action_items"), meeting_id
    )
    updated_action_items = normalize_action_items(merged.get("action_items"), meeting_id)
    action_item_map = {item["item_id"]: item for item in previous_action_items}
    for item in updated_action_items:
        action_item_map[item["item_id"]] = item

    previous_method_changes = normalize_method_changes(
        previous_memory.get("method_changes"), meeting_id
    )
    updated_method_changes = normalize_method_changes(
        merged.get("method_changes"), meeting_id
    )
    method_change_map = {item["change_id"]: item for item in previous_method_changes}
    for item in updated_method_changes:
        method_change_map[item["change_id"]] = item

    previous_experiment_todos = normalize_experiment_todos(
        previous_memory.get("experiment_todos"), meeting_id
    )
    updated_experiment_todos = normalize_experiment_todos(
        merged.get("experiment_todos"), meeting_id
    )
    experiment_todo_map = {
        item["todo_id"]: item for item in previous_experiment_todos
    }
    for item in updated_experiment_todos:
        experiment_todo_map[item["todo_id"]] = item

    merged["memory_version"] = version
    merged["last_updated_utc"] = utc_now_iso()
    merged["last_updated_meeting_id"] = meeting_id
    merged["meeting_window"] = meeting_window
    merged["action_items"] = list(action_item_map.values())
    merged["method_changes"] = list(method_change_map.values())
    merged["experiment_todos"] = list(experiment_todo_map.values())

    next_focus = normalize_str_list(merged.get("next_meeting_focus"))
    if not next_focus:
        next_focus = normalize_str_list(previous_memory.get("next_meeting_focus"))
    merged["next_meeting_focus"] = next_focus
    return merged
