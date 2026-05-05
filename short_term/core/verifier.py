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
    from short_term.core.schema import (
        ACTION_ITEM_STATUS,
        EXPERIMENT_STATUS,
        METHOD_CHANGE_STATUS,
        PRIORITY_LEVELS,
    )


CONFIDENCE_THRESHOLD = 0.45
_EVIDENCE_RE = re.compile(r"L(?P<start>\d+)(?:\s*-\s*L?(?P<end>\d+))?")
_ACTION_ID_RE = re.compile(r"^A\d{3}$")
_METHOD_ID_RE = re.compile(r"^M\d{3}$")
_TODO_ID_RE = re.compile(r"^E\d{3}$")

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
        warnings = list(candidate.get("warnings", [])) if isinstance(candidate.get("warnings"), list) else []

        allowed_agents = SECTION_AGENT_ALLOWLIST.get(section)
        if allowed_agents is None:
            reasons.append("unknown_section")
        elif agent not in allowed_agents:
            reasons.append("agent_section_mismatch")

        evidence = _normalize_candidate_evidence(candidate, payload)
        if not evidence:
            warnings.append("missing_evidence")
        elif not _evidence_lines_are_allowed(evidence, allowed_line_numbers):
            warnings.append("evidence_line_not_read")

        confidence = _safe_float(payload.get("confidence"), 0.0)
        if confidence < CONFIDENCE_THRESHOLD:
            reasons.append("low_confidence")

        operation = str(payload.get("operation") or candidate.get("operation") or "").strip()
        writes_memory = operation != "no_op"
        if writes_memory:
            if not evidence:
                reasons.append("missing_evidence")
            elif not _evidence_lines_are_allowed(evidence, allowed_line_numbers):
                reasons.append("evidence_line_not_read")
        target_id = str(candidate.get("target_id", "")).strip()
        if target_id:
            if section == "action_items" and not str(payload.get("item_id", "")).strip():
                payload["item_id"] = target_id
            elif section == "method_changes" and not str(payload.get("change_id", "")).strip():
                payload["change_id"] = target_id
            elif section == "experiment_todos" and not str(payload.get("todo_id", "")).strip():
                payload["todo_id"] = target_id
        if section == "action_items":
            _verify_action(payload, operation, existing_action_ids, reasons)
            if operation == "create" and _duplicate_text(
                payload.get("title"),
                current_memory.get("action_items", []),
                "title",
            ):
                reasons.append("duplicate_create")
        elif section == "method_changes":
            _verify_method(payload, operation, existing_method_ids, reasons)
            if operation == "create" and _duplicate_text(
                payload.get("topic"),
                current_memory.get("method_changes", []),
                "topic",
            ):
                reasons.append("duplicate_create")
        elif section == "experiment_todos":
            _verify_experiment(payload, operation, existing_todo_ids, reasons)
            _verify_related_action_item_ids(payload, existing_action_ids, reasons)
            if operation == "create" and _duplicate_text(
                payload.get("description"),
                current_memory.get("experiment_todos", []),
                "description",
            ):
                reasons.append("duplicate_create")
        elif section == "meeting_window":
            if not str(payload.get("meeting_id", "")).strip():
                reasons.append("missing_meeting_id")
        elif section == "next_meeting_focus":
            if operation != "no_op" and not str(payload.get("text", "")).strip():
                reasons.append("missing_focus_text")

        if reasons:
            rejected.append(
                {
                    **candidate,
                    "warnings": sorted(set(warnings)),
                    "rejection_reasons": sorted(set(reasons)),
                }
            )
        else:
            verified.append({**candidate, "warnings": sorted(set(warnings))})

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
    if item_id and not _ACTION_ID_RE.fullmatch(item_id):
        if operation == "create":
            payload.pop("item_id", None)
        elif operation != "no_op":
            reasons.append("invalid_action_item_id")
    if operation not in {"create", "update", "close", "no_op"}:
        reasons.append("invalid_operation")
    if operation in {"update", "close"} and item_id not in existing_ids:
        reasons.append("update_unknown_id")
    if operation == "create" and item_id and item_id in existing_ids:
        reasons.append("create_collides_existing_id")
    status = str(payload.get("status", "")).strip()
    if (operation == "create" or status) and status not in ACTION_ITEM_STATUS:
        reasons.append("invalid_status")
    priority = str(payload.get("priority", "")).strip()
    if (operation == "create" or priority) and priority not in PRIORITY_LEVELS:
        reasons.append("invalid_priority")
    if operation == "create" and not str(payload.get("title", "")).strip():
        reasons.append("missing_title")
    if operation == "create" and not str(payload.get("owner", "")).strip():
        reasons.append("missing_owner")
    if operation == "create" and not str(payload.get("proposer", "")).strip():
        reasons.append("missing_proposer")


