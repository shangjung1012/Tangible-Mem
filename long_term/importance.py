"""Shared importance calibration for long-term memory extraction.

The model still proposes an importance score, but this module keeps the scale
consistent across full-transcript and incremental extraction paths.
"""

from __future__ import annotations

from typing import Any


MIN_IMPORTANCE_THRESHOLD = 0.35
LINKED_ISSUE_IMPORTANCE_BONUS_THRESHOLD = 0.70
MAX_LINKED_ISSUE_IMPORTANCE_BONUS = 0.08

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

_SOCIAL_LOW_VALUE_MARKERS = (
    "提拉米蘇",
    "燒烤",
    "品嚐",
    "聚餐",
    "週末活動",
    "barbecue",
    "bbq",
    "tasting",
    "dessert",
    "party",
    "social event",
    "weekend activity",
)

_LOGISTICS_LOW_VALUE_MARKERS = (
    "錄音操作",
    "錄音說明",
    "錄音指示",
    "耳機舒適度",
    "更舒適的耳機",
    "電池開關",
    "關閉麥克風",
    "meeting moved",
    "recording instructions",
    "headset comfort",
    "turn off the microphones",
    "turn off microphones",
    "remote control",
    "battery switch",
)

_GENERIC_ISSUE_MARKERS = (
    "會議議程",
    "週三會議議程",
    "weekly meeting agenda",
    "meeting agenda",
    "agenda for the meeting",
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


def is_social_low_value_text(text: str) -> bool:
    return _contains_any(text, _SOCIAL_LOW_VALUE_MARKERS)


def is_logistics_low_value_text(text: str) -> bool:
    return _contains_any(text, _LOGISTICS_LOW_VALUE_MARKERS)


def is_low_value_text(text: str) -> bool:
    return (
        _contains_any(text, _LOW_VALUE_MARKERS)
        or is_social_low_value_text(text)
        or is_logistics_low_value_text(text)
    )


def is_generic_issue_text(title: str, summary: str = "") -> bool:
    title_text = str(title or "").strip()
    combined = f"{title_text}\n{summary}".strip()
    title_lower = title_text.lower()
    if _contains_any(combined, _GENERIC_ISSUE_MARKERS):
        return True
    if "agenda" in title_lower:
        return True
    if "議程" in title_text and ("會議" in title_text or "週三" in title_text):
        return True
    return False


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
    title: str = "",
    summary: str = "",
) -> float:
    """Combine model judgment with an evidence floor from issue recurrence."""
    score = normalize_importance_score(model_importance)
    score = max(score, episode_count_floor(episode_count))
    text = f"{title}\n{summary}".strip()

    if is_generic_issue_text(title, summary):
        score = min(score, 0.60)
    if is_social_low_value_text(text):
        score = min(score, 0.50)
    if is_logistics_low_value_text(text):
        score = min(score, 0.55)

    clean_status = str(status or "").lower()
    if clean_status == "unclear":
        score = min(score, 0.65)
    elif clean_status in {"resolved", "superseded"} and score < 0.8:
        score = max(score - 0.05, MIN_IMPORTANCE_THRESHOLD)

    return normalize_importance_score(score)


def linked_issue_importance_bonus(issue_importance: Any) -> float:
    """Small bounded L1 bonus for objects linked to recurring high-importance issues."""
    score = normalize_importance_score(issue_importance, fallback=0.0)
    if score < LINKED_ISSUE_IMPORTANCE_BONUS_THRESHOLD:
        return 0.0

    span = 1.0 - LINKED_ISSUE_IMPORTANCE_BONUS_THRESHOLD
    scaled = (score - LINKED_ISSUE_IMPORTANCE_BONUS_THRESHOLD) / span
    return normalize_importance_score(
        min(MAX_LINKED_ISSUE_IMPORTANCE_BONUS, scaled * MAX_LINKED_ISSUE_IMPORTANCE_BONUS),
        fallback=0.0,
    )


def apply_linked_issue_importance_bonus(
    object_importance: Any,
    issue_importance: Any,
) -> float:
    """Propagate issue recurrence into a linked raw L1 score without replacing it."""
    base = normalize_importance_score(object_importance)
    bonus = linked_issue_importance_bonus(issue_importance)
    return normalize_importance_score(base + bonus)
