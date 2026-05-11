"""Deterministic topic-state synthesis for generated L2/L3 sidecars."""

from __future__ import annotations

import re
from typing import Any


TRANSITION_RE = re.compile(
    r"\b("
    r"because|why|rationale|reason|therefore|so that|tradeoff|trade-off|"
    r"shift|shifted|move|moved|replace|replaced|instead|from|toward|"
    r"decide|decided|adopt|adopted|reject|rejected|avoid|risk|problem|issue"
    r")\b",
    re.IGNORECASE,
)

TENSION_RE = re.compile(
    r"\b("
    r"open|unresolved|still needs|whether|unclear|risk|concern|tradeoff|"
    r"trade-off|but|however|question|issue|decide"
    r")\b",
    re.IGNORECASE,
)


def _clean_text(value: Any, *, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _timeline_date(row: dict[str, Any]) -> str:
    return str(row.get("meeting_date") or row.get("meeting_id") or "")


def _timeline_summary(row: dict[str, Any], *, limit: int = 260) -> str:
    return _clean_text(row.get("summary", row.get("content", "")), limit=limit)


def _obj_id(row: dict[str, Any]) -> str:
    return str(row.get("obj_id", "") or "").strip()


def _representative_l1_ids(rows: list[dict[str, Any]], *, max_ids: int = 5) -> list[str]:
    if not rows:
        return []
    picks: list[dict[str, Any]] = []
    picks.append(rows[0])
    if len(rows) > 2:
        picks.append(rows[len(rows) // 2])
    if len(rows) > 1:
        picks.append(rows[-1])
    for row in rows:
        if len(picks) >= max_ids:
            break
        picks.append(row)

    seen: set[str] = set()
    output: list[str] = []
    for row in picks:
        obj_id = _obj_id(row)
        if obj_id and obj_id not in seen:
            output.append(obj_id)
            seen.add(obj_id)
    return output


def _first_matching_summary(rows: list[dict[str, Any]], pattern: re.Pattern[str]) -> str:
    for row in rows:
        summary = _timeline_summary(row)
        if pattern.search(summary):
            return summary
    return ""


def build_topic_state(
    label: str,
    timeline: list[dict[str, Any]] | list[Any],
    assignment_criteria: list[str] | None = None,
) -> dict[str, Any]:
    """Build a compact, deterministic state summary for a topic node.

    The result is intentionally template based. It is generated sidecar
    metadata only; raw L1 evidence and timeline rows remain the source of truth.
    """

    rows = [row for row in timeline if isinstance(row, dict)]
    rows.sort(key=_timeline_date)
    label = _clean_text(label, limit=120) or "topic"
    criteria = [_clean_text(item, limit=80) for item in assignment_criteria or [] if str(item).strip()]

    if not rows:
        empty_state = f"No linked L1 evidence is currently assigned to {label}."
        return {
            "current_state": empty_state,
            "evolution_summary": "",
            "latest_position": "",
            "key_rationale": "",
            "open_tensions": "",
            "representative_l1_ids": [],
            "state_source": "deterministic_topic_state_v1",
        }

    earliest = rows[0]
    latest = rows[-1]
    earliest_summary = _timeline_summary(earliest)
    latest_summary = _timeline_summary(latest)
    earliest_ref = " ".join(
        part for part in [_timeline_date(earliest), _obj_id(earliest)] if part
    ).strip()
    latest_ref = " ".join(part for part in [_timeline_date(latest), _obj_id(latest)] if part).strip()

    if len(rows) == 1:
        evolution = f"{label} is currently grounded by one L1 evidence item: {latest_summary}"
    else:
        evolution = (
            f"{label} evolved from {earliest_ref}: {earliest_summary} "
            f"to {latest_ref}: {latest_summary}"
        )

    rationale = _first_matching_summary(rows, TRANSITION_RE)
    if not rationale and criteria:
        rationale = "Assignment criteria: " + "; ".join(criteria[:3])
    if not rationale:
        rationale = earliest_summary

    tension = _first_matching_summary(list(reversed(rows)), TENSION_RE)
    if not tension:
        tension = "No explicit unresolved tension is visible in the selected L1 evidence."

    current_state = (
        f"{label}: latest state from {latest_ref or 'latest evidence'} is {latest_summary}"
    )
    if len(rows) > 1:
        current_state += f" Earlier evidence began with {earliest_summary}"

    return {
        "current_state": _clean_text(current_state, limit=420),
        "evolution_summary": _clean_text(evolution, limit=520),
        "latest_position": _clean_text(latest_summary, limit=320),
        "key_rationale": _clean_text(rationale, limit=320),
        "open_tensions": _clean_text(tension, limit=320),
        "representative_l1_ids": _representative_l1_ids(rows),
        "state_source": "deterministic_topic_state_v1",
    }