def _verify_method(
    payload: dict[str, Any],
    operation: str,
    existing_ids: set[str],
    reasons: list[str],
) -> None:
    change_id = str(payload.get("change_id", "")).strip()
    if change_id and not _METHOD_ID_RE.fullmatch(change_id):
        if operation == "create":
            payload.pop("change_id", None)
            change_id = ""
        elif operation != "no_op":
            reasons.append("invalid_method_change_id")
    if operation not in {"create", "update", "no_op"}:
        reasons.append("invalid_operation")
    if operation == "update" and change_id not in existing_ids:
        reasons.append("update_unknown_id")
    if operation == "create" and change_id and change_id in existing_ids:
        reasons.append("create_collides_existing_id")
    status = str(payload.get("status", "")).strip()
    if (operation == "create" or status) and status not in METHOD_CHANGE_STATUS:
        reasons.append("invalid_status")
    required = ("topic", "after", "reason") if operation == "create" else ()
    for key in required:
        if not str(payload.get(key, "")).strip():
            reasons.append(f"missing_{key}")
    if operation == "create" and _looks_like_inventory_only_method_change(payload):
        reasons.append("inventory_not_method_change")
    if operation == "create" and _looks_like_unresolved_method_change(payload):
        reasons.append("unresolved_method_change")


def _verify_experiment(
    payload: dict[str, Any],
    operation: str,
    existing_ids: set[str],
    reasons: list[str],
) -> None:
    todo_id = str(payload.get("todo_id", "")).strip()
    if todo_id and not _TODO_ID_RE.fullmatch(todo_id):
        if operation == "create":
            payload.pop("todo_id", None)
            todo_id = ""
        elif operation != "no_op":
            reasons.append("invalid_experiment_todo_id")
    if operation not in {"create", "update", "close", "no_op"}:
        reasons.append("invalid_operation")
    if operation in {"update", "close"} and todo_id not in existing_ids:
        reasons.append("update_unknown_id")
    if operation == "create" and todo_id and todo_id in existing_ids:
        reasons.append("create_collides_existing_id")
    status = str(payload.get("status", "")).strip()
    if (operation == "create" or status) and status not in EXPERIMENT_STATUS:
        reasons.append("invalid_status")
    if operation == "create" and not str(payload.get("description", "")).strip():
        reasons.append("missing_description")
    if operation == "create" and not str(payload.get("owner", "")).strip():
        reasons.append("missing_owner")
    if operation == "create" and status == "completed":
        reasons.append("completed_create_not_allowed")


def _verify_related_action_item_ids(
    payload: dict[str, Any],
    existing_action_ids: set[str],
    reasons: list[str],
) -> None:
    related = payload.get("related_action_item_ids")
    if related in (None, ""):
        return
    if not isinstance(related, list):
        reasons.append("invalid_related_action_item_ids")
        return
    for value in related:
        action_id = str(value).strip()
        if not action_id:
            continue
        if not _ACTION_ID_RE.fullmatch(action_id):
            reasons.append("invalid_related_action_item_id")
        elif action_id not in existing_action_ids:
            reasons.append("related_action_item_unknown_id")


