from __future__ import annotations

import re
from typing import Any

SHORT_TERM_HINTS = (
    "目前",
    "現在",
    "最新",
    "最近",
    "待辦",
    "下一步",
    "進度",
    "狀態",
    "todo",
    "owner",
    "負責",
    "action",
    "status",
    "next step",
    "action item",
)

LONG_TERM_HINTS = (
    "為什麼",
    "原因",
    "怎麼演變",
    "演變",
    "演進",
    "歷史",
    "之前",
    "架構",
    "設計",
    "跨會議",
    "長期",
    "long-term",
    "l1",
    "l2",
    "l3",
    "child l2",
    "promotion",
    "promote",
    "topic",
    "rationale",
    "history",
    "evolution",
    "across meetings",
    "manager-agent",
)


def _contains_any(query: str, hints: tuple[str, ...]) -> bool:
    q = query.lower()
    return any(hint.lower() in q for hint in hints)


def _looks_like_meeting_memory_query(query: str) -> bool:
    return bool(
        re.search(
            r"(會議|記憶|memory|meeting|待辦|進度|架構|設計|演進|演變|之前|長期|短期|l1|l2|l3|promotion|promote|topic|retrieve|retrieval|recall|manager-agent)",
            query,
            flags=re.IGNORECASE,
        )
    )


def plan_memory_retrieval(query: str) -> dict[str, Any]:
    """Route a user query to the memory layers.

    Meeting-memory retrieval is intentionally long-term-on by default. Recent
    status hints can add short-term context, but they should not suppress the
    long-term topic map and evidence-first retrieval path.
    """
    clean_query = str(query or "").strip()
    if not clean_query:
        return {
            "targets": [],
            "strategy": "none",
            "reason": "empty query",
            "confidence": 1.0,
        }

    has_short = _contains_any(clean_query, SHORT_TERM_HINTS)
    has_long = _contains_any(clean_query, LONG_TERM_HINTS)
    meeting_memory_query = _looks_like_meeting_memory_query(clean_query)

    if has_short:
        return {
            "targets": ["short_term", "long_term"],
            "strategy": "both",
            "reason": "query has recent-status hints; include long-term context as background",
            "confidence": 0.85 if meeting_memory_query or has_long else 0.75,
        }
    if has_long:
        return {
            "targets": ["long_term"],
            "strategy": "long_term_only",
            "reason": "query asks for history, rationale, method evolution, or cross-meeting context",
            "confidence": 0.8,
        }
    if meeting_memory_query:
        return {
            "targets": ["long_term"],
            "strategy": "long_term_only",
            "reason": "meeting-memory query; retrieve long-term topic context",
            "confidence": 0.6,
        }
    return {
        "targets": [],
        "strategy": "none",
        "reason": "query does not appear to need meeting memory",
        "confidence": 0.7,
    }
