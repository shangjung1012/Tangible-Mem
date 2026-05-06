"""Activity sidecar helpers for long-term L1 memory objects.

Activity is a ranking and summarization signal only.  It never changes
canonical L1 importance and never deletes memory objects from tree.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from io_utils import save_json
from l1_quality import l1_quality_hashes

MEMORY_ACTIVITY_SCHEMA_VERSION = 1
TYPE_DECAY_DAYS = {
    "todo": 30,
    "open_question": 90,
    "result": 180,
    "argument": 180,
    "decision": 720,
    "method_change": 720,
}
TYPE_ACTIVITY_FLOORS = {
    "todo": 0.15,
    "open_question": 0.25,
    "result": 0.35,
    "argument": 0.35,
    "decision": 0.65,
    "method_change": 0.65,
}
REACTIVATING_RELATIONS = {"continues", "reactivates", "repeats", "supports"}
RESOLVING_RELATIONS = {"resolves", "supersedes"}
MIN_RELATION_BOOST_CONFIDENCE = 0.70

_CORE_CONTEXT_TERMS = (
    "agent architecture",
    "architectural design",
    "benchmarking",
    "baseline comparison",
    "chunking",
    "data handling strategy",
    "demo",
    "demonstration",
    "evaluation",
    "evaluation methods",
    "evaluation strategy",
    "function calling",
    "idea unit",
    "idea units",
    "information entropy",
    "item tracking",
    "long-term memory",
    "long term memory",
    "memory architecture",
    "memory management",
    "memory retrieval",
    "model evaluation",
    "project evaluation criteria",
    "rag",
    "recall",
    "relative time",
    "retrieval",
    "segmentation",
    "short-term memory",
    "system architecture",
    "tool calling",
    "transcript",
    "working memory",
    "三層",
    "函式呼叫",
    "分塊",
    "切分",
    "想法單元",
    "證明",
    "展示",
    "記憶",
    "長期記憶",
    "短期記憶",
    "評估",
    "檢索",
    "架構",
)
_OPERATIONAL_CONTEXT_TERMS = (
    "api key",
    "api金鑰",
    "budget",
    "credit card",
    "google帳戶",
    "project budget",
    "免費額度",
    "信用卡",
    "實驗室財務",
    "帳戶",
)


def memory_activity_default_path(tree_path: Path) -> Path:
    return tree_path.parent / "memory_activity_index.json"


def load_memory_activity_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid memory activity index JSON: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Memory activity index must be a JSON object: {path}")
    return data


def save_memory_activity_index(path: Path, activity_index: dict[str, Any]) -> None:
    save_json(path, activity_index)


def remove_memory_activity_for_meeting(path: Path, meeting_id: str) -> dict[str, Any]:
    existing = load_memory_activity_index(path)
    if not existing:
        return existing
    prefix = f"L1-{meeting_id}-"
    filtered: dict[str, Any] = {}
    changed = False
    for obj_id, meta in existing.items():
        if not isinstance(meta, dict):
            changed = True
            continue
        if str(meta.get("meeting_id", "")).strip() == meeting_id:
            changed = True
            continue
        reactivated_by = meta.get("reactivated_by", [])
        if isinstance(reactivated_by, list):
            kept_sources = [
                str(source)
                for source in reactivated_by
                if not str(source).startswith(prefix)
            ]
            if kept_sources != reactivated_by:
                meta = {**meta, "reactivated_by": kept_sources}
                changed = True
        filtered[str(obj_id)] = meta
    if changed:
        save_memory_activity_index(path, filtered)
    return filtered


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _meeting_datetime(meeting: dict[str, Any]) -> datetime | None:
    return _parse_datetime(str(meeting.get("meeting_date", "") or meeting.get("timestamp", "")))


def base_activation_for_obj(
    obj: dict[str, Any],
    meeting: dict[str, Any],
    *,
    now: datetime | None = None,
) -> float:
    """Compute type-aware activity decay without changing importance."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    obj_type = str(obj.get("type", "") or "").lower()
    decay_days = max(1, TYPE_DECAY_DAYS.get(obj_type, 180))
    floor = TYPE_ACTIVITY_FLOORS.get(obj_type, 0.25)
    meeting_dt = _meeting_datetime(meeting)
    if meeting_dt is None:
        return max(floor, 0.55)
    elapsed_days = max(0, (now - meeting_dt).days)
    try:
        importance = float(obj.get("importance") or 0.0)
    except (TypeError, ValueError):
        importance = 0.0
    high_importance_bonus = 0.08 if importance >= 0.8 else 0.0
    if _is_durable_context_memory(obj, importance=importance):
        # A high-importance research thread may be temporarily inactive, but it
        # should not collapse to the same floor as one-off operational todos.
        floor = max(floor, 0.46 if obj_type == "todo" else 0.42)
        high_importance_bonus = max(high_importance_bonus, 0.06)
    activation = max(floor, 1.0 - elapsed_days / decay_days + high_importance_bonus)
    return round(max(0.0, min(1.0, activation)), 3)


