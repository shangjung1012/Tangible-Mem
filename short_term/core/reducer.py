from __future__ import annotations

import json
import re
from typing import Any


INTERNAL_KEYS = {
    "operation",
    "confidence",
    "evidence_lines",
    "evidence_quote",
    "note",
    "warnings",
}
ID_PATTERNS = {
    "item_id": re.compile(r"^A\d{3}$"),
    "change_id": re.compile(r"^M\d{3}$"),
    "todo_id": re.compile(r"^E\d{3}$"),
}


def reduce_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    patch: dict[str, Any] = {}

    for section in (
        "meeting_window",
        "action_items",
        "method_changes",
        "experiment_todos",
        "next_meeting_focus",
    ):
        rows = [
            candidate
            for candidate in candidates
            if candidate.get("section") == section
            and isinstance(candidate.get("payload"), dict)
            and str(candidate.get("operation") or candidate.get("payload", {}).get("operation") or "") != "no_op"
        ]
        if not rows:
            continue
        if section == "next_meeting_focus":
            patch[section] = _dedupe_strings(
                str(row["payload"].get("text", "")).strip()
                for row in rows
                if str(row["payload"].get("text", "")).strip()
            )
            continue
        if section == "meeting_window":
            patch[section] = _merge_meeting_window_rows(
                [_clean_payload(row["payload"]) for row in rows]
            )
            continue
        patch[section] = _dedupe_rows([_clean_payload(row["payload"]) for row in rows])

    return patch


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = {
        key: value
        for key, value in payload.items()
        if key not in INTERNAL_KEYS and value is not None
    }
    for id_key, pattern in ID_PATTERNS.items():
        if id_key not in cleaned:
            continue
        value = str(cleaned[id_key]).strip()
        if not value or not pattern.fullmatch(value):
            cleaned.pop(id_key, None)
    return cleaned


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = _row_key(row)
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _merge_meeting_window_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_meeting_id: dict[str, int] = {}

    for row in rows:
        if _is_no_op_meeting_summary(row):
            continue
        meeting_id = str(row.get("meeting_id", "")).strip()
        if not meeting_id:
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        else:
            key = meeting_id

        if key not in index_by_meeting_id:
            index_by_meeting_id[key] = len(merged)
            clean = dict(row)
            clean["key_points"] = _dedupe_strings(clean.get("key_points", []))
            clean["open_questions"] = _dedupe_strings(clean.get("open_questions", []))
            merged.append(clean)
            continue

        existing = merged[index_by_meeting_id[key]]
        existing["summary"] = _join_distinct_texts(
            existing.get("summary"),
            row.get("summary"),
        )
        existing["key_points"] = _dedupe_strings(
            list(existing.get("key_points", [])) + list(row.get("key_points", []))
            if isinstance(row.get("key_points"), list)
            else list(existing.get("key_points", []))
        )
        existing["open_questions"] = _dedupe_strings(
            list(existing.get("open_questions", []))
            + list(row.get("open_questions", []))
            if isinstance(row.get("open_questions"), list)
            else list(existing.get("open_questions", []))
        )
        existing["evidence"] = _join_evidence(existing.get("evidence"), row.get("evidence"))
        if not str(existing.get("source_file", "")).strip() and row.get("source_file"):
            existing["source_file"] = row.get("source_file")

    return merged


def _dedupe_strings(values: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        output.append(clean)
    return output


def _join_distinct_texts(*values: Any) -> str:
    return " ".join(_dedupe_strings(str(value).strip() for value in values if value))


def _join_evidence(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        for part in str(value or "").split(","):
            clean = part.strip()
            if clean:
                parts.append(clean)
    return ", ".join(_dedupe_strings(parts))


def _is_no_op_meeting_summary(row: dict[str, Any]) -> bool:
    summary = str(row.get("summary", "")).strip().casefold()
    return summary.startswith("no_op") or summary.startswith("no update")


def _row_key(row: dict[str, Any]) -> str:
    for id_key in ("meeting_id", "item_id", "change_id", "todo_id"):
        value = str(row.get(id_key, "")).strip()
        if value:
            return f"{id_key}:{value}"
    return json.dumps(row, ensure_ascii=False, sort_keys=True)
