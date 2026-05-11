"""Recall: semantic retrieval from the temporal tree + optional short-term memory."""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from embedder import EmbedCache, cosine_similarity, embed_text
from gemini_clients import create_gemini_client
from importance import normalize_importance_score
from memory_activity import (
    activity_score_for_obj,
    adjust_recall_score_for_activity,
    load_memory_activity_index,
)
from memory_relations import (
    load_memory_relations_index,
    relation_is_current,
)
from schema import DEFAULT_MODEL_NAME, EMBED_MODEL_NAME, RECALL_GATE_SCHEMA

FALLBACK_SCORE_THRESHOLD = 0.80
FALLBACK_MAX_RESULTS = 8
DEFAULT_L2_ROOT = Path(__file__).resolve().parent / "l2"
DEFAULT_L3_PROMOTIONS_PATH = Path(__file__).resolve().parent / "l3" / "l3_promotions.json"
DEFAULT_L3_VIEW_PATH = Path(__file__).resolve().parent / "l3" / "l3_view.json"
DEFAULT_L3_INDEX_PATH = Path(__file__).resolve().parent / "l3" / "l3_index.json"
TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)


# ===================================================================
# Keyword matching (still used by short-term retrieval)
# ===================================================================

def _keyword_score(text: str, keywords: list[str]) -> float:
    """Fraction of *keywords* that appear in *text* (case-insensitive)."""
    if not keywords or not text:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in text_lower)
    return hits / len(keywords)


# ===================================================================
# Scoring helpers
# ===================================================================

def _importance_score(importance: float) -> float:
    """Map importance (0.0-1.0) to [0.0, 1.0] with clamping."""
    return normalize_importance_score(importance, fallback=0.0)


def _recency_score(
    meeting_date: str,
    timestamp: str,
    obj_type: str,
    query_date: datetime,
    importance: float,
) -> float:
    """Type-specific recency decay with graceful fallback."""
    date_str = meeting_date if meeting_date else timestamp

    try:
        meeting_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.5

    if meeting_dt.tzinfo is None:
        meeting_dt = meeting_dt.replace(tzinfo=timezone.utc)
    if query_date.tzinfo is None:
        query_date = query_date.replace(tzinfo=timezone.utc)

    delta_days = max(0, (query_date - meeting_dt).days)
    high_imp = importance >= 0.8

    if obj_type in ("decision", "method_change", "approach_change", "argument"):
        return max(0.3, 1.0 - delta_days / 360)
    if obj_type in ("result", "finding", "open_question", "open_issue", "proposal"):
        floor = 0.3 if high_imp else 0.0
        return max(floor, 1.0 - delta_days / 180)
    if obj_type in ("todo", "action_item"):
        floor = 0.3 if high_imp else 0.0
        return max(floor, 1.0 - delta_days / 30)

    floor = 0.3 if high_imp else 0.0
    return max(floor, 1.0 - delta_days / 180)


def _combined_score(
    s_sem: float,
    s_recency: float,
    s_importance: float,
    w_s: float = 0.6,
    w_r: float = 0.2,
    w_i: float = 0.2,
) -> float:
    """Weighted combination for semantic retrieval."""
    return w_s * s_sem + w_r * s_recency + w_i * s_importance


def _lexical_units(text: str) -> set[str]:
    lowered = str(text or "").lower()
    units = {
        token.lower()
        for token in TOKEN_RE.findall(lowered)
        if len(token.strip()) >= 2
    }
    cjk_chars = [char for char in lowered if "\u4e00" <= char <= "\u9fff"]
    units.update("".join(cjk_chars[index : index + 2]) for index in range(max(0, len(cjk_chars) - 1)))
    return {unit for unit in units if unit.strip()}


def _lexical_score(query_units: set[str], text: str, keywords: list[str] | None = None) -> float:
    if not query_units:
        return 0.0
    lowered = str(text or "").lower().replace("-", " ")
    text_units = _lexical_units(lowered)
    overlap = len(query_units & text_units) / max(1, len(query_units))
    keyword_hits = 0
    for keyword in keywords or []:
        clean = str(keyword or "").strip().lower().replace("-", " ")
        if clean and clean in lowered:
            keyword_hits += 1
    keyword_score = min(1.0, keyword_hits / max(1, len(keywords or [])))
    return max(overlap, keyword_score)


QUERY_EXPANSION_GROUPS = [
    {
        "triggers": {"rag", "full transcript", "baseline", "lifecycle"},
        "expansions": {
            "rag",
            "full transcript",
            "逐字稿",
            "基準",
            "baseline",
            "生命週期",
            "狀態演變",
            "被否決",
            "採用",
            "轉向",
            "chunking",
        },
    },
    {
        "triggers": {"stm", "ltm", "short-term", "long-term", "routing", "route", "memory"},
        "expansions": {
            "stm",
            "ltm",
            "short-term",
            "long-term",
            "短期",
            "長期",
            "記憶",
            "平行",
            "同時",
            "更新",
            "路由",
            "routing",
            "manager",
            "agent",
        },
    },
    {
        "triggers": {"evaluation", "baseline", "metric", "metrics", "judge", "locomo", "mem0"},
        "expansions": {
            "evaluation",
            "baseline",
            "metrics",
            "judge",
            "latency",
            "token",
            "評估",
            "基準",
            "指標",
            "裁判",
            "題型",
            "正確性",
            "三類",
            "single-hop",
            "multi-hop",
            "temporal",
        },
    },
    {
        "triggers": {"forgetting", "fade", "fade-out", "activation", "decay", "floor"},
        "expansions": {
            "forgetting",
            "fade",
            "fade-out",
            "activation",
            "decay",
            "floor",
            "遺忘",
            "淡出",
            "激活",
            "重新激活",
            "非活躍",
            "衰減",
            "下限",
            "importance",
        },
    },
    {
        "triggers": {"retrieve", "retrieval", "update", "inspector", "visualization"},
        "expansions": {
            "retrieve",
            "retrieval",
            "update",
            "inspector",
            "visualization",
            "檢索",
            "更新",
            "視覺化",
            "檢查",
            "脈絡",
            "l1",
            "l2",
            "l3",
        },
    },
]


def _expand_query_terms(query: str, keywords: list[str] | None = None) -> list[str]:
    text = " ".join([str(query or ""), " ".join(str(k) for k in keywords or [])]).lower()
    normalized = text.replace("_", " ").replace("-", " ")
    expansions: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        clean = str(term or "").strip()
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            expansions.append(clean)

    for group in QUERY_EXPANSION_GROUPS:
        triggers = group["triggers"]
        if any(trigger in text or trigger.replace("-", " ") in normalized for trigger in triggers):
            for expansion in group["expansions"]:
                add(expansion)
    return expansions


def _expanded_query_units(query: str, keywords: list[str] | None = None) -> set[str]:
    expanded_terms = _expand_query_terms(query, keywords)
    return _lexical_units(" ".join([str(query or ""), " ".join(str(k) for k in keywords or []), " ".join(expanded_terms)]))


# ===================================================================
# L1 semantic search
# ===================================================================