def _evidence_lines_are_allowed(evidence: str, allowed: set[int]) -> bool:
    if not allowed:
        return False
    line_numbers = _evidence_line_numbers(evidence)
    if not line_numbers:
        return False
    for line_number in line_numbers:
        if line_number not in allowed:
            return False
    return True


def _normalize_candidate_evidence(
    candidate: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    evidence = str(payload.get("evidence", "")).strip()
    if _evidence_line_numbers(evidence):
        return evidence

    line_numbers = _embedded_evidence_line_numbers(candidate, payload)
    if not line_numbers:
        return evidence
    normalized = _format_evidence_lines(line_numbers)
    payload["evidence"] = normalized
    return normalized


def _embedded_evidence_line_numbers(
    candidate: dict[str, Any],
    payload: dict[str, Any],
) -> list[int]:
    numbers: list[int] = []
    evidence_lines = candidate.get("evidence_lines")
    if isinstance(evidence_lines, list):
        for value in evidence_lines:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                numbers.append(number)
    numbers.extend(_evidence_line_numbers_from_value(payload, skip_keys={"evidence"}))
    return sorted(set(numbers))


def _evidence_line_numbers_from_value(
    value: Any,
    *,
    skip_keys: set[str],
) -> list[int]:
    if isinstance(value, dict):
        numbers: list[int] = []
        for key, nested in value.items():
            if str(key) in skip_keys:
                continue
            numbers.extend(
                _evidence_line_numbers_from_value(nested, skip_keys=skip_keys)
            )
        return numbers
    if isinstance(value, list):
        numbers: list[int] = []
        for item in value:
            numbers.extend(_evidence_line_numbers_from_value(item, skip_keys=skip_keys))
        return numbers
    if isinstance(value, str):
        return _evidence_line_numbers(value)
    return []


def _evidence_line_numbers(evidence: str) -> list[int]:
    numbers: list[int] = []
    for match in _EVIDENCE_RE.finditer(str(evidence or "")):
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        if end < start:
            start, end = end, start
        numbers.extend(range(start, end + 1))
    return sorted(set(numbers))


def _format_evidence_lines(values: list[int]) -> str:
    numbers = sorted(set(number for number in values if number > 0))
    if not numbers:
        return ""
    ranges: list[str] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(_format_evidence_range(start, previous))
        start = previous = number
    ranges.append(_format_evidence_range(start, previous))
    return ", ".join(ranges)


def _format_evidence_range(start: int, end: int) -> str:
    if start == end:
        return f"L{start}"
    return f"L{start}-L{end}"


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


def _duplicate_text(value: Any, rows: Any, key: str) -> bool:
    needle = _normalize_text(value)
    if len(needle) < 6 or not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        haystack = _normalize_text(row.get(key))
        if needle and haystack and (needle == haystack or needle in haystack or haystack in needle):
            return True
    return False


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _looks_like_inventory_only_method_change(payload: dict[str, Any]) -> bool:
    topic = _normalize_text(payload.get("topic"))
    before = _normalize_text(payload.get("before"))
    after = _normalize_text(payload.get("after"))
    reason = _normalize_text(payload.get("reason"))
    combined = " ".join(part for part in (topic, before, after, reason) if part)
    if not combined:
        return False
    inventory_markers = (
        "inventory",
        "microphone",
        "setup for recording",
        "multiple microphones were used",
        "to document the recording setup",
        "document the recording setup",
        "described all microphones",
        "recording setup",
    )
    if before == "not specified" and any(marker in combined for marker in inventory_markers):
        return True
    return False


def _looks_like_unresolved_method_change(payload: dict[str, Any]) -> bool:
    after = _normalize_text(payload.get("after"))
    reason = _normalize_text(payload.get("reason"))
    combined = " ".join(part for part in (after, reason) if part)
    unresolved_markers = (
        "unresolved discussion",
        "needs to be clarified",
        "conflicting estimates",
        "not established",
        "to plan for",
    )
    return any(marker in combined for marker in unresolved_markers)
