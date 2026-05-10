from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_PATH = Path(__file__).resolve().parents[1] / "short_term_memory.json"
DEFAULT_L1_INDEX_PATH = Path(__file__).resolve().parents[2] / "share_mem" / "l1_index.json"
INACTIVE_STATUSES = {"resolved", "superseded", "inactive", "archived"}
ACTIVE_SOURCE_MEETING_WINDOW = 3
ACTIVE_SOURCE_MAX_IDS = 30
SOURCE_QUERY_STOP_TERMS = {
    "l1",
    "l2",
    "l3",
    "memory",
    "meeting",
    "目前",
    "現在",
    "什麼",
    "怎麼",
    "是什",
    "是什麼",
}


def _load_memory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_l1_index(path: Path) -> dict[str, Any]:
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


def _status(unit: dict[str, Any]) -> str:
    return str(unit.get("status", "active") or "active").strip().lower()


def _is_active_unit(unit: dict[str, Any]) -> bool:
    return _status(unit) not in INACTIVE_STATUSES


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def _source_meeting_id(obj_id: str) -> str:
    match = re.match(r"^L1-([^-]+)-", str(obj_id or "").strip())
    return match.group(1) if match else ""


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe([str(item) for item in value])


def _source_ids_for_prompt(memory: dict[str, Any], unit: dict[str, Any]) -> tuple[list[str], int, str]:
    active_source_ids = _normalize_str_list(unit.get("active_source_obj_ids"))
    historical_source_ids = _normalize_str_list(unit.get("historical_source_obj_ids"))
    if active_source_ids:
        return active_source_ids[:ACTIVE_SOURCE_MAX_IDS], len(historical_source_ids), "active"

    source_ids = _normalize_str_list(unit.get("source_obj_ids"))
    meeting_history = _normalize_str_list(memory.get("meeting_history_ids"))
    if not source_ids or not meeting_history:
        return source_ids[:ACTIVE_SOURCE_MAX_IDS], 0, "legacy_all"

    recent_meetings = set(meeting_history[-ACTIVE_SOURCE_MEETING_WINDOW:])
    derived_active: list[str] = []
    derived_historical: list[str] = []
    for obj_id in source_ids:
        meeting_id = _source_meeting_id(obj_id)
        if not meeting_id or meeting_id in recent_meetings:
            derived_active.append(obj_id)
        else:
            derived_historical.append(obj_id)
    if len(derived_active) > ACTIVE_SOURCE_MAX_IDS:
        overflow = derived_active[:-ACTIVE_SOURCE_MAX_IDS]
        derived_active = derived_active[-ACTIVE_SOURCE_MAX_IDS:]
        derived_historical = _dedupe(derived_historical + overflow)
    return derived_active, len(derived_historical), "derived_recent_active"


def _source_query_terms(query: str) -> list[str]:
    base_terms = set(_query_terms(query))
    has_ascii_anchor = any(any(ch.isascii() and ch.isalnum() for ch in term) for term in base_terms)
    if has_ascii_anchor:
        terms = {
            term
            for term in base_terms
            if any(ch.isascii() and ch.isalnum() for ch in term)
        }
    else:
        terms = set(base_terms)
    cjk_run = ""
    if not has_ascii_anchor:
        for ch in str(query or ""):
            if "\u4e00" <= ch <= "\u9fff":
                cjk_run += ch
                continue
            if len(cjk_run) >= 2:
                terms.update(_ngrams(cjk_run))
            cjk_run = ""
        if len(cjk_run) >= 2:
            terms.update(_ngrams(cjk_run))
    terms = {term for term in terms if term.lower() not in SOURCE_QUERY_STOP_TERMS}
    return sorted(terms, key=lambda term: (-len(term), term))


def _ngrams(text: str) -> set[str]:
    grams: set[str] = set()
    for size in (2, 3, 4):
        if len(text) < size:
            continue
        grams.update(text[index : index + size] for index in range(len(text) - size + 1))
    return grams


