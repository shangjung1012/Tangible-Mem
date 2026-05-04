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


def _row_key(row: dict[str, Any]) -> str:
    for id_key in ("meeting_id", "item_id", "change_id", "todo_id"):
        value = str(row.get(id_key, "")).strip()
        if value:
            return f"{id_key}:{value}"
    return json.dumps(row, ensure_ascii=False, sort_keys=True)
