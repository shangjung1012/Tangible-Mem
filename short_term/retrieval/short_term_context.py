from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_PATH = Path(__file__).resolve().parents[1] / "short_term_memory.json"


def _load_memory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _query_terms(query: str) -> list[str]:
    normalized = "".join(
        ch.lower() if ch.isalnum() else " "
        for ch in str(query or "").replace("_", " ").replace("-", " ")
    )
    return [part for part in normalized.split() if len(part) >= 2]


def _unit_text(unit: dict[str, Any]) -> str:
    fields = [
        str(unit.get("unit_id", "") or ""),
        str(unit.get("title", "") or ""),
        str(unit.get("summary", "") or ""),
    ]
    for key in ("types", "related_topics"):
        values = unit.get(key, [])
        if isinstance(values, list):
            fields.append(" ".join(str(value) for value in values if str(value).strip()))
    return " ".join(fields).lower().replace("_", " ").replace("-", " ")


def _unit_score(unit: dict[str, Any], query_terms: list[str]) -> float:
    if not query_terms:
        return 0.0
    haystack = _unit_text(unit)
    hits = sum(1 for term in query_terms if term in haystack)
    if hits == 0:
        return 0.0
    try:
        missed = int(unit.get("missed_meeting_count", 0) or 0)
    except (TypeError, ValueError):
        missed = 0
    freshness = max(0.0, 1.0 - 0.25 * missed)
    return hits + freshness * 0.25


def _rank_units(memory: dict[str, Any], query: str, top_k: int) -> list[tuple[float, dict[str, Any]]]:
    units = memory.get("units", [])
    if not isinstance(units, list):
        return []
    query_terms = _query_terms(query)
    scored = [
        (round(_unit_score(unit, query_terms), 4), unit)
        for unit in units
        if isinstance(unit, dict)
    ]
    scored = [(score, unit) for score, unit in scored if score > 0]
    scored.sort(
        key=lambda row: (
            -row[0],
            int(row[1].get("missed_meeting_count", 0) or 0),
            str(row[1].get("unit_id", "")),
        )
    )
    return scored[: max(1, top_k)]


def _format_context(
    memory: dict[str, Any],
    ranked_units: list[tuple[float, dict[str, Any]]],
    *,
    max_context_chars: int,
) -> str:
    if not ranked_units:
        return "（無相關短期記憶）"

    parts = [
        "=== Short-Term Memory Retrieval ===",
        f"memory_version: {memory.get('memory_version', '')}",
        f"last_updated_meeting_id: {memory.get('last_updated_meeting_id', '')}",
    ]
    for score, unit in ranked_units:
        unit_id = str(unit.get("unit_id", "") or "?")
        title = str(unit.get("title", "") or "")
        parts.append(f"\n[{unit_id}] {title}".rstrip())
        parts.append(f"  score: {score}")
        if unit.get("summary"):
            parts.append(f"  summary: {unit['summary']}")
        if unit.get("last_updated_meeting_id"):
            parts.append(f"  last_updated_meeting_id: {unit['last_updated_meeting_id']}")
        if unit.get("missed_meeting_count") is not None:
            parts.append(f"  missed_meeting_count: {unit['missed_meeting_count']}")
        source_ids = unit.get("source_obj_ids", [])
        if isinstance(source_ids, list) and source_ids:
            preview = [str(obj_id) for obj_id in source_ids[:8]]
            suffix = " ..." if len(source_ids) > len(preview) else ""
            parts.append(f"  source L1: {', '.join(preview)}{suffix}")

    context = "\n".join(parts)
    if len(context) > max_context_chars:
        return context[:max_context_chars] + "\n...(truncated)"
    return context


def retrieve_short_term_context(
    query: str,
    api_key: str | list[str] | None = None,
    *,
    retrieval_mode: str = "hybrid",
    top_k: int = 6,
    max_context_chars: int = 4000,
    memory_path: Path | str = DEFAULT_MEMORY_PATH,
) -> str:
    """Retrieve compact context from the current short-term memory JSON.

    `api_key` and `retrieval_mode` are accepted to keep the interface stable for
    future semantic/hybrid retrieval. The current implementation is deterministic
    lexical ranking over active S-units.
    """
    del api_key, retrieval_mode
    memory = _load_memory(Path(memory_path))
    units = memory.get("units", [])
    if not memory or not isinstance(units, list) or not units:
        return "（無短期記憶）"
    ranked = _rank_units(memory, query, top_k=top_k)
    return _format_context(memory, ranked, max_context_chars=max_context_chars)