def search_l1_semantic(
    tree: dict[str, Any],
    query_emb: list[float],
    api_key: str | list[str],
    cache: EmbedCache,
    obj_types: list[str] | None = None,
    min_importance: float = 0.0,
    top_k: int = 30,
    query_date: datetime | None = None,
    embed_model: str = EMBED_MODEL_NAME,
    activity_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search ALL L1 objects using semantic + recency + importance scoring."""
    if query_date is None:
        query_date = datetime.now(timezone.utc)

    results: list[dict[str, Any]] = []

    for meeting in tree.get("meetings", []):
        meeting_id = meeting.get("meeting_id", "")
        timestamp = meeting.get("timestamp", "")
        meeting_date = meeting.get("meeting_date", "")
        phase_id = meeting.get("phase_id", "")

        for obj in meeting.get("memory_objects", []):
            obj_type = obj.get("type", "")
            if obj_types and obj_type not in obj_types:
                continue

            try:
                importance = float(obj.get("importance") or 0.0)
            except (TypeError, ValueError):
                importance = 0.0

            if importance < min_importance:
                continue

            raw_topics = obj.get("related_topics", [])
            topics = [str(t) for t in raw_topics] if isinstance(raw_topics, list) else []
            text = " ".join(
                [
                    str(obj.get("content", "") or ""),
                    str(obj.get("evidence", "") or ""),
                    " ".join(topics),
                ]
            ).strip()
            if not text:
                continue

            obj_emb = embed_text(text, api_key, cache, model=embed_model)
            cos = cosine_similarity(query_emb, obj_emb)
            s_sem = (cos + 1.0) / 2.0
            s_recency = _recency_score(
                meeting_date, timestamp, str(obj_type), query_date, importance
            )
            s_importance = _importance_score(importance)
            base_score = _combined_score(s_sem, s_recency, s_importance)
            s_activation, activity_state = activity_score_for_obj(obj, activity_index)
            score = adjust_recall_score_for_activity(
                score=base_score,
                semantic_score=s_sem,
                activation=s_activation,
                state=activity_state,
            )

            results.append(
                {
                    "source": "long_term_l1",
                    "meeting_id": meeting_id,
                    "timestamp": timestamp,
                    "meeting_date": meeting_date,
                    "phase_id": phase_id,
                    "obj_id": obj.get("obj_id", ""),
                    "type": obj_type,
                    "legacy_type": obj.get("legacy_type", ""),
                    "content": obj.get("content", ""),
                    "importance": importance,
                    "evidence": obj.get("evidence", ""),
                    "related_topics": topics,
                    "score": round(score, 4),
                    "s_sem": round(s_sem, 4),
                    "s_recency": round(s_recency, 4),
                    "s_importance": round(s_importance, 4),
                    "s_activation": (
                        round(s_activation, 4) if s_activation is not None else None
                    ),
                    "activity_state": activity_state,
                }
            )

    results.sort(key=lambda x: -x["score"])
    return results[:top_k]


def search_l1_lexical(
    tree: dict[str, Any],
    query: str,
    *,
    keywords: list[str] | None = None,
    obj_types: list[str] | None = None,
    min_importance: float = 0.0,
    top_k: int = 30,
    query_date: datetime | None = None,
    activity_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search L1 objects with deterministic lexical scoring, no API calls."""
    if query_date is None:
        query_date = datetime.now(timezone.utc)
    expanded_keywords = [str(k) for k in keywords or []] + _expand_query_terms(query, keywords)
    query_text = " ".join([str(query or ""), " ".join(expanded_keywords)])
    query_units = _lexical_units(query_text)
    results: list[dict[str, Any]] = []

    for meeting in tree.get("meetings", []):
        meeting_id = meeting.get("meeting_id", "")
        timestamp = meeting.get("timestamp", "")
        meeting_date = meeting.get("meeting_date", "")
        phase_id = meeting.get("phase_id", "")

        for obj in meeting.get("memory_objects", []):
            obj_type = obj.get("type", "")
            if obj_types and obj_type not in obj_types:
                continue
            try:
                importance = float(obj.get("importance") or 0.0)
            except (TypeError, ValueError):
                importance = 0.0
            if importance < min_importance:
                continue
            raw_topics = obj.get("related_topics", [])
            topics = [str(t) for t in raw_topics] if isinstance(raw_topics, list) else []
            text = " ".join(
                [
                    str(obj.get("content", "") or ""),
                    str(obj.get("evidence", "") or ""),
                    " ".join(topics),
                ]
            ).strip()
            if not text:
                continue
            lexical = _lexical_score(query_units, text, keywords=expanded_keywords)
            if lexical <= 0:
                continue
            s_recency = _recency_score(
                meeting_date, timestamp, str(obj_type), query_date, importance
            )
            s_importance = _importance_score(importance)
            base_score = _combined_score(lexical, s_recency, s_importance, w_s=0.7, w_r=0.1, w_i=0.2)
            s_activation, activity_state = activity_score_for_obj(obj, activity_index)
            score = adjust_recall_score_for_activity(
                score=base_score,
                semantic_score=lexical,
                activation=s_activation,
                state=activity_state,
            )
            results.append(
                {
                    "source": "long_term_l1",
                    "meeting_id": meeting_id,
                    "timestamp": timestamp,
                    "meeting_date": meeting_date,
                    "phase_id": phase_id,
                    "obj_id": obj.get("obj_id", ""),
                    "type": obj_type,
                    "legacy_type": obj.get("legacy_type", ""),
                    "content": obj.get("content", ""),
                    "importance": importance,
                    "evidence": obj.get("evidence", ""),
                    "related_topics": topics,
                    "score": round(score, 4),
                    "s_sem": round(lexical, 4),
                    "s_recency": round(s_recency, 4),
                    "s_importance": round(s_importance, 4),
                    "s_activation": (
                        round(s_activation, 4) if s_activation is not None else None
                    ),
                    "activity_state": activity_state,
                    "retrieval_mode": "lexical",
                }
            )

    results.sort(key=lambda x: -x["score"])
    return results[:top_k]

# ===================================================================
# L2 retrieval via active share_mem-generated L2 view
# ===================================================================

def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_l2_index(path: Path | None = None) -> dict[str, Any]:
    """Load active obj_id -> L2 assignment index."""
    return _load_json_object(path or (DEFAULT_L2_ROOT / "l2_index.json"))


def load_l2_view(path: Path | None = None) -> dict[str, Any]:
    """Load active materialized L2 topic view."""
    return _load_json_object(path or (DEFAULT_L2_ROOT / "l2_view.json"))


def load_l3_promotions(path: Path | None = None) -> dict[str, Any]:
    """Load optional L3 promotion sidecar for overcrowded L2 topics."""
    return _load_json_object(path or DEFAULT_L3_PROMOTIONS_PATH)


def load_l3_view(path: Path | None = None) -> dict[str, Any]:
    """Load optional materialized L3 sidecar with child L2 assignments."""
    return _load_json_object(path or DEFAULT_L3_VIEW_PATH)


def load_l3_index(path: Path | None = None) -> dict[str, Any]:
    """Load optional obj_id -> materialized child L2 assignment index."""
    return _load_json_object(path or DEFAULT_L3_INDEX_PATH)


def _l2_nodes_by_id(l2_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = l2_view.get("l2_nodes", [])
    if not isinstance(nodes, list):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        l2_id = str(node.get("l2_id", "")).strip()
        if l2_id:
            output[l2_id] = node
    return output


def _compact_timeline_digest(
    timeline: list[Any],
    matched_l1_ids: list[str],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    matched = set(matched_l1_ids)
    compact: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    def append_entry(entry: Any) -> None:
        if not isinstance(entry, dict) or len(compact) >= max_items:
            return
        row = {
            "meeting_id": str(entry.get("meeting_id", "") or ""),
            "meeting_date": str(entry.get("meeting_date", "") or ""),
            "obj_id": str(entry.get("obj_id", "") or ""),
            "summary": str(entry.get("summary", "") or ""),
        }
        key = (row["meeting_id"], row["obj_id"], row["summary"])
        if key in seen_keys:
            return
        seen_keys.add(key)
        compact.append(row)

    for entry in timeline:
        if isinstance(entry, dict) and str(entry.get("obj_id", "") or "") in matched:
            append_entry(entry)
    for entry in timeline:
        append_entry(entry)
    return compact


def _l3_promotions_by_source_l2(
    l3_promotions: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(l3_promotions, dict):
        return {}
    rows = l3_promotions.get("promotions", [])
    if not isinstance(rows, list):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_l2_id = str(row.get("source_l2_id", "") or "").strip()
        if source_l2_id:
            output[source_l2_id] = row
    return output


def _compact_promotion_for_prompt(promotion: dict[str, Any]) -> dict[str, Any]:
    children = []
    for child in promotion.get("child_l2_candidates", []):
        if not isinstance(child, dict):
            continue
        child_l2_id = str(child.get("child_l2_id", "") or "").strip()
        if not child_l2_id:
            continue
        children.append(
            {
                "child_l2_id": child_l2_id,
                "label": str(child.get("label", "") or ""),
                "split_reason": str(child.get("split_reason", "") or ""),
            }
        )
    return {
        "l3_id": str(promotion.get("proposed_l3_id", "") or ""),
        "status": str(promotion.get("status", "") or ""),
        "source_l2_id": str(promotion.get("source_l2_id", "") or ""),
        "child_l2_candidates": children,
        "mapping": promotion.get("mapping", {}) if isinstance(promotion.get("mapping"), dict) else {},
    }


def _materialized_l3_by_source_l2(l3_view: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(l3_view, dict):
        return {}
    rows = l3_view.get("l3_nodes", [])
    if not isinstance(rows, list):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_l2_id = str(row.get("promoted_from_l2_id", "") or "").strip()
        if source_l2_id:
            output[source_l2_id] = row
    return output


def _child_l2_nodes_by_id(l3_node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = l3_node.get("child_l2_nodes", [])
    if not isinstance(rows, list):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        l2_id = str(row.get("l2_id", "") or "").strip()
        if l2_id:
            output[l2_id] = row
    return output


def _compact_materialized_l3_for_prompt(
    l3_node: dict[str, Any],
    matched_l1_ids: list[str],
    *,
    max_timeline_items: int,
) -> dict[str, Any]:
    child_lookup = _child_l2_nodes_by_id(l3_node)
    child_contexts: list[dict[str, Any]] = []
    matched = set(matched_l1_ids)
    for child_id, child in child_lookup.items():
        linked_ids = [
            str(obj_id)
            for obj_id in child.get("linked_obj_ids", [])
            if str(obj_id).strip()
        ] if isinstance(child.get("linked_obj_ids"), list) else []
        child_matched_ids = [obj_id for obj_id in linked_ids if obj_id in matched]
        if not child_matched_ids:
            continue
        timeline = child.get("timeline_digest", [])
        if not isinstance(timeline, list):
            timeline = []
        child_contexts.append(
            {
                "l2_id": child_id,
                "label": str(child.get("label", "") or ""),
                "current_state": str(child.get("current_state", "") or ""),
                "matched_l1_ids": child_matched_ids,
                "timeline_digest": _compact_timeline_digest(
                    timeline,
                    child_matched_ids,
                    max_items=max_timeline_items,
                ),
            }
        )
    return {
        "l3_id": str(l3_node.get("l3_id", "") or ""),
        "label": str(l3_node.get("label", "") or ""),
        "promoted_from_l2_id": str(l3_node.get("promoted_from_l2_id", "") or ""),
        "child_l2_contexts": child_contexts,
    }


def expand_l2_view_context(
    l1_results: list[dict[str, Any]],
    l2_index: dict[str, Any] | None,
    l2_view: dict[str, Any] | None,
    *,
    l3_promotions: dict[str, Any] | None = None,
    l3_view: dict[str, Any] | None = None,
    max_timeline_items: int = 5,
) -> list[dict[str, Any]]:
    """Expand L1 hits to compact active L2 topic context.

    This is the main upward recall path for `share_mem` L1: L1 hit -> l2_index
    assignment -> l2_view node. Missing L2 assignments are non-fatal.
    """
    if not l1_results or not l2_index or not l2_view:
        return []

    node_lookup = _l2_nodes_by_id(l2_view)
    promotion_lookup = _l3_promotions_by_source_l2(l3_promotions)
    materialized_lookup = _materialized_l3_by_source_l2(l3_view)
    expanded: dict[str, dict[str, Any]] = {}
    matched_by_l2: dict[str, list[str]] = {}
    assignments_by_l2: dict[str, list[dict[str, Any]]] = {}

    for item in l1_results:
        obj_id = str(item.get("obj_id", "") or "").strip()
        if not obj_id:
            continue
        assignment = l2_index.get(obj_id)
        if not isinstance(assignment, dict):
            continue
        l2_id = str(assignment.get("l2_id", "") or "").strip()
        if not l2_id:
            continue
        node = node_lookup.get(l2_id)
        if not node:
            continue

        matched_by_l2.setdefault(l2_id, [])
        if obj_id not in matched_by_l2[l2_id]:
            matched_by_l2[l2_id].append(obj_id)
        assignments_by_l2.setdefault(l2_id, []).append(
            {
                "obj_id": obj_id,
                "confidence": assignment.get("confidence"),
                "assignment_reason": assignment.get("assignment_reason", ""),
            }
        )
        if l2_id not in expanded:
            expanded[l2_id] = {
                "source": "long_term_l2",
                "l2_id": l2_id,
                "label": str(node.get("label") or assignment.get("l2_label") or ""),
                "current_state": str(node.get("current_state", "") or ""),
                "meeting_ids": list(node.get("meeting_ids", []))
                if isinstance(node.get("meeting_ids"), list)
                else [],
                "linked_obj_ids": list(node.get("linked_obj_ids", []))
                if isinstance(node.get("linked_obj_ids"), list)
                else [],
            }
            if l2_id in promotion_lookup:
                expanded[l2_id]["promoted_to_l3"] = _compact_promotion_for_prompt(
                    promotion_lookup[l2_id]
                )

    output: list[dict[str, Any]] = []
    for l2_id, row in expanded.items():
        matched_l1_ids = matched_by_l2.get(l2_id, [])
        node = node_lookup[l2_id]
        timeline = node.get("timeline_digest", [])
        if not isinstance(timeline, list):
            timeline = []
        row["matched_l1_ids"] = matched_l1_ids
        row["assignments"] = assignments_by_l2.get(l2_id, [])
        row["timeline_digest"] = _compact_timeline_digest(
            timeline,
            matched_l1_ids,
            max_items=max_timeline_items,
        )
        if l2_id in materialized_lookup:
            materialized = _compact_materialized_l3_for_prompt(
                materialized_lookup[l2_id],
                matched_l1_ids,
                max_timeline_items=max_timeline_items,
            )
            if materialized["child_l2_contexts"]:
                row["materialized_l3"] = materialized
        output.append(row)
    return output


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(str(text or "").lower())
        if token.strip()
    }


def _truncate_text(text: Any, max_chars: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 15)].rstrip() + "...(truncated)"


def _timeline_event_date(entry: dict[str, Any]) -> str:
    return str(entry.get("meeting_date") or entry.get("meeting_id") or "")


def _extract_meeting_hints(query: str) -> list[str]:
    text = str(query or "")
    hints: list[str] = []
    for match in re.findall(r"\b(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])\b", text):
        if match not in hints:
            hints.append(match)
    for month, day in re.findall(r"\b20\d{2}[-/](\d{2})[-/](\d{2})\b", text):
        hint = f"{month}{day}"
        if hint not in hints:
            hints.append(hint)
    return hints


def _is_evolution_query(query: str) -> bool:
    lowered = str(query or "").lower()
    if re.search(r"\bfrom\b.+\bto\b", lowered) or re.search(r"從.+到", lowered):
        return True
    chinese_markers = (
        "演進",
        "演變",
        "轉變",
        "轉折",
        "後來",
        "最後",
        "變成",
        "歷程",
        "時間線",
        "為什麼最後",
        "怎麼變",
    )
    if any(marker in lowered for marker in chinese_markers):
        return True
    if any(
        marker in lowered
        for marker in (
            "evolution",
            "evolve",
            "evolved",
            "lifecycle",
            "timeline",
            "history",
            "progression",
            "current state",
            "演變",
            "演進",
            "變化",
            "歷程",
            "脈絡",
            "生命週期",
            "怎麼變",
            "怎麼發展",
        )
    ):
        return True
    units = _lexical_units(lowered)
    return bool({"之前", "後來", "目前", "現在"} & units)


def _node_event_count(node: dict[str, Any], timeline: list[Any] | None = None) -> int:
    try:
        count = int(node.get("event_count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    if count:
        return count
    if timeline is not None:
        return len(timeline)
    linked = node.get("linked_obj_ids")
    if isinstance(linked, list):
        return len(linked)
    return 0


def _select_timeline_slice(
    timeline: list[Any],
    matched_l1_ids: list[str],
    *,
    max_events: int,
    max_event_chars: int,
    query: str = "",
) -> tuple[list[dict[str, Any]], int]:
    matched = set(matched_l1_ids)
    matched_order = {obj_id: index for index, obj_id in enumerate(matched_l1_ids)}
    rows = [row for row in timeline if isinstance(row, dict)]
    rows.sort(key=_timeline_event_date)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(row: dict[str, Any]) -> None:
        if len(selected) >= max_events:
            return
        obj_id = str(row.get("obj_id", "") or "")
        key = obj_id or f"{row.get('meeting_id', '')}:{row.get('summary', '')}"
        if key in seen:
            return
        seen.add(key)
        selected.append(
            {
                "meeting_id": str(row.get("meeting_id", "") or ""),
                "meeting_date": str(row.get("meeting_date", "") or ""),
                "obj_id": obj_id,
                "summary": _truncate_text(row.get("summary", row.get("content", "")), max_event_chars),
            }
        )

    matched_rows = [row for row in rows if str(row.get("obj_id", "") or "") in matched]
    if _is_evolution_query(query) and max_events > 1:
        query_units = _expanded_query_units(query)

        def evolution_relevance(row: dict[str, Any]) -> float:
            text = str(row.get("summary", row.get("content", "")) or "")
            lowered_text = text.lower()
            base_score = _lexical_score(query_units, text)
            if base_score <= 0:
                return 0.0
            transition_bonus = 0.0
            for marker in (
                "adopted",
                "decided",
                "changed",
                "shifted",
                "rejected",
                "replaced",
                "resolved",
                "採用",
                "決定",
                "轉為",
                "改成",
            ):
                if marker in lowered_text:
                    transition_bonus += 0.08
            return base_score + min(0.24, transition_bonus)

        meeting_hints = _extract_meeting_hints(query)

        def rows_for_meeting_hint(hint: str) -> list[dict[str, Any]]:
            matches = [
                row
                for row in rows
                if str(row.get("meeting_id", "") or "") == hint
                or str(row.get("meeting_date", "") or "").replace("-", "")[4:8] == hint
            ]
            matches.sort(
                key=lambda row: (
                    0 if str(row.get("obj_id", "") or "") in matched else 1,
                    -evolution_relevance(row),
                    _timeline_event_date(row),
                )
            )
            return matches

        if meeting_hints:
            endpoint_hints = [meeting_hints[0]]
            if meeting_hints[-1] != meeting_hints[0]:
                endpoint_hints.append(meeting_hints[-1])
            for hint in endpoint_hints:
                hinted_rows = rows_for_meeting_hint(hint)
                if hinted_rows:
                    add(hinted_rows[0])
            for row in matched_rows:
                add(row)
            for hint in meeting_hints[1:-1]:
                hinted_rows = rows_for_meeting_hint(hint)
                if hinted_rows:
                    add(hinted_rows[0])

        relevant_rows = [
            row
            for row in rows
            if evolution_relevance(row) > 0
        ]
        span_rows = relevant_rows or matched_rows or rows
        origin_date = _timeline_event_date(span_rows[0]) if span_rows else ""
        if span_rows:
            add(span_rows[0])
        if matched_rows:
            latest_matched_date = max(_timeline_event_date(row) for row in matched_rows)
            if latest_matched_date > origin_date:
                latest_matched_rows = [
                    row for row in matched_rows if _timeline_event_date(row) == latest_matched_date
                ]
                latest_matched_rows.sort(
                    key=lambda row: matched_order.get(str(row.get("obj_id", "") or ""), len(matched_order))
                )
                add(latest_matched_rows[0])
            elif span_rows:
                later_span_rows = [
                    row for row in span_rows if _timeline_event_date(row) > origin_date
                ] or span_rows
                latest_span_date = max(_timeline_event_date(row) for row in later_span_rows)
                latest_span_rows = [
                    row for row in later_span_rows if _timeline_event_date(row) == latest_span_date
                ]
                latest_span_rows.sort(key=lambda row: -evolution_relevance(row))
                add(latest_span_rows[0])
        elif span_rows:
            latest_span_date = max(_timeline_event_date(row) for row in span_rows)
            latest_span_rows = [
                row for row in span_rows if _timeline_event_date(row) == latest_span_date
            ]
            latest_span_rows.sort(key=lambda row: -evolution_relevance(row))
            add(latest_span_rows[0])
        remaining = [
            row
            for row in rows
            if len(selected) < max_events
        ]
        remaining.sort(
            key=lambda row: (
                0 if str(row.get("obj_id", "") or "") in matched else 1,
                -evolution_relevance(row),
                _timeline_event_date(row),
            )
        )
        for row in remaining:
            add(row)
    else:
        for row in matched_rows:
            add(row)
    for row in rows:
        add(row)
    selected.sort(key=_timeline_event_date)
    return selected, max(0, len(rows) - len(selected))


def _node_query_similarity(query: str, node: dict[str, Any]) -> float:
    query_tokens = _tokens(query)
    query_units = _lexical_units(query)
    if not query_tokens and not query_units:
        return 0.0
    label = str(node.get("label", "") or "")
    text = " ".join(
        [
            label,
            str(node.get("current_state", "") or ""),
            str(node.get("split_reason", "") or ""),
            " ".join(str(x) for x in node.get("assignment_criteria", []) if str(x).strip())
            if isinstance(node.get("assignment_criteria"), list)
            else "",
        ]
    )
    node_tokens = _tokens(text)
    token_score = (
        len(query_tokens & node_tokens) / len(query_tokens)
        if query_tokens and node_tokens
        else 0.0
    )
    node_units = _lexical_units(text)
    unit_score = (
        len(query_units & node_units) / len(query_units)
        if query_units and node_units
        else 0.0
    )
    score = max(token_score, unit_score)

    query_phrase = " ".join(str(query or "").lower().replace("-", " ").split())
    label_phrase = " ".join(label.lower().replace("-", " ").split())
    label_units = _lexical_units(label_phrase)
    if label_phrase and label_phrase in query_phrase:
        score = max(score, 1.0)
    elif label_units and label_units.issubset(query_units):
        score = max(score, 0.9)
    elif label_units:
        label_overlap = len(label_units & query_units) / len(label_units)
        score = max(score, 0.8 * label_overlap)
    return min(1.0, score)


def _is_topic_navigation_query(query: str) -> bool:
    text = " ".join(str(query or "").lower().replace("-", " ").split())
    navigation_markers = [
        "child l2",
        "children l2",
        "child topic",
        "topic map",
        "topic hierarchy",
        "被拆成",
        "拆成哪些",
        "哪些 child",
        "哪些 l2",
        "主題被拆",
        "大主題",
    ]
    return any(marker in text for marker in navigation_markers)


def build_global_topic_map(
    l2_view: dict[str, Any] | None,
    l3_view: dict[str, Any] | None,
    *,
    max_chars: int = 800,
    query: str = "",
) -> dict[str, Any]:
    """Build a compact navigation map from materialized L3 plus remaining L2 labels."""
    promoted_source_l2_ids: set[str] = set()
    l3_families: list[dict[str, Any]] = []
    char_count = 0
    query_text = str(query or "")
    query_tokens = _tokens(query_text)
    query_units = _lexical_units(query_text)
    navigation_query = _is_topic_navigation_query(query_text)

    def family_score(l3_node: dict[str, Any]) -> float:
        children = (
            l3_node.get("child_l2_nodes", [])
            if isinstance(l3_node.get("child_l2_nodes"), list)
            else []
        )
        text_parts = [
            str(l3_node.get("l3_id", "") or ""),
            str(l3_node.get("label", "") or ""),
            str(l3_node.get("promoted_from_l2_id", "") or ""),
        ]
        for child in children:
            if isinstance(child, dict):
                text_parts.extend(
                    [
                        str(child.get("l2_id", "") or ""),
                        str(child.get("label", "") or ""),
                    ]
                )
        text = " ".join(text_parts)
        tokens = _tokens(text)
        units = _lexical_units(text)
        token_score = (
            len(query_tokens & tokens) / len(query_tokens)
            if query_tokens and tokens
            else 0.0
        )
        unit_score = (
            len(query_units & units) / len(query_units)
            if query_units and units
            else 0.0
        )
        return max(token_score, unit_score)

    def l2_score(node: dict[str, Any]) -> float:
        text = " ".join(
            [
                str(node.get("l2_id", "") or ""),
                str(node.get("label", "") or ""),
                str(node.get("current_state", "") or ""),
            ]
        )
        tokens = _tokens(text)
        units = _lexical_units(text)
        token_score = (
            len(query_tokens & tokens) / len(query_tokens)
            if query_tokens and tokens
            else 0.0
        )
        unit_score = (
            len(query_units & units) / len(query_units)
            if query_units and units
            else 0.0
        )
        return max(token_score, unit_score)

    l3_nodes = [
        node
        for node in ((l3_view or {}).get("l3_nodes", []) if isinstance(l3_view, dict) else [])
        if isinstance(node, dict)
    ]
    scored_l3_nodes = [
        (family_score(node), index, node)
        for index, node in enumerate(l3_nodes)
    ]
    if query_tokens or query_units:
        scored_l3_nodes.sort(key=lambda item: (-item[0], item[1]))

    focused_family_added = False
    for score, _index, l3_node in scored_l3_nodes:
        if focused_family_added:
            break
        if not isinstance(l3_node, dict):
            continue
        children = []
        include_all_children = bool(navigation_query and score > 0)
        for child in l3_node.get("child_l2_nodes", []) if isinstance(l3_node.get("child_l2_nodes"), list) else []:
            if not isinstance(child, dict):
                continue
            child_row = {
                "l2_id": str(child.get("l2_id", "") or ""),
                "label": str(child.get("label", "") or ""),
                "event_count": _node_event_count(child),
            }
            row_text = f"{child_row['l2_id']} {child_row['label']}"
            if not include_all_children and char_count + len(row_text) > max_chars and children:
                continue
            char_count += len(row_text)
            children.append(child_row)
        family = {
            "l3_id": str(l3_node.get("l3_id", "") or ""),
            "label": str(l3_node.get("label", "") or ""),
            "child_l2": children,
            "query_score": round(score, 4),
            "focused": bool(include_all_children),
        }
        promoted_source_l2_id = str(l3_node.get("promoted_from_l2_id", "") or "")
        if promoted_source_l2_id:
            promoted_source_l2_ids.add(promoted_source_l2_id)
        family_text = f"{family['l3_id']} {family['label']}"
        if include_all_children or char_count + len(family_text) <= max_chars or not l3_families:
            char_count += len(family_text)
            l3_families.append(family)
            focused_family_added = bool(include_all_children)

    l2_topics: list[dict[str, Any]] = []
    if focused_family_added:
        return {
            "source": "long_term_global_topic_map",
            "note": "Navigation context only; do not use as standalone factual evidence.",
            "l3_families": l3_families,
            "l2_topics": l2_topics,
            "char_count": char_count,
        }
    l2_nodes = [
        node
        for node in ((l2_view or {}).get("l2_nodes", []) if isinstance(l2_view, dict) else [])
        if isinstance(node, dict)
    ]
    scored_l2_nodes = [(l2_score(node), index, node) for index, node in enumerate(l2_nodes)]
    if query_tokens or query_units:
        scored_l2_nodes.sort(key=lambda item: (-item[0], item[1]))
    for _score, _index, node in scored_l2_nodes:
        if not isinstance(node, dict):
            continue
        l2_id = str(node.get("l2_id", "") or "")
        if l2_id in promoted_source_l2_ids:
            continue
        row = {
            "l2_id": l2_id,
            "label": str(node.get("label", "") or ""),
            "event_count": _node_event_count(node),
        }
        row_text = f"{row['l2_id']} {row['label']}"
        if char_count + len(row_text) > max_chars and l2_topics:
            continue
        char_count += len(row_text)
        l2_topics.append(row)

    return {
        "source": "long_term_global_topic_map",
        "note": "Navigation context only; do not use as standalone factual evidence.",
        "l3_families": l3_families,
        "l2_topics": l2_topics,
        "char_count": char_count,
    }


def select_layered_l2_context(
    query: str,
    l1_results: list[dict[str, Any]],
    l2_index: dict[str, Any] | None,
    l2_view: dict[str, Any] | None,
    *,
    l3_view: dict[str, Any] | None = None,
    l3_index: dict[str, Any] | None = None,
    max_relevant_l2_summaries: int = 3,
    max_expanded_l2_topics: int = 2,
    max_events_per_l2: int = 6,
    max_events_per_child_l2: int = 8,
    max_event_chars: int = 280,
    prefer_materialized_l3: bool = True,
    topic_size_penalty: float = 0.05,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not l1_results or not l2_index or not l2_view:
        return [], [], {
            "selected_l2_count": 0,
            "selected_child_l2_count": 0,
            "omitted_event_count": 0,
            "large_l2_expanded_without_child_split": False,
        }

    l2_lookup = _l2_nodes_by_id(l2_view)
    l3_nodes = {
        str(node.get("l3_id", "") or ""): node
        for node in (l3_view or {}).get("l3_nodes", []) if isinstance(node, dict)
    } if isinstance(l3_view, dict) else {}
    groups: dict[str, dict[str, Any]] = {}

    for seed in l1_results:
        obj_id = str(seed.get("obj_id", "") or "")
        if not obj_id:
            continue
        assignment = l2_index.get(obj_id) if isinstance(l2_index, dict) else None
        if not isinstance(assignment, dict):
            continue
        l3_assignment = l3_index.get(obj_id) if isinstance(l3_index, dict) else None
        if prefer_materialized_l3 and isinstance(l3_assignment, dict):
            l3_id = str(l3_assignment.get("l3_id", "") or "")
            child_l2_id = str(l3_assignment.get("child_l2_id", "") or "")
            l3_node = l3_nodes.get(l3_id)
            child_node = _child_l2_nodes_by_id(l3_node or {}).get(child_l2_id)
            if child_node:
                key = f"child:{child_l2_id}"
                groups.setdefault(
                    key,
                    {
                        "source": "long_term_child_l2",
                        "parent_l3_id": l3_id,
                        "parent_l3_label": str((l3_node or {}).get("label", "") or ""),
                        "promoted_from_l2_id": str((l3_node or {}).get("promoted_from_l2_id", "") or ""),
                        "l2_id": child_l2_id,
                        "label": str(child_node.get("label", "") or ""),
                        "current_state": str(child_node.get("current_state", "") or ""),
                        "node": child_node,
                        "matched_l1_ids": [],
                        "matched_seed_scores": [],
                        "matched_importance": [],
                    },
                )
                group = groups[key]
                group["matched_l1_ids"].append(obj_id)
                group["matched_seed_scores"].append(float(seed.get("score", 0.0) or 0.0))
                group["matched_importance"].append(float(seed.get("importance", 0.0) or 0.0))
                continue
        l2_id = str(assignment.get("l2_id", "") or "")
        node = l2_lookup.get(l2_id)
        if not node:
            continue
        key = f"l2:{l2_id}"
        groups.setdefault(
            key,
            {
                "source": "long_term_l2",
                "l2_id": l2_id,
                "label": str(node.get("label") or assignment.get("l2_label") or ""),
                "current_state": str(node.get("current_state", "") or ""),
                "node": node,
                "matched_l1_ids": [],
                "matched_seed_scores": [],
                "matched_importance": [],
            },
        )
        group = groups[key]
        group["matched_l1_ids"].append(obj_id)
        group["matched_seed_scores"].append(float(seed.get("score", 0.0) or 0.0))
        group["matched_importance"].append(float(seed.get("importance", 0.0) or 0.0))

    rows: list[dict[str, Any]] = []
    for group in groups.values():
        node = group.pop("node")
        timeline = node.get("timeline_digest", []) if isinstance(node.get("timeline_digest"), list) else []
        topic_size = _node_event_count(node, timeline=timeline)
        seed_scores = group.pop("matched_seed_scores")
        importances = group.pop("matched_importance")
        seed_score_aggregate = max(seed_scores) if seed_scores else 0.0
        seed_count_coverage = len(set(group["matched_l1_ids"])) / max(1, len(l1_results))
        query_similarity = _node_query_similarity(query, node)
        importance = sum(importances) / len(importances) if importances else 0.0
        currentness = 0.5
        if timeline:
            currentness = 1.0
        l2_score = (
            0.35 * seed_score_aggregate
            + 0.20 * seed_count_coverage
            + 0.30 * query_similarity
            + 0.10 * currentness
            + 0.05 * importance
            - topic_size_penalty * math.log(topic_size + 1)
        )
        max_events = max_events_per_child_l2 if group["source"] == "long_term_child_l2" else max_events_per_l2
        selected_timeline, omitted = _select_timeline_slice(
            timeline,
            group["matched_l1_ids"],
            max_events=max_events,
            max_event_chars=max_event_chars,
            query=query,
        )
        row = {
            **group,
            "topic_size": topic_size,
            "selected_event_count": len(selected_timeline),
            "omitted_event_count": omitted,
            "timeline_digest": selected_timeline,
            "selection_score": round(l2_score, 4),
        }
        if group["source"] == "long_term_l2" and topic_size > max_events_per_l2:
            row["retrieval_slice"] = "selected_slice"
        rows.append(row)

    rows.sort(key=lambda row: -float(row.get("selection_score", 0.0) or 0.0))
    selected = rows[:max(max_relevant_l2_summaries, max_expanded_l2_topics)]
    selected = selected[:max_expanded_l2_topics] + selected[max_expanded_l2_topics:max_relevant_l2_summaries]
    selected = selected[:max_relevant_l2_summaries]
    l3_contexts: dict[str, dict[str, Any]] = {}
    for row in selected:
        parent_l3_id = str(row.get("parent_l3_id", "") or "")
        if parent_l3_id:
            l3_contexts[parent_l3_id] = {
                "l3_id": parent_l3_id,
                "label": str(row.get("parent_l3_label", "") or ""),
                "source": "long_term_l3_topic_family",
            }
    debug = {
        "selected_l2_count": sum(1 for row in selected if row.get("source") == "long_term_l2"),
        "selected_child_l2_count": sum(1 for row in selected if row.get("source") == "long_term_child_l2"),
        "omitted_event_count": sum(int(row.get("omitted_event_count", 0) or 0) for row in selected),
        "large_l2_expanded_without_child_split": any(
            row.get("source") == "long_term_l2" and int(row.get("topic_size", 0) or 0) > max_events_per_l2
            and int(row.get("selected_event_count", 0) or 0) >= int(row.get("topic_size", 0) or 0)
            for row in selected
        ),
    }
    return selected, list(l3_contexts.values()), debug


# ===================================================================
# Legacy L2/L3 retrieval via parent-chain expansion
# ===================================================================

def _get_l2_for_meeting(tree: dict[str, Any], meeting_id: str) -> dict[str, Any] | None:
    """Find L2 phase that contains *meeting_id* in child_meeting_ids."""
    for phase in tree.get("phases", []):
        if meeting_id in phase.get("child_meeting_ids", []):
            return phase
    return None


def get_l3_profile(tree: dict[str, Any]) -> dict[str, Any] | None:
    """Return the L3 project profile if it contains meaningful data."""
    profile = tree.get("project_profile", {})
    if not profile.get("core_goal") and not profile.get("established_methods"):
        return None
    return {"source": "long_term_l3", **profile}


def expand_parent_chain(
    tree: dict[str, Any],
    l1_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Expand kept L1 objects to their L2 phases and singleton L3 profile."""
    seen_phase_ids: set[str] = set()
    l2_nodes: list[dict[str, Any]] = []

    for item in l1_results:
        phase_id = item.get("phase_id", "")
        meeting_id = item.get("meeting_id", "")

        phase = None
        if phase_id:
            if phase_id not in seen_phase_ids:
                phase = next(
                    (p for p in tree.get("phases", []) if p.get("phase_id") == phase_id),
                    None,
                )
        else:
            phase = _get_l2_for_meeting(tree, meeting_id)

        if not phase:
            continue

        pid = phase.get("phase_id", "")
        if pid and pid not in seen_phase_ids:
            seen_phase_ids.add(pid)
            l2_nodes.append({"source": "long_term_l2", **phase})

    l3_profile = get_l3_profile(tree)
    return l2_nodes, l3_profile


def _l1_lookup(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for meeting in tree.get("meetings", []):
        meeting_id = meeting.get("meeting_id", "")
        timestamp = meeting.get("timestamp", "")
        meeting_date = meeting.get("meeting_date", "")
        phase_id = meeting.get("phase_id", "")
        for obj in meeting.get("memory_objects", []):
            obj_id = str(obj.get("obj_id", "")).strip()
            if obj_id:
                lookup[obj_id] = {
                    "source": "long_term_l1_linked",
                    "meeting_id": meeting_id,
                    "timestamp": timestamp,
                    "meeting_date": meeting_date,
                    "phase_id": phase_id,
                    "obj_id": obj_id,
                    "type": obj.get("type", ""),
                    "content": obj.get("content", ""),
                    "importance": obj.get("importance", 0.0),
                    "evidence": obj.get("evidence", ""),
                    "related_topics": obj.get("related_topics", []),
                    "_raw_obj": obj,
                }
    return lookup


def expand_relation_graph(
    tree: dict[str, Any],
    l1_results: list[dict[str, Any]],
    relations_index: dict[str, Any] | None,
    *,
    max_linked: int = 6,
) -> list[dict[str, Any]]:
    """Softly add linked L1 context without changing primary semantic search."""
    if not relations_index:
        return l1_results
    lookup = _l1_lookup(tree)
    output = list(l1_results)
    seen_ids = {str(item.get("obj_id", "")).strip() for item in output}
    linked: list[dict[str, Any]] = []
    for item in l1_results:
        source_obj_id = str(item.get("obj_id", "")).strip()
        source_lookup = lookup.get(source_obj_id)
        if not source_lookup:
            continue
        source_obj = source_lookup["_raw_obj"]
        relations = relations_index.get(source_obj_id, [])
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            target_obj_id = str(relation.get("target_obj_id", "")).strip()
            if not target_obj_id or target_obj_id in seen_ids:
                continue
            target = lookup.get(target_obj_id)
            if not target:
                continue
            if not relation_is_current(
                relation,
                source_obj=source_obj,
                target_obj=target["_raw_obj"],
            ):
                continue
            try:
                relation_confidence = float(relation.get("confidence") or 0.0)
            except (TypeError, ValueError):
                relation_confidence = 0.0
            linked_item = {
                key: value
                for key, value in target.items()
                if key != "_raw_obj"
            }
            base_score = float(item.get("score", 0.0) or 0.0)
            linked_item.update(
                {
                    "score": round(max(0.0, min(1.0, base_score * 0.86 * relation_confidence)), 4),
                    "linked_from_obj_id": source_obj_id,
                    "relation": relation.get("relation", ""),
                    "relation_confidence": round(relation_confidence, 3),
                }
            )
            linked.append(linked_item)
            seen_ids.add(target_obj_id)
            if len(linked) >= max_linked:
                return sorted(output + linked, key=lambda row: -float(row.get("score", 0.0) or 0.0))
    return sorted(output + linked, key=lambda row: -float(row.get("score", 0.0) or 0.0))


# ===================================================================
# Recall Gate (LLM-based noise filter)
# ===================================================================

def _build_gate_prompt(
    query: str,
    candidates: list[dict[str, Any]],
) -> str:
    candidates_text = ""
    for i, c in enumerate(candidates):
        obj_id = c.get("obj_id", c.get("phase_id", f"candidate_{i}"))
        content = c.get("content", c.get("summary", ""))
        obj_type = c.get("type", c.get("source", "?"))
        meeting_id = c.get("meeting_id", "")
        date_str = c.get("meeting_date") or c.get("timestamp", "")[:10]
        phase_id = c.get("phase_id", "")
        importance = c.get("importance", "?")
        score = c.get("score", "?")
        candidates_text += (
            f"\n[{obj_id}] type={obj_type} meeting={meeting_id} "
            f"date={date_str} phase={phase_id} "
            f"importance={importance} score={score}\n"
            f"  {content}\n"
        )

    return f"""
你是「記憶過濾閘門」(Recall Gate)。
任務：從候選記憶物件中，篩選出與使用者問題真正相關的，剔除雜訊。

規則：
1) 回傳 JSON only。
2) relevant_obj_ids 列出相關物件的 ID（保留 5-8 個為佳）。
3) 只保留真正能回答問題或提供重要背景的物件。
4) 語意接近但實際不相關的，請剔除。
5) 高度重疊或重複的物件，只保留最具代表性的一筆。
6) 可根據 date / phase 資訊，剔除過時或已被推翻的物件。

使用者問題：
{query}

候選記憶物件：
{candidates_text.strip()}
""".strip()


def _extract_json(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise RuntimeError("Response does not contain valid JSON.")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse gate JSON.") from exc
    return data


def _is_retryable_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {429, 500, 502, 503, 504}:
        return True
    msg = str(exc).upper()
    retry_tokens = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "RATE LIMIT",
    )
    return any(token in msg for token in retry_tokens)


def recall_gate(
    query: str,
    candidates: list[dict[str, Any]],
    api_key: str | list[str],
    model_name: str = DEFAULT_MODEL_NAME,
    max_retries: int = 5,
) -> list[dict[str, Any]]:
    """Use LLM to filter candidate memories, removing noise."""
    if len(candidates) <= 3:
        return candidates

    client = create_gemini_client(api_key)
    prompt = _build_gate_prompt(query, candidates)
    config = {
        "temperature": 0.1,
        "response_mime_type": "application/json",
        "response_json_schema": RECALL_GATE_SCHEMA,
    }
    result: dict[str, Any] | None = None
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            result = _extract_json(response.text or "")
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries or not _is_retryable_error(exc):
                break
            backoff = min(90.0, 2.0 * (2 ** (attempt - 1)))
            wait_s = backoff + random.uniform(0.0, 1.5)
            print(
                f"  Recall gate API busy ({type(exc).__name__}), "
                f"retry {attempt}/{max_retries} in {wait_s:.1f}s..."
            )
            time.sleep(wait_s)

    if result is None:
        if last_exc:
            print(
                "  Recall gate fallback: applying score-based truncation because gate API is unavailable."
            )
        filtered = [
            c for c in candidates if float(c.get("score", 0.0) or 0.0) >= FALLBACK_SCORE_THRESHOLD
        ]
        filtered.sort(key=lambda x: -float(x.get("score", 0.0) or 0.0))
        return filtered[:FALLBACK_MAX_RESULTS]

    relevant_ids = set(result.get("relevant_obj_ids", []))

    if not relevant_ids:
        return candidates

    filtered = [
        c for c in candidates if c.get("obj_id", c.get("phase_id", "")) in relevant_ids
    ]
    return filtered if filtered else candidates


# ===================================================================
# Main recall orchestrator
# ===================================================================

def recall(
    query: str,
    plan: dict[str, Any],
    tree: dict[str, Any],
    api_key: str | list[str],
    model_name: str = DEFAULT_MODEL_NAME,
    short_term_memory: dict[str, Any] | None = None,
    query_date: datetime | None = None,
    embed_cache: EmbedCache | None = None,
    top_k_raw: int = 30,
    activity_index: dict[str, Any] | None = None,
    activity_index_path: Path | None = None,
    relations_index: dict[str, Any] | None = None,
    relations_index_path: Path | None = None,
    l2_index: dict[str, Any] | None = None,
    l2_view: dict[str, Any] | None = None,
    l3_promotions: dict[str, Any] | None = None,
    l3_view: dict[str, Any] | None = None,
    l3_index: dict[str, Any] | None = None,
    l2_index_path: Path | None = None,
    l2_view_path: Path | None = None,
    l3_promotions_path: Path | None = None,
    l3_view_path: Path | None = None,
    l3_index_path: Path | None = None,
    max_l1_seeds_for_prompt: int = 8,
    max_global_topic_map_chars: int = 800,
    max_relevant_l2_summaries: int = 3,
    max_expanded_l2_topics: int = 2,
    max_events_per_l2: int = 6,
    max_events_per_child_l2: int = 8,
    max_event_chars: int = 280,
    prefer_materialized_l3: bool = True,
    topic_size_penalty: float = 0.05,
    include_retrieval_debug: bool = False,
    retrieval_mode: str = "semantic",
    use_legacy_parent_fallback: bool = True,
) -> dict[str, Any]:
    """Execute a recall plan and return retrieved memories."""
    if query_date is None:
        query_date = datetime.now(timezone.utc)
    embed_model = os.getenv("GEMINI_EMBED_MODEL", EMBED_MODEL_NAME).strip() or EMBED_MODEL_NAME

    keywords = plan.get("keywords", [])
    targets = set(plan.get("search_targets", []))
    type_filter_raw = plan.get("type_filter", [])
    type_filter = (
        [str(t).strip() for t in type_filter_raw if str(t).strip()]
        if isinstance(type_filter_raw, list)
        else []
    )

    own_cache = embed_cache is None
    if embed_cache is None:
        embed_cache = EmbedCache()
    if activity_index is None and activity_index_path is not None:
        activity_index = load_memory_activity_index(activity_index_path)
    if relations_index is None and relations_index_path is not None:
        relations_index = load_memory_relations_index(relations_index_path)
    if l2_index is None:
        l2_index = load_l2_index(l2_index_path)
    if l2_view is None:
        l2_view = load_l2_view(l2_view_path)
    if l3_promotions is None:
        l3_promotions = load_l3_promotions(l3_promotions_path)
    if l3_view is None:
        l3_view = load_l3_view(l3_view_path)
    if l3_index is None:
        l3_index = load_l3_index(l3_index_path)

    stm_results: list[dict[str, Any]] = []
    l1_results: list[dict[str, Any]] = []
    l2_results: list[dict[str, Any]] = []
    l3_results: list[dict[str, Any]] = []
    global_topic_map = build_global_topic_map(
        l2_view,
        l3_view,
        max_chars=max_global_topic_map_chars,
        query=query,
    )
    retrieval_debug: dict[str, Any] = {
        "selected_l1_count": 0,
        "selected_l2_count": 0,
        "selected_child_l2_count": 0,
        "global_topic_map_chars": int(global_topic_map.get("char_count", 0) or 0),
        "expanded_context_chars": 0,
        "omitted_event_count": 0,
        "large_l2_expanded_without_child_split": False,
        "retrieval_mode": retrieval_mode,
    }
    l3_profile = None

    # --- short-term search (keyword-based; unchanged) ---
    if "short_term" in targets and short_term_memory:
        for mw in short_term_memory.get("meeting_window", []):
            text = " ".join([mw.get("summary", ""), " ".join(mw.get("key_points", []))])
            score = _keyword_score(text, keywords)
            if score > 0:
                stm_results.append(
                    {
                        "source": "short_term",
                        "meeting_id": mw.get("meeting_id", ""),
                        "summary": mw.get("summary", ""),
                        "key_points": mw.get("key_points", []),
                        "score": score,
                    }
                )

        for ai in short_term_memory.get("action_items", []):
            text = f"{ai.get('title', '')} {ai.get('detail', '')}"
            score = _keyword_score(text, keywords)
            if score > 0:
                stm_results.append(
                    {
                        "source": "short_term",
                        "obj_id": ai.get("item_id", ""),
                        "type": "action_item",
                        "content": f"{ai.get('title', '')}: {ai.get('detail', '')}",
                        "status": ai.get("status", ""),
                        "score": score,
                    }
                )

    # --- long-term search (semantic L1 + active L2 view expansion) ---
    if any(t.startswith("long_term") for t in targets):
        if retrieval_mode == "lexical":
            l1_candidates = search_l1_lexical(
                tree=tree,
                query=query,
                keywords=[str(k) for k in keywords if str(k).strip()] if isinstance(keywords, list) else [],
                obj_types=type_filter or None,
                top_k=top_k_raw,
                query_date=query_date,
                activity_index=activity_index,
            )
        else:
            query_emb = embed_text(query, api_key, embed_cache, model=embed_model)

            l1_candidates = search_l1_semantic(
                tree=tree,
                query_emb=query_emb,
                api_key=api_key,
                cache=embed_cache,
                obj_types=type_filter or None,
                top_k=top_k_raw,
                query_date=query_date,
                embed_model=embed_model,
                activity_index=activity_index,
            )

        if plan.get("complexity") == "complex" and len(l1_candidates) > 5:
            l1_results = recall_gate(query, l1_candidates, api_key, model_name)
        else:
            l1_results = l1_candidates
        l1_results = expand_relation_graph(tree, l1_results, relations_index)
        l1_results = sorted(
            l1_results,
            key=lambda row: -float(row.get("score", 0.0) or 0.0),
        )[:max_l1_seeds_for_prompt]

        l2_results, l3_results, topic_debug = select_layered_l2_context(
            query,
            l1_results,
            l2_index,
            l2_view,
            l3_view=l3_view,
            l3_index=l3_index,
            max_relevant_l2_summaries=max_relevant_l2_summaries,
            max_expanded_l2_topics=max_expanded_l2_topics,
            max_events_per_l2=max_events_per_l2,
            max_events_per_child_l2=max_events_per_child_l2,
            max_event_chars=max_event_chars,
            prefer_materialized_l3=prefer_materialized_l3,
            topic_size_penalty=topic_size_penalty,
        )
        retrieval_debug.update(topic_debug)
        retrieval_debug["selected_l1_count"] = len(l1_results)
        if not l2_results and use_legacy_parent_fallback:
            l2_results, l3_profile = expand_parent_chain(tree, l1_results)
        elif "long_term_l3" in targets:
            l3_profile = get_l3_profile(tree)

    if own_cache:
        embed_cache.save()

    return {
        "complexity": plan.get("complexity", "simple"),
        "short_term_results": stm_results,
        "long_term_results": l1_results,  # backward compatibility alias
        "long_term_l1": l1_results,
        "long_term_l2": l2_results,
        "long_term_l3": l3_results,
        "global_topic_map": global_topic_map,
        "retrieval_debug": retrieval_debug if include_retrieval_debug else {},
        "project_profile": l3_profile,
    }


# ===================================================================
# Format for prompt injection
# ===================================================================

def _format_recall_for_prompt_legacy(recall_result: dict[str, Any]) -> str:
    """Format recall results for prompt injection.

    Output order: L3 -> L2 -> L1 -> short-term.
    """
    parts: list[str] = []

    # --- L3 profile ---
    profile = recall_result.get("project_profile")
    if profile:
        parts.append("=== 研究計畫輪廓 (L3) ===")
        if profile.get("core_goal"):
            parts.append(f"目標：{profile['core_goal']}")
        if profile.get("current_phase"):
            parts.append(f"目前階段：{profile['current_phase']}")
        if profile.get("established_methods"):
            parts.append("確立做法：")
            for method in profile["established_methods"]:
                parts.append(f"  · {method}")
        if profile.get("long_term_open_questions"):
            parts.append("長期懸案：")
            for question in profile["long_term_open_questions"]:
                parts.append(f"  ? {question}")

    # --- L2 topic context ---
    l2_results = recall_result.get("long_term_l2", [])
    topic_l2_results = [item for item in l2_results if item.get("l2_id")]
    if topic_l2_results:
        parts.append("\n=== L2 主題脈絡 ===")
        for node in topic_l2_results:
            l2_id = node.get("l2_id", "?")
            label = node.get("label", "")
            parts.append(f"\n[{l2_id}] {label}".rstrip())
            if node.get("current_state"):
                parts.append(f"  state: {node['current_state']}")
            matched_l1_ids = node.get("matched_l1_ids", [])
            if matched_l1_ids:
                parts.append(f"  matched L1: {', '.join(str(x) for x in matched_l1_ids)}")
            promotion = node.get("promoted_to_l3")
            if isinstance(promotion, dict) and promotion.get("l3_id"):
                parts.append(
                    f"  promoted L3: {promotion['l3_id']}"
                    f" status={promotion.get('status', '')}"
                )
                children = promotion.get("child_l2_candidates", [])
                if isinstance(children, list):
                    for child in children:
                        if not isinstance(child, dict):
                            continue
                        child_id = str(child.get("child_l2_id", "") or "")
                        child_label = str(child.get("label", "") or "")
                        if child_id:
                            parts.append(f"  child L2: {child_id} {child_label}".rstrip())
            materialized = node.get("materialized_l3")
            if isinstance(materialized, dict) and materialized.get("l3_id"):
                parts.append(f"  materialized L3: {materialized['l3_id']}")
                children = materialized.get("child_l2_contexts", [])
                if isinstance(children, list):
                    for child in children:
                        if not isinstance(child, dict):
                            continue
                        child_id = str(child.get("l2_id", "") or "")
                        child_label = str(child.get("label", "") or "")
                        if not child_id:
                            continue
                        parts.append(
                            f"  materialized child L2: {child_id} {child_label}".rstrip()
                        )
                        child_matched = child.get("matched_l1_ids", [])
                        if child_matched:
                            parts.append(
                                "    matched L1: "
                                + ", ".join(str(x) for x in child_matched)
                            )
                        child_timeline = child.get("timeline_digest", [])
                        if child_timeline:
                            parts.append("    timeline:")
                            for entry in child_timeline:
                                if not isinstance(entry, dict):
                                    continue
                                date_str = entry.get("meeting_date") or entry.get("meeting_id", "?")
                                obj_id = entry.get("obj_id", "")
                                summary = entry.get("summary", "")
                                parts.append(f"      - [{date_str} {obj_id}] {summary}".rstrip())
            timeline = node.get("timeline_digest", [])
            if timeline:
                parts.append("  timeline:")
                for entry in timeline:
                    if not isinstance(entry, dict):
                        continue
                    date_str = entry.get("meeting_date") or entry.get("meeting_id", "?")
                    obj_id = entry.get("obj_id", "")
                    summary = entry.get("summary", "")
                    parts.append(f"    - [{date_str} {obj_id}] {summary}".rstrip())

    # --- Legacy L2 phases ---
    phase_l2_results = [item for item in l2_results if not item.get("l2_id")]
    if phase_l2_results:
        parts.append("\n=== 階段摘要 (L2) ===")
        for phase in phase_l2_results:
            phase_id = phase.get("phase_id", "?")
            tr = phase.get("time_range", {})
            time_str = f"{tr.get('start', '?')} ~ {tr.get('end', '?')}"
            parts.append(f"\n[Phase {phase_id} | {time_str}]")
            if phase.get("summary"):
                parts.append(f"  {phase['summary']}")
            for change in phase.get("changes", []):
                status_label = {
                    "adopted": "✓確立",
                    "abandoned": "✗棄用",
                    "evolved": "→演進",
                }.get(change.get("status", ""), change.get("status", "?"))
                parts.append(f"  [{status_label}] {change.get('method', '')}")
            for issue in phase.get("open_to_next", []):
                parts.append(f"  [懸案] {issue}")

    # --- L1 memory objects ---
    l1_results = recall_result.get(
        "long_term_l1",
        recall_result.get("long_term_results", []),
    )
    if l1_results:
        parts.append("\n=== 記憶物件 (L1) ===")

        def _sort_key(item: dict[str, Any]) -> str:
            return item.get("meeting_date") or item.get("timestamp") or item.get("meeting_id", "")

        for item in sorted(l1_results, key=_sort_key):
            date_str = item.get("meeting_date") or item.get("timestamp", "")[:10]
            activity_state = item.get("activity_state")
            activity_text = (
                f" activity={activity_state}"
                if activity_state and activity_state != "unknown"
                else ""
            )
            parts.append(
                f"  [{item.get('meeting_id', '?')} | {date_str}] "
                f"({item.get('type', '?')}) "
                f"importance={item.get('importance', '?')} "
                f"score={item.get('score', '?')}{activity_text}\n"
                f"    {item.get('content', '')}"
            )

    # --- short-term results ---
    stm = recall_result.get("short_term_results", [])
    if stm:
        parts.append("\n=== 短期記憶結果 ===")
        for item in stm:
            if item.get("type") == "action_item":
                parts.append(
                    f"  [TODO] {item.get('content', '')} "
                    f"(status={item.get('status', '')})"
                )
            else:
                parts.append(
                    f"  [{item.get('meeting_id', '?')}] "
                    f"{item.get('summary', '')}"
                )

    return "\n".join(parts) if parts else "（無相關記憶）"


def format_recall_for_prompt(
    recall_result: dict[str, Any],
    *,
    include_debug: bool = False,
    l1_content_chars: int = 100,
    l1_evidence_chars: int = 100,
) -> str:
    """Format evidence-first layered long-term context for prompt injection."""
    parts: list[str] = []

    global_map = recall_result.get("global_topic_map")
    if isinstance(global_map, dict) and (
        global_map.get("l3_families") or global_map.get("l2_topics")
    ):
        parts.append("=== Global Topic Map ===")
        parts.append("Low-resolution navigation context only; not standalone factual evidence.")
        for family in global_map.get("l3_families", []):
            if not isinstance(family, dict):
                continue
            parts.append(f"- L3 {family.get('l3_id', '')}: {family.get('label', '')}".rstrip())
            children = [child for child in family.get("child_l2", []) if isinstance(child, dict)]
            if family.get("focused") and len(children) > 4:
                child_ids = [str(child.get("l2_id", "") or "") for child in children if child.get("l2_id")]
                if child_ids:
                    parts.append(f"  - child L2 map: {'; '.join(child_ids)}")
                continue
            for child in children:
                if isinstance(child, dict):
                    parts.append(
                        f"  - child L2 {child.get('l2_id', '')}: {child.get('label', '')}".rstrip()
                    )
        if global_map.get("l2_topics"):
            parts.append("- Unpromoted L2 topics:")
            for topic in global_map.get("l2_topics", []):
                if isinstance(topic, dict):
                    parts.append(f"  - {topic.get('l2_id', '')}: {topic.get('label', '')}".rstrip())

    l1_results = recall_result.get(
        "long_term_l1",
        recall_result.get("long_term_results", []),
    )
    if l1_results:
        parts.append("\n=== L1 Evidence Seeds ===")

        def _sort_key(item: dict[str, Any]) -> str:
            return item.get("meeting_date") or item.get("timestamp") or item.get("meeting_id", "")

        for item in sorted(l1_results, key=_sort_key):
            date_str = item.get("meeting_date") or item.get("timestamp", "")[:10]
            parts.append(
                f"- [{item.get('meeting_id', '?')} | {date_str} | {item.get('obj_id', '?')}] "
                f"type={item.get('type', '?')} importance={item.get('importance', '?')} "
                f"score={item.get('score', '?')}"
            )
            if item.get("content"):
                parts.append(f"  content: {_truncate_text(item.get('content', ''), l1_content_chars)}")
            if item.get("evidence"):
                parts.append(f"  evidence: {_truncate_text(item.get('evidence', ''), l1_evidence_chars)}")

    l2_results = recall_result.get("long_term_l2", [])
    topic_l2_results = [item for item in l2_results if item.get("l2_id")]
    if topic_l2_results:
        parts.append("\n=== L2 / Child-L2 Evolution Context ===")
        for node in topic_l2_results:
            l2_id = node.get("l2_id", "?")
            label = node.get("label", "")
            parts.append(f"\n[{l2_id}] {label}".rstrip())
            if node.get("parent_l3_id"):
                parts.append(
                    f"  parent L3: {node.get('parent_l3_id')} {node.get('parent_l3_label', '')}".rstrip()
                )
            materialized = node.get("materialized_l3")
            if isinstance(materialized, dict) and materialized.get("l3_id"):
                parts.append(f"  materialized L3: {materialized['l3_id']}")
            promotion = node.get("promoted_to_l3")
            if isinstance(promotion, dict) and promotion.get("l3_id"):
                parts.append(
                    f"  promoted L3: {promotion.get('l3_id', '')} status={promotion.get('status', '')}".rstrip()
                )
                for child in promotion.get("child_l2_candidates", []):
                    if isinstance(child, dict) and child.get("child_l2_id"):
                        parts.append(
                            f"  child L2: {child.get('child_l2_id')} {child.get('label', '')}".rstrip()
                        )
            matched_l1_ids = node.get("matched_l1_ids", [])
            if matched_l1_ids:
                parts.append(f"  matched L1: {', '.join(str(x) for x in matched_l1_ids)}")
            topic_size = node.get("topic_size")
            if topic_size is None and isinstance(node.get("linked_obj_ids"), list):
                topic_size = len(node["linked_obj_ids"])
            selected_count = node.get("selected_event_count")
            if selected_count is None and isinstance(node.get("timeline_digest"), list):
                selected_count = len(node["timeline_digest"])
            parts.append(
                f"  topic_size={topic_size if topic_size is not None else '?'} "
                f"selected_event_count={selected_count if selected_count is not None else '?'} "
                f"omitted_event_count={node.get('omitted_event_count', 0)}"
            )
            if node.get("current_state"):
                parts.append(f"  current_state: {_truncate_text(node['current_state'], 260)}")
            timeline = node.get("timeline_digest", [])
            if timeline:
                parts.append("  timeline_digest:")
                for entry in timeline:
                    if not isinstance(entry, dict):
                        continue
                    date_str = entry.get("meeting_date") or entry.get("meeting_id", "?")
                    obj_id = entry.get("obj_id", "")
                    summary = entry.get("summary", "")
                    parts.append(f"    - [{date_str} {obj_id}] {summary}".rstrip())

            if isinstance(materialized, dict):
                for child in materialized.get("child_l2_contexts", []):
                    if not isinstance(child, dict) or not child.get("l2_id"):
                        continue
                    parts.append(
                        f"  materialized child L2: {child.get('l2_id')} {child.get('label', '')}".rstrip()
                    )

    phase_l2_results = [item for item in l2_results if not item.get("l2_id")]
    if phase_l2_results:
        parts.append("\n=== Legacy Temporal L2 Fallback ===")
        for phase in phase_l2_results:
            phase_id = phase.get("phase_id", "?")
            tr = phase.get("time_range", {})
            parts.append(f"- [Phase {phase_id} | {tr.get('start', '?')} ~ {tr.get('end', '?')}]")
            if phase.get("summary"):
                parts.append(f"  summary: {phase['summary']}")

    stm = recall_result.get("short_term_results", [])
    if stm:
        parts.append("\n=== Short-Term Memory Supplement ===")
        for item in stm:
            if item.get("type") == "action_item":
                parts.append(
                    f"- [TODO] {item.get('content', '')} "
                    f"(status={item.get('status', '')})"
                )
            else:
                parts.append(f"- [{item.get('meeting_id', '?')}] {item.get('summary', '')}")

    debug = recall_result.get("retrieval_debug")
    if include_debug and isinstance(debug, dict) and debug:
        parts.append("\n=== Retrieval Debug ===")
        for key in sorted(debug):
            parts.append(f"- {key}: {debug[key]}")

    return "\n".join(parts) if parts else "No relevant memory context found."
