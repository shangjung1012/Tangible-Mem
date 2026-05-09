from __future__ import annotations

import re
from typing import Any

SHORT_TERM_HINTS = (
    "目前",
    "現在",
    "最新",
    "最近",
    "今天",
    "上次",
    "下一步",
    "待辦",
    "todo",
    "owner",
    "負責",
    "進度",
    "status",
    "next step",
    "action item",
)

LONG_TERM_HINTS = (
    "為什麼",
    "原因",
    "演進",
    "歷史",
    "之前",
    "後來",
    "當初",
    "設計",
    "架構",
    "主題",
    "方法變更",
    "決策",
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
)


def _contains_any(query: str, hints: tuple[str, ...]) -> bool:
    q = query.lower()
    return any(hint.lower() in q for hint in hints)


def _looks_like_meeting_memory_query(query: str) -> bool:
    return bool(
        re.search(
            r"(會議|記憶|memory|meeting|待辦|進度|決策|設計|架構|主題|l1|l2|l3|promotion|promote|topic|retrieve|recall)",
            query,
            flags=re.IGNORECASE,
        )
    )


def plan_memory_retrieval(query: str) -> dict[str, Any]:
    """Route a user query to short-term, long-term, both, or no memory.

    This deterministic first-pass router is intentionally cheap and testable.
    A later LLM planner can replace or augment it without changing callers.
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

    if has_short and has_long:
        return {
            "targets": ["short_term", "long_term"],
            "strategy": "both",
            "reason": "query asks for recent state and historical rationale",
            "confidence": 0.85,
        }
    if has_short:
        return {
            "targets": ["short_term"],
            "strategy": "short_term_only",
            "reason": "query asks for recent status, TODOs, owners, or next steps",
            "confidence": 0.8,
        }
    if has_long:
        return {
            "targets": ["long_term"],
            "strategy": "long_term_only",
            "reason": "query asks for history, rationale, method evolution, or cross-meeting context",
            "confidence": 0.8,
        }
    if _looks_like_meeting_memory_query(clean_query):
        return {
            "targets": ["short_term", "long_term"],
            "strategy": "both",
            "reason": "ambiguous meeting-memory query; retrieve both for coverage",
            "confidence": 0.55,
        }
    return {
        "targets": [],
        "strategy": "none",
        "reason": "query does not appear to need meeting memory",
        "confidence": 0.7,
    }