def _unit_text(unit: dict[str, Any]) -> str:
    fields = [
        str(unit.get("unit_id", "") or ""),
        str(unit.get("title", "") or ""),
        str(unit.get("summary", "") or ""),
        str(unit.get("current_state", "") or ""),
        str(unit.get("role", "") or ""),
        str(unit.get("status", "") or ""),
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


def _l1_text(obj_id: str, l1_index: dict[str, Any]) -> str:
    record = l1_index.get(obj_id, {})
    if not isinstance(record, dict):
        record = {}
    fields = [
        obj_id,
        str(record.get("meeting_id", "") or ""),
        str(record.get("type", "") or ""),
        str(record.get("content", "") or ""),
        str(record.get("evidence", "") or ""),
    ]
    for key in ("topics", "related_topics"):
        values = record.get(key, [])
        if isinstance(values, list):
            fields.append(" ".join(str(value) for value in values if str(value).strip()))
    return " ".join(fields).lower().replace("_", " ").replace("-", " ")


def _source_score(obj_id: str, query_terms: list[str], l1_index: dict[str, Any]) -> int:
    haystack = _l1_text(obj_id, l1_index)
    return sum(1 for term in query_terms if term.lower() in haystack)


def _rank_source_ids(
    source_ids: list[str],
    query: str,
    *,
    l1_index: dict[str, Any],
    source_preview_limit: int,
) -> list[str]:
    preview_limit = max(1, source_preview_limit)
    query_terms = _source_query_terms(query)
    if not l1_index or not query_terms:
        return source_ids[:preview_limit]

    scored = [
        (_source_score(obj_id, query_terms, l1_index), index, obj_id)
        for index, obj_id in enumerate(source_ids)
    ]
    if not any(score > 0 for score, _, _ in scored):
        return source_ids[:preview_limit]
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [obj_id for _, _, obj_id in scored[:preview_limit]]


def _rank_units(memory: dict[str, Any], query: str, top_k: int) -> list[tuple[float, dict[str, Any]]]:
    units = memory.get("units", [])
    if not isinstance(units, list):
        return []
    query_terms = _query_terms(query)
    scored = [
        (round(_unit_score(unit, query_terms), 4), unit)
        for unit in units
        if isinstance(unit, dict) and _is_active_unit(unit)
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
    query: str,
    l1_index: dict[str, Any],
    max_context_chars: int,
    source_preview_limit: int,
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
        if unit.get("role"):
            parts.append(f"  role: {unit['role']}")
        if unit.get("status"):
            parts.append(f"  status: {unit['status']}")
        if unit.get("last_updated_meeting_id"):
            parts.append(f"  last_updated_meeting_id: {unit['last_updated_meeting_id']}")
        if unit.get("missed_meeting_count") is not None:
            parts.append(f"  missed_meeting_count: {unit['missed_meeting_count']}")
        source_ids, historical_source_count, source_scope = _source_ids_for_prompt(memory, unit)
        if source_ids:
            normalized_source_ids = [str(obj_id) for obj_id in source_ids if str(obj_id).strip()]
            preview = _rank_source_ids(
                normalized_source_ids,
                query,
                l1_index=l1_index,
                source_preview_limit=source_preview_limit,
            )
            suffix = " ..." if len(source_ids) > len(preview) else ""
            parts.append(f"  active_source_count: {len(normalized_source_ids)}")
            if historical_source_count:
                parts.append(f"  historical_source_count: {historical_source_count}")
            legacy_source_ids = unit.get("source_obj_ids", [])
            if isinstance(legacy_source_ids, list) and legacy_source_ids:
                parts.append(f"  total_source_count: {len(legacy_source_ids)}")
            legacy_count = len(legacy_source_ids) if isinstance(legacy_source_ids, list) else 0
            if max(len(normalized_source_ids), legacy_count) > 80:
                parts.append("  source_note: broad unit; source L1 preview is query-ranked")
            parts.append(f"  source_scope: {source_scope}")
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
    top_k: int = 4,
    max_context_chars: int = 4000,
    memory_path: Path | str = DEFAULT_MEMORY_PATH,
    l1_index_path: Path | str = DEFAULT_L1_INDEX_PATH,
    source_preview_limit: int = 16,
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
    l1_index = _load_l1_index(Path(l1_index_path))
    return _format_context(
        memory,
        ranked,
        query=query,
        l1_index=l1_index,
        max_context_chars=max_context_chars,
        source_preview_limit=source_preview_limit,
    )