def _obj_context_text(obj: dict[str, Any]) -> str:
    raw_topics = obj.get("related_topics", [])
    topics = " ".join(str(topic) for topic in raw_topics) if isinstance(raw_topics, list) else ""
    return " ".join(
        [
            str(obj.get("type", "") or ""),
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
            topics,
        ]
    ).lower()


def _is_durable_context_memory(
    obj: dict[str, Any],
    *,
    importance: float | None = None,
) -> bool:
    """Return True for old research threads that should fade gently.

    This deliberately excludes project logistics.  The goal is to preserve
    access to durable architecture/evaluation context without keeping stale API
    keys, budgets, or one-off setup tasks active.
    """
    obj_type = str(obj.get("type", "") or "").lower()
    if obj_type not in {"todo", "open_question", "result", "argument"}:
        return False
    if importance is None:
        try:
            importance = float(obj.get("importance") or 0.0)
        except (TypeError, ValueError):
            importance = 0.0
    if importance < 0.65:
        return False
    text = _obj_context_text(obj)
    if any(term in text for term in _OPERATIONAL_CONTEXT_TERMS):
        return False
    return any(term in text for term in _CORE_CONTEXT_TERMS)


def _state_for_activation(activation: float) -> str:
    if activation >= 0.72:
        return "active"
    if activation >= 0.40:
        return "fading"
    return "dormant"


def _valid_existing_meta(
    obj: dict[str, Any],
    existing_index: dict[str, Any],
) -> dict[str, Any]:
    obj_id = str(obj.get("obj_id", "")).strip()
    meta = existing_index.get(obj_id)
    if not isinstance(meta, dict):
        return {}
    expected = l1_quality_hashes(obj)
    if (
        meta.get("content_hash") != expected["content_hash"]
        or meta.get("evidence_hash") != expected["evidence_hash"]
    ):
        return {}
    return dict(meta)


