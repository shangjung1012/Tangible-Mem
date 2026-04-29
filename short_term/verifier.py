from __future__ import annotations

import re
from collections import Counter
from typing import Any

try:
    from .schema import (
        ACTION_ITEM_STATUS,
        EXPERIMENT_STATUS,
        METHOD_CHANGE_STATUS,
        PRIORITY_LEVELS,
    )
except ImportError:  # pragma: no cover
    from schema import (
        ACTION_ITEM_STATUS,
        EXPERIMENT_STATUS,
        METHOD_CHANGE_STATUS,
        PRIORITY_LEVELS,
    )


CONFIDENCE_THRESHOLD = 0.45
_EVIDENCE_RE = re.compile(r"L(?P<start>\d+)(?:\s*-\s*L?(?P<end>\d+))?")

SECTION_AGENT_ALLOWLIST = {
    "meeting_window": {"meeting_summary_agent"},
    "action_items": {"action_item_agent"},
    "method_changes": {"method_change_agent"},
    "experiment_todos": {"experiment_todo_agent"},
    "next_meeting_focus": {"next_focus_agent"},
}


def verify_candidates(
    candidates: list[dict[str, Any]],
    *,
    current_memory: dict[str, Any],
    allowed_line_numbers: set[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    existing_action_ids = _existing_ids(current_memory, "action_items", "item_id")
    existing_method_ids = _existing_ids(current_memory, "method_changes", "change_id")
    existing_todo_ids = _existing_ids(current_memory, "experiment_todos", "todo_id")

    for candidate in candidates:
        reasons: list[str] = []
        section = str(candidate.get("section", "")).strip()
        agent = str(candidate.get("agent", "")).strip()
        payload = candidate.get("payload")
        if not isinstance(payload, dict):
            reasons.append("payload_not_object")
            payload = {}

        allowed_agents = SECTION_AGENT_ALLOWLIST.get(section)
        if allowed_agents is None:
            reasons.append("unknown_section")
        elif agent not in allowed_agents:
            reasons.append("agent_section_mismatch")

        evidence = str(payload.get("evidence", "")).strip()
        if not evidence:
            reasons.append("missing_evidence")
        elif not _evidence_lines_are_allowed(evidence, allowed_line_numbers):
            reasons.append("evidence_line_not_read")

        confidence = _safe_float(payload.get("confidence"), 0.0)
        if confidence < CONFIDENCE_THRESHOLD:
            reasons.append("low_confidence")

        operation = str(payload.get("operation", "")).strip()
        if section == "action_items":
            _verify_action(payload, operation, existing_action_ids, reasons)
        elif section == "method_changes":
            _verify_method(payload, operation, existing_method_ids, reasons)
        elif section == "experiment_todos":
            _verify_experiment(payload, operation, existing_todo_ids, reasons)
        elif section == "meeting_window":
            if not str(payload.get("meeting_id", "")).strip():
                reasons.append("missing_meeting_id")
        elif section == "next_meeting_focus":
            if not str(payload.get("text", "")).strip():
                reasons.append("missing_focus_text")

        if reasons:
            rejected.append({**candidate, "rejection_reasons": sorted(set(reasons))})
        else:
            verified.append(candidate)

    reason_counts = Counter(
        reason
        for row in rejected
        for reason in row.get("rejection_reasons", [])
    )
    return verified, rejected, dict(reason_counts)


def _verify_action(
    payload: dict[str, Any],
    operation: str,
    existing_ids: set[str],
    reasons: list[str],
) -> None:
    item_id = str(payload.get("item_id", "")).strip()
    if operation not in {"create", "update"}:
        reasons.append("invalid_operation")
    if operation == "update" and item_id not in existing_ids:
        reasons.append("update_unknown_id")
    if operation == "create" and item_id and item_id in existing_ids:
        reasons.append("create_collides_existing_id")
    if str(payload.get("status", "")).strip() not in ACTION_ITEM_STATUS:
        reasons.append("invalid_status")
    if str(payload.get("priority", "")).strip() not in PRIORITY_LEVELS:
        reasons.append("invalid_priority")
    if not str(payload.get("title", "")).strip():
        reasons.append("missing_title")
    if not str(payload.get("owner", "")).strip():
        reasons.append("missing_owner")
    if not str(payload.get("proposer", "")).strip():
        reasons.append("missing_proposer")


def _verify_method(
    payload: dict[str, Any],
    operation: str,
    existing_ids: set[str],
    reasons: list[str],
) -> None:
    change_id = str(payload.get("change_id", "")).strip()
    if operation not in {"create", "update"}:
        reasons.append("invalid_operation")
    if operation == "update" and change_id not in existing_ids:
        reasons.append("update_unknown_id")
    if operation == "create" and change_id and change_id in existing_ids:
        reasons.append("create_collides_existing_id")
    if str(payload.get("status", "")).strip() not in METHOD_CHANGE_STATUS:
        reasons.append("invalid_status")
    for key in ("topic", "after", "reason"):
        if not str(payload.get(key, "")).strip():
            reasons.append(f"missing_{key}")


def _verify_experiment(
    payload: dict[str, Any],
    operation: str,
    existing_ids: set[str],
    reasons: list[str],
) -> None:
    todo_id = str(payload.get("todo_id", "")).strip()
    if operation not in {"create", "update"}:
        reasons.append("invalid_operation")
    if operation == "update" and todo_id not in existing_ids:
        reasons.append("update_unknown_id")
    if operation == "create" and todo_id and todo_id in existing_ids:
        reasons.append("create_collides_existing_id")
    if str(payload.get("status", "")).strip() not in EXPERIMENT_STATUS:
        reasons.append("invalid_status")
    if not str(payload.get("description", "")).strip():
        reasons.append("missing_description")
    if not str(payload.get("owner", "")).strip():
        reasons.append("missing_owner")


def _evidence_lines_are_allowed(evidence: str, allowed: set[int]) -> bool:
    if not allowed:
        return False
    matches = list(_EVIDENCE_RE.finditer(evidence))
    if not matches:
        return False
    for match in matches:
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        if end < start:
            start, end = end, start
        for line_number in range(start, end + 1):
            if line_number not in allowed:
                return False
    return True


def _existing_ids(memory: dict[str, Any], section: str, id_key: str) -> set[str]:
    return {
        str(row.get(id_key, "")).strip()
        for row in memory.get(section, [])
        if isinstance(row, dict) and str(row.get(id_key, "")).strip()
    }


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
