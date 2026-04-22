"""Shared importance calibration for long-term memory extraction.

The model still proposes an importance score, but this module keeps the scale
consistent across full-transcript and incremental extraction paths.
"""

from __future__ import annotations

from typing import Any


MIN_IMPORTANCE_THRESHOLD = 0.35

IMPORTANCE_SCALE = """
0.90-1.00: project-level or cross-meeting decisions/method changes that steer the work.
0.70-0.89: affects next research steps, experimental design, data quality, or unresolved blockers.
0.50-0.69: useful meeting-level memory with clear follow-up value.
0.35-0.49: weak but durable context; keep only if it may help later recall.
0.00-0.34: local chatter, transient logistics, or unsupported claims; discard as L1.
""".strip()

_TYPE_RETAINED_FLOORS = {
    "decision": 0.50,
    "method_change": 0.50,
    "result": 0.40,
    "todo": 0.40,
    "open_question": 0.40,
    "argument": 0.35,
}

_HIGH_IMPACT_MARKERS = (
    "跨會議",
    "整個",
    "核心",
    "長期",
    "阻擋",
    "影響後續",
    "下一步",
    "後續",
    "實驗設計",
    "方法",
    "架構",
    "決策",
    "決定",
    "current",
    "future",
    "next step",
    "block",
    "blocked",
    "blocking",
    "design",
    "method",
    "pipeline",
    "architecture",
    "cross-meeting",
    "long-term",
)

_LOW_VALUE_MARKERS = (
    "閒聊",
    "寒暄",
    "休息",
    "午餐",
    "行政",
    "logistics",
    "lunch",
    "break",
    "chitchat",
)


def normalize_importance_score(value: Any, fallback: float = 0.5) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = fallback
    return max(0.0, min(1.0, round(score, 2)))


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def calibrate_l1_importance(
    obj_type: str,
    model_importance: Any,
    *,
    content: str = "",
    evidence: str = "",
    related_topics: list[str] | None = None,
) -> float:
    """Normalize an L1 object's score without letting type alone inflate noise."""
    score = normalize_importance_score(model_importance)
    obj_type = str(obj_type or "").lower()
    text = f"{content}\n{evidence}".strip()
    topics = related_topics or []

    if score >= MIN_IMPORTANCE_THRESHOLD:
        score = max(score, _TYPE_RETAINED_FLOORS.get(obj_type, MIN_IMPORTANCE_THRESHOLD))

    if evidence.strip():
        score += 0.02
    if topics:
        score += min(0.03, 0.01 * len([topic for topic in topics if str(topic).strip()]))
    if _contains_any(text, _HIGH_IMPACT_MARKERS):
        score += 0.08
    if _contains_any(text, _LOW_VALUE_MARKERS):
        score -= 0.08

    return normalize_importance_score(score)


def episode_count_floor(episode_count: int) -> float:
    """Evidence floor for issues that recur in separated transcript episodes."""
    count = max(0, int(episode_count or 0))
    if count <= 0:
        return 0.0
    return normalize_importance_score(min(0.85, 0.40 + count * 0.12))


def calibrate_issue_importance(
    model_importance: Any,
    *,
    episode_count: int = 0,
    status: str = "open",
) -> float:
    """Combine model judgment with an evidence floor from issue recurrence."""
    score = normalize_importance_score(model_importance)
    score = max(score, episode_count_floor(episode_count))

    clean_status = str(status or "").lower()
    if clean_status == "unclear":
        score = min(score, 0.65)
    elif clean_status in {"resolved", "superseded"} and score < 0.8:
        score = max(score - 0.05, MIN_IMPORTANCE_THRESHOLD)

    return normalize_importance_score(score)