def _relations_by_target(
    relation_updates: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    by_target: dict[str, list[dict[str, Any]]] = {}
    for source_obj_id, relations in (relation_updates or {}).items():
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            target_obj_id = str(relation.get("target_obj_id", "")).strip()
            if not target_obj_id:
                continue
            by_target.setdefault(target_obj_id, []).append(
                {**relation, "source_obj_id": str(source_obj_id)}
            )
    return by_target


def build_memory_activity_update(
    *,
    tree: dict[str, Any],
    meeting_id: str,
    existing_index: dict[str, Any] | None = None,
    relation_updates: dict[str, list[dict[str, Any]]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh activity metadata for all current tree L1 objects."""
    now = now or datetime.now(timezone.utc)
    existing = existing_index or {}
    by_target = _relations_by_target(relation_updates)
    refreshed: dict[str, Any] = {}
    source_touch_date = ""
    for meeting in tree.get("meetings", []):
        if str(meeting.get("meeting_id", "")).strip() == meeting_id:
            source_touch_date = str(
                meeting.get("meeting_date", "") or meeting.get("timestamp", "")
            )
            break

    for meeting in tree.get("meetings", []):
        current_meeting_id = str(meeting.get("meeting_id", "")).strip()
        touch_date = str(meeting.get("meeting_date", "") or meeting.get("timestamp", ""))
        for obj in meeting.get("memory_objects", []):
            if not isinstance(obj, dict):
                continue
            obj_id = str(obj.get("obj_id", "")).strip()
            if not obj_id:
                continue

            activation = base_activation_for_obj(obj, meeting, now=now)
            state = _state_for_activation(activation)
            previous = _valid_existing_meta(obj, existing)
            touch_count = int(previous.get("touch_count", 0) or 0)
            last_touched_meeting_id = str(
                previous.get("last_touched_meeting_id", "") or current_meeting_id
            )
            last_touched_date = str(previous.get("last_touched_date", "") or touch_date)
            reactivated_by = (
                [
                    str(item)
                    for item in previous.get("reactivated_by", [])
                    if str(item or "").strip()
                ]
                if isinstance(previous.get("reactivated_by"), list)
                else []
            )

            if current_meeting_id == meeting_id:
                activation = max(activation, 0.86)
                state = "active"
                touch_count = max(1, touch_count + 1)
                last_touched_meeting_id = current_meeting_id
                last_touched_date = touch_date

            target_relations = by_target.get(obj_id, [])
            if target_relations:
                strong_relations = [
                    relation
                    for relation in target_relations
                    if _relation_can_update_activity(relation)
                ]
                relation_types = {
                    str(relation.get("relation", "")).strip()
                    for relation in strong_relations
                    if str(relation.get("relation", "")).strip()
                }
                if relation_types & RESOLVING_RELATIONS:
                    activation = min(max(activation, 0.28), 0.42)
                    state = "superseded" if "supersedes" in relation_types else "resolved"
                elif relation_types & REACTIVATING_RELATIONS:
                    activation = max(activation, 0.82)
                    state = "reactivated"
                elif "contradicts" in relation_types:
                    activation = max(activation, 0.68)
                    state = "active"
                if relation_types:
                    touch_count = max(1, touch_count + len(strong_relations))
                    last_touched_meeting_id = meeting_id
                    last_touched_date = source_touch_date or now.date().isoformat()
                    for relation in strong_relations:
                        source_obj_id = str(relation.get("source_obj_id", "")).strip()
                        if source_obj_id and source_obj_id not in reactivated_by:
                            reactivated_by.append(source_obj_id)

            refreshed[obj_id] = {
                "schema_version": MEMORY_ACTIVITY_SCHEMA_VERSION,
                "meeting_id": current_meeting_id,
                "type": str(obj.get("type", "") or ""),
                "activation": round(max(0.0, min(1.0, activation)), 3),
                "state": state,
                "durable_context": _is_durable_context_memory(obj),
                "last_touched_meeting_id": last_touched_meeting_id,
                "last_touched_date": last_touched_date,
                "touch_count": touch_count,
                "reactivated_by": reactivated_by[:12],
                **l1_quality_hashes(obj),
            }
    return refreshed


def _relation_can_update_activity(relation: dict[str, Any]) -> bool:
    rel_type = str(relation.get("relation", "") or "").strip()
    if rel_type not in REACTIVATING_RELATIONS | RESOLVING_RELATIONS | {"contradicts"}:
        return False
    try:
        confidence = float(relation.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence >= MIN_RELATION_BOOST_CONFIDENCE:
        return True
    shared_viewpoints = relation.get("shared_viewpoint_keys", [])
    shared_concepts = relation.get("shared_concept_keys", [])
    return bool(shared_viewpoints or shared_concepts)


def merge_memory_activity_index(path: Path, updates: dict[str, Any]) -> dict[str, Any]:
    save_memory_activity_index(path, updates)
    return updates


def _safe_meta_for_obj(
    obj: dict[str, Any],
    activity_index: dict[str, Any] | None,
) -> dict[str, Any]:
    obj_id = str(obj.get("obj_id", "")).strip()
    meta = (activity_index or {}).get(obj_id)
    if not isinstance(meta, dict):
        return {}
    expected = l1_quality_hashes(obj)
    if (
        meta.get("content_hash") != expected["content_hash"]
        or meta.get("evidence_hash") != expected["evidence_hash"]
    ):
        return {}
    return meta


def activity_score_for_obj(
    obj: dict[str, Any],
    activity_index: dict[str, Any] | None,
) -> tuple[float | None, str]:
    meta = _safe_meta_for_obj(obj, activity_index)
    if not meta:
        return None, "unknown"
    activation = meta.get("activation")
    state = str(meta.get("state") or "unknown")
    if isinstance(activation, int | float):
        return max(0.0, min(1.0, float(activation))), state
    return None, state


def format_memory_activity_tag(
    obj: dict[str, Any],
    activity_index: dict[str, Any] | None,
) -> str:
    activation, state = activity_score_for_obj(obj, activity_index)
    if activation is None:
        return "activity=unknown"
    return f"activity={state} activation={activation:.2f}"


def adjust_recall_score_for_activity(
    *,
    score: float,
    semantic_score: float,
    activation: float | None,
    state: str,
) -> float:
    adjusted = float(score)
    clean_state = str(state or "").lower()
    if activation is None:
        return round(max(0.0, min(1.0, adjusted)), 4)
    if clean_state in {"resolved", "superseded"} and semantic_score < 0.86:
        adjusted -= 0.08
    elif activation < 0.35 and semantic_score < 0.82:
        adjusted -= 0.06
    elif activation >= 0.78 and clean_state in {"active", "reactivated"}:
        adjusted += 0.03
    return round(max(0.0, min(1.0, adjusted)), 4)
