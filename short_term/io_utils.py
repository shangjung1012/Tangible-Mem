from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import DEFAULT_MEMORY, MEMORY_SCHEMA_VERSION


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON file: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"JSON file must contain an object: {path}")
    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = normalize_str(item)
        if text and text not in output:
            output.append(text)
    return output


def dedupe_keep_order(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        clean = normalize_str(value)
        if clean and clean not in output:
            output.append(clean)
    return output


def load_short_term_memory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(DEFAULT_MEMORY)
    raw = load_json_object(path)
    memory = deepcopy(DEFAULT_MEMORY)
    memory.update(raw)
    memory["schema_version"] = MEMORY_SCHEMA_VERSION
    memory["meeting_history_ids"] = normalize_str_list(memory.get("meeting_history_ids"))
    units = memory.get("units", [])
    memory["units"] = [unit for unit in units if isinstance(unit, dict)]
    return memory

