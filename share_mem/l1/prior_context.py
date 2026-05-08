"""Compact prior context packs for cross-meeting L1 extraction."""

from __future__ import annotations

import re
from typing import Any

from .l1_quality import l1_quality_hashes
from .memory_activity import format_memory_activity_tag

PRIOR_CONTEXT_SCHEMA_VERSION = 1
DEFAULT_PRIOR_CONTEXT_MAX_ITEMS = 12
TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
DURABLE_CONTEXT_TYPES = {"decision", "method_change", "approach_change"}
OPEN_THREAD_TYPES = {"todo", "action_item", "open_question", "open_issue"}


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(str(text or ""))}


def _overlap_score(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _quality_for_obj(
    obj: dict[str, Any],
    quality_index: dict[str, Any] | None,
) -> tuple[str, bool]:
    obj_id = str(obj.get("obj_id", "")).strip()
    meta = (quality_index or {}).get(obj_id)
    if not isinstance(meta, dict):
        return "unknown", False
    expected = l1_quality_hashes(obj)
    stale = (
        meta.get("content_hash") != expected["content_hash"]
        or meta.get("evidence_hash") != expected["evidence_hash"]
    )
    if stale:
        return "unknown", True
    return str(meta.get("quality_level") or "unknown").strip().lower(), False


def _iter_l1_rows(tree: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for meeting_index, meeting in enumerate(tree.get("meetings", [])):
        meeting_id = str(meeting.get("meeting_id", "")).strip()
        for obj in meeting.get("memory_objects", []):
            if isinstance(obj, dict):
                rows.append(
                    {
                        "meeting_index": meeting_index,
                        "meeting_id": meeting_id,
                        "meeting_date": meeting.get("meeting_date", ""),
                        "timestamp": meeting.get("timestamp", ""),
                        "obj": obj,
                    }
                )
    return rows


def _candidate_text(obj: dict[str, Any]) -> str:
    topics = obj.get("related_topics", [])
    topics_text = (
        " ".join(str(topic) for topic in topics if str(topic).strip())
        if isinstance(topics, list)
        else ""
    )
    return " ".join(
        [
            str(obj.get("type", "") or ""),
            str(obj.get("content", "") or ""),
            str(obj.get("evidence", "") or ""),
            topics_text,
        ]
    ).strip()


def _profile_items(tree: dict[str, Any]) -> list[dict[str, Any]]:
    profile = tree.get("project_profile", {})
    methods = profile.get("established_methods", [])
    if not isinstance(methods, list):
        return []
    items: list[dict[str, Any]] = []
    for index, method in enumerate(methods[:3], start=1):
        text = str(method or "").strip()
        if text:
            items.append(
                {
                    "obj_id": f"L3-established-method-{index:03d}",
                    "meeting_id": "",
                    "type": "method_change",
                    "content": text,
                    "importance": 0.7,
                    "quality": "normal",
                    "activity": "activity=active activation=0.70",
                    "reason": "l3_established_method",
                    "score": 0.62,
                }
            )
    return items


def build_prior_context_pack(
    *,
    tree: dict[str, Any],
    meeting_id: str,
    transcript: str,
    quality_index: dict[str, Any] | None = None,
    activity_index: dict[str, Any] | None = None,
    max_items: int = DEFAULT_PRIOR_CONTEXT_MAX_ITEMS,
) -> dict[str, Any]:
    transcript_preview = "\n".join(str(transcript or "").splitlines()[:180])
    rows = _iter_l1_rows(tree)
    latest_index = max((row["meeting_index"] for row in rows), default=-1)
    candidates: list[dict[str, Any]] = []

    for row in rows:
        if row["meeting_id"] == meeting_id:
            continue
        obj = row["obj"]
        obj_id = str(obj.get("obj_id", "")).strip()
        if not obj_id:
            continue
        obj_type = str(obj.get("type", "") or "").strip().lower()
        try:
            importance = float(obj.get("importance") or 0.0)
        except (TypeError, ValueError):
            importance = 0.0
        quality, quality_stale = _quality_for_obj(obj, quality_index)
        if quality == "weak" or quality_stale:
            continue

        match_score = _overlap_score(transcript_preview, _candidate_text(obj))
        is_recent = row["meeting_index"] >= max(0, latest_index - 2)
        is_durable = obj_type in DURABLE_CONTEXT_TYPES and importance >= 0.68
        is_open_thread = obj_type in OPEN_THREAD_TYPES and importance >= 0.45
        is_matched = match_score >= 0.045 and importance >= 0.35
        if not (is_durable or is_open_thread or is_matched):
            continue

        quality_bonus = {"strong": 0.12, "normal": 0.08, "tentative": -0.06}.get(quality, 0.0)
        reasons: list[str] = []
        if is_matched:
            reasons.append("transcript_match")
        if is_open_thread:
            reasons.append("open_thread")
        if is_durable:
            reasons.append("recent_high_importance" if is_recent else "high_importance")
        candidates.append(
            {
                "obj_id": obj_id,
                "meeting_id": row["meeting_id"],
                "meeting_date": row["meeting_date"],
                "type": obj_type,
                "content": str(obj.get("content", "") or ""),
                "importance": round(importance, 3),
                "quality": quality,
                "activity": format_memory_activity_tag(obj, activity_index),
                "reason": "+".join(reasons or ["context"]),
                "score": round(
                    0.46 * importance
                    + 0.30 * match_score
                    + quality_bonus
                    + (0.08 if is_recent else 0.0)
                    + (0.08 if is_open_thread else 0.0),
                    4,
                ),
            }
        )

    candidates.extend(_profile_items(tree))
    candidates.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("obj_id", ""))))
    items = candidates[: max(0, int(max_items))]
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
    return {
        "schema_version": PRIOR_CONTEXT_SCHEMA_VERSION,
        "meeting_id": meeting_id,
        "rules": [
            "Prior context is for disambiguation only.",
            "Do not use prior context as evidence for new L1 candidates.",
            "Every new L1 candidate must cite only the current transcript or current idea units.",
        ],
        "items": items,
    }


def format_prior_context_for_prompt(pack: dict[str, Any] | None) -> str:
    items = (pack or {}).get("items", [])
    if not isinstance(items, list) or not items:
        return (
            "Prior cross-meeting context: (none)\n"
            "Use only the current transcript as evidence for new L1 objects."
        )
    lines = [
        "Prior cross-meeting context (for disambiguation only, never evidence):",
        "- Do not use these items as evidence for new L1 candidates.",
        "- Every new L1 candidate must cite only the current transcript / idea units.",
    ]
    for item in items[:DEFAULT_PRIOR_CONTEXT_MAX_ITEMS]:
        lines.append(
            "  "
            f"[{item.get('obj_id', '?')}] "
            f"type={item.get('type', '?')} "
            f"quality={item.get('quality', 'unknown')} "
            f"{item.get('activity', 'activity=unknown')} "
            f"reason={item.get('reason', 'context')} "
            f"content={item.get('content', '')}"
        )
    return "\n".join(lines)
