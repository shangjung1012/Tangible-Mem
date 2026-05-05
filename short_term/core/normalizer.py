from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

try:
    from ..storage.io_utils import utc_now_iso
    from .schema import (
        ACTION_ITEM_STATUS,
        DEFAULT_MEMORY,
        EXPERIMENT_STATUS,
        METHOD_CHANGE_STATUS,
        PRIORITY_LEVELS,
    )
except ImportError:  # pragma: no cover - script execution fallback
    from short_term.storage.io_utils import utc_now_iso
    from short_term.core.schema import (
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


def dedupe_keep_last(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        if item in deduped:
            deduped = [x for x in deduped if x != item]
        deduped.append(item)
    return deduped


def normalize_meeting_history_ids(
    previous_memory: dict[str, Any],
    meeting_id: str,
) -> list[str]:
    history_ids = normalize_str_list(previous_memory.get("meeting_history_ids"))
    if not history_ids:
        previous_window = previous_memory.get("meeting_window")
        if isinstance(previous_window, list):
            for row in previous_window:
                if not isinstance(row, dict):
                    continue
                mid = normalize_str(row.get("meeting_id"))
                if mid:
                    history_ids.append(mid)

    history_ids.append(meeting_id)
    return dedupe_keep_last(history_ids)


def normalize_meeting_window(
    raw_window: Any,
    meeting_id: str,
    source_file: str,
    recent_meeting_ids: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw_window, list):
        raw_window = []

    item_map: dict[str, dict[str, Any]] = {}
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
        item_map[mid] = item

    normalized_recent_ids = dedupe_keep_last(recent_meeting_ids)
    return [item_map[mid] for mid in normalized_recent_ids if mid in item_map]


def _raw_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _merge_patch_row(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in patch.items():
        merged[key] = value
    return merged


def _changed_fields(
    before: dict[str, Any],
    after: dict[str, Any],
    ignored_keys: set[str] | None = None,
) -> list[str]:
    ignored = ignored_keys or set()
    keys = (set(before) | set(after)) - ignored
    return sorted(key for key in keys if before.get(key) != after.get(key))


def _next_history_version(history: Any) -> int:
    if not isinstance(history, list):
        return 1
    max_version = 0
    for row in history:
        if not isinstance(row, dict):
            continue
        try:
            max_version = max(max_version, int(row.get("version", 0) or 0))
        except (TypeError, ValueError):
            continue
    return max_version + 1


def _combine_history_change_text(*changes: Any) -> str:
    segments: list[str] = []
    updated_fields: set[str] = set()

    for change in changes:
        for segment in normalize_str(change).split(";"):
            segment = segment.strip()
            if not segment:
                continue
            if segment.startswith("updated fields:"):
                fields_text = segment.removeprefix("updated fields:").strip()
                for field in fields_text.split(","):
                    field = field.strip()
                    if field and field != "content":
                        updated_fields.add(field)
                continue
            if segment not in segments:
                segments.append(segment)

    if updated_fields:
        segments.append(f"updated fields: {', '.join(sorted(updated_fields))}")
    return "; ".join(segments) if segments else "updated"


def _history_change_with_fields(existing_change: Any, changed_fields: list[str]) -> str:
    fields_text = ", ".join(changed_fields) if changed_fields else "content"
    return _combine_history_change_text(
        existing_change,
        f"updated fields: {fields_text}",
    )


def _collapse_action_history_by_meeting(
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    collapsed: list[dict[str, Any]] = []
    index_by_meeting_id: dict[str, int] = {}

    for row in history:
        meeting_id = normalize_str(row.get("meeting_id"))
        if not meeting_id:
            continue

        if meeting_id in index_by_meeting_id:
            existing = collapsed[index_by_meeting_id[meeting_id]]
            existing["change"] = _combine_history_change_text(
                existing.get("change"),
                row.get("change"),
            )
            continue

        index_by_meeting_id[meeting_id] = len(collapsed)
        collapsed.append(
            {
                "version": 0,
                "meeting_id": meeting_id,
                "change": normalize_str(row.get("change"), "updated"),
            }
        )

    for version, row in enumerate(collapsed):
        row["version"] = version
    return collapsed


def _append_action_history(
    item: dict[str, Any],
    meeting_id: str,
    changed_fields: list[str],
) -> dict[str, Any]:
    updated = deepcopy(item)
    history = updated.get("history")
    if not isinstance(history, list):
        history = []
    else:
        history = [row for row in history if isinstance(row, dict)]
    history = _collapse_action_history_by_meeting(history)

    for index in range(len(history) - 1, -1, -1):
        if normalize_str(history[index].get("meeting_id")) != meeting_id:
            continue
        history[index]["change"] = _history_change_with_fields(
            history[index].get("change"),
            changed_fields,
        )
        updated["history"] = history
        return updated

    fields_text = ", ".join(changed_fields) if changed_fields else "content"
    history.append(
        {
            "version": _next_history_version(history),
            "meeting_id": meeting_id,
            "change": f"updated fields: {fields_text}",
        }
    )
    updated["history"] = history
    return updated


def _normalize_one_action_item(row: dict[str, Any], meeting_id: str) -> dict[str, Any]:
    return normalize_action_items([row], meeting_id)[0]


def _normalize_one_method_change(row: dict[str, Any], meeting_id: str) -> dict[str, Any]:
    return normalize_method_changes([row], meeting_id)[0]


def _normalize_one_experiment_todo(
    row: dict[str, Any], meeting_id: str
) -> dict[str, Any]:
    return normalize_experiment_todos([row], meeting_id)[0]


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
            history = _collapse_action_history_by_meeting(history)
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


def filter_recent_action_items(
    items: list[dict[str, Any]],
    recent_meeting_ids: list[str],
) -> list[dict[str, Any]]:
    recent_set = set(recent_meeting_ids)
    filtered: list[dict[str, Any]] = []
    for item in items:
        created_meeting_id = normalize_str(item.get("created_meeting_id"))
        last_updated_meeting_id = normalize_str(item.get("last_updated_meeting_id"))
        history_rows = item.get("history")
        history_meeting_ids: list[str] = []
        if isinstance(history_rows, list):
            for row in history_rows:
                if not isinstance(row, dict):
                    continue
                history_mid = normalize_str(row.get("meeting_id"))
                if history_mid:
                    history_meeting_ids.append(history_mid)

        if (
            created_meeting_id in recent_set
            or last_updated_meeting_id in recent_set
            or any(mid in recent_set for mid in history_meeting_ids)
        ):
            filtered.append(item)
    return filtered


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
        raw_id = normalize_str(row.get("todo_id")) or normalize_str(row.get("item_id"))
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


def merge_meeting_window_patch(
    previous_window: Any,
    updated_window: Any,
    meeting_id: str,
    source_file: str,
    recent_meeting_ids: list[str],
) -> list[dict[str, Any]]:
    previous_rows = normalize_meeting_window(
        previous_window,
        meeting_id,
        source_file,
        recent_meeting_ids,
    )
    row_map = {row["meeting_id"]: row for row in previous_rows}

    for patch in _raw_rows(updated_window):
        mid = normalize_str(patch.get("meeting_id"))
        if not mid:
            continue
        base = row_map.get(mid, {"meeting_id": mid})
        row_map[mid] = normalize_meeting_window(
            [_merge_patch_row(base, patch)],
            meeting_id,
            source_file,
            [mid],
        )[0]

    normalized_recent_ids = dedupe_keep_last(recent_meeting_ids)
    return [row_map[mid] for mid in normalized_recent_ids if mid in row_map]


def merge_action_item_patch(
    previous_items: Any,
    updated_items: Any,
    meeting_id: str,
) -> list[dict[str, Any]]:
    normalized_previous = normalize_action_items(previous_items, meeting_id)
    item_map = {item["item_id"]: item for item in normalized_previous}
    used_ids = set(item_map)

    for patch in _raw_rows(updated_items):
        raw_id = normalize_str(patch.get("item_id"))
        is_existing = raw_id in item_map
        item_id = raw_id
        if not item_id or (item_id in used_ids and not is_existing):
            item_id = next_seq_id("A", used_ids)
        used_ids.add(item_id)

        patch_with_id = dict(patch)
        patch_with_id["item_id"] = item_id

        if is_existing:
            before = item_map[item_id]
            merged_row = _merge_patch_row(before, patch_with_id)
            normalized = _normalize_one_action_item(merged_row, meeting_id)
            changed = _changed_fields(
                before,
                normalized,
                ignored_keys={"history", "last_updated_meeting_id"},
            )
            if changed and "last_updated_meeting_id" not in patch:
                normalized["last_updated_meeting_id"] = meeting_id
            if changed and "history" not in patch:
                normalized = _append_action_history(normalized, meeting_id, changed)
            item_map[item_id] = normalized
            continue

        item_map[item_id] = _normalize_one_action_item(patch_with_id, meeting_id)

    return list(item_map.values())


def merge_method_change_patch(
    previous_items: Any,
    updated_items: Any,
    meeting_id: str,
) -> list[dict[str, Any]]:
    normalized_previous = normalize_method_changes(previous_items, meeting_id)
    item_map = {item["change_id"]: item for item in normalized_previous}
    used_ids = set(item_map)

    for patch in _raw_rows(updated_items):
        raw_id = normalize_str(patch.get("change_id"))
        is_existing = raw_id in item_map
        change_id = raw_id
        if not change_id or (change_id in used_ids and not is_existing):
            change_id = next_seq_id("M", used_ids)
        used_ids.add(change_id)

        patch_with_id = dict(patch)
        patch_with_id["change_id"] = change_id
        if is_existing:
            patch_with_id = _merge_patch_row(item_map[change_id], patch_with_id)
        item_map[change_id] = _normalize_one_method_change(patch_with_id, meeting_id)

    return list(item_map.values())


def merge_experiment_todo_patch(
    previous_items: Any,
    updated_items: Any,
    meeting_id: str,
) -> list[dict[str, Any]]:
    normalized_previous = normalize_experiment_todos(previous_items, meeting_id)
    item_map = {item["todo_id"]: item for item in normalized_previous}
    used_ids = set(item_map)

    for patch in _raw_rows(updated_items):
        raw_id = normalize_str(patch.get("todo_id")) or normalize_str(
            patch.get("item_id")
        )
        is_existing = raw_id in item_map
        todo_id = raw_id
        if not todo_id or (todo_id in used_ids and not is_existing):
            todo_id = next_seq_id("E", used_ids)
        used_ids.add(todo_id)

        patch_with_id = dict(patch)
        patch_with_id["todo_id"] = todo_id
        if is_existing:
            before = item_map[todo_id]
            merged_row = _merge_patch_row(before, patch_with_id)
            normalized = _normalize_one_experiment_todo(merged_row, meeting_id)
            changed = _changed_fields(
                before,
                normalized,
                ignored_keys={"meeting_id"},
            )
            if changed and "meeting_id" not in patch:
                normalized["meeting_id"] = meeting_id
            item_map[todo_id] = normalized
            continue

        item_map[todo_id] = _normalize_one_experiment_todo(patch_with_id, meeting_id)

    return list(item_map.values())


def remove_dangling_experiment_action_refs(
    todos: list[dict[str, Any]],
    action_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    action_ids = {
        normalize_str(item.get("item_id"))
        for item in action_items
        if isinstance(item, dict) and normalize_str(item.get("item_id"))
    }
    cleaned: list[dict[str, Any]] = []
    for todo in todos:
        updated = deepcopy(todo)
        updated["related_action_item_ids"] = [
            action_id
            for action_id in normalize_str_list(todo.get("related_action_item_ids"))
            if action_id in action_ids
        ]
        cleaned.append(updated)
    return cleaned


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

    meeting_history_ids = normalize_meeting_history_ids(previous_memory, meeting_id)
    recent_meeting_ids = meeting_history_ids[-3:]

    meeting_window = merge_meeting_window_patch(
        previous_memory.get("meeting_window"),
        updated_memory.get("meeting_window"),
        meeting_id,
        source_file,
        recent_meeting_ids,
    )

    action_items = merge_action_item_patch(
        previous_memory.get("action_items"),
        updated_memory.get("action_items"),
        meeting_id,
    )
    method_changes = merge_method_change_patch(
        previous_memory.get("method_changes"),
        updated_memory.get("method_changes"),
        meeting_id,
    )
    experiment_todos = merge_experiment_todo_patch(
        previous_memory.get("experiment_todos"),
        updated_memory.get("experiment_todos"),
        meeting_id,
    )

    merged["memory_version"] = version
    merged["last_updated_utc"] = utc_now_iso()
    merged["last_updated_meeting_id"] = meeting_id
    merged["meeting_history_ids"] = meeting_history_ids
    merged["meeting_window"] = meeting_window
    merged["action_items"] = filter_recent_action_items(
        action_items,
        recent_meeting_ids,
    )
    merged["method_changes"] = method_changes
    merged["experiment_todos"] = remove_dangling_experiment_action_refs(
        experiment_todos,
        merged["action_items"],
    )

    next_focus = normalize_str_list(merged.get("next_meeting_focus"))
    if not next_focus:
        next_focus = normalize_str_list(previous_memory.get("next_meeting_focus"))
    merged["next_meeting_focus"] = next_focus
    return merged
