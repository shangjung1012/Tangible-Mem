"""Conflict resolution and final L1 patch reduction for multi-agent output."""

from __future__ import annotations

from typing import Any

from importance import MIN_IMPORTANCE_THRESHOLD, calibrate_l1_importance
from multi_agent_state import ConflictDecision, GroundedCandidate
from multi_agent_tools import clamp_float, jaccard, tokenize, unique_strings

TYPE_PRIORITY = {
    "method_change": 3,
    "decision": 2,
    "result": 1,
    "todo": 1,
}

_DURABLE_MARKERS = (
    "adopt",
    "decide",
    "decision",
    "change",
    "method",
    "strategy",
    "architecture",
    "pipeline",
    "implement",
    "evaluate",
    "baseline",
    "memory",
    "retrieval",
    "tool calling",
    "long-term",
    "short-term",
    "決定",
    "採用",
    "改",
    "方法",
    "策略",
    "架構",
    "流程",
    "實作",
    "評估",
    "記憶",
    "長期",
    "短期",
    "檢索",
)


def _as_candidate_dict(candidate: GroundedCandidate | dict[str, Any]) -> dict[str, Any]:
    if isinstance(candidate, dict):
        return dict(candidate)
    return {
        "candidate_id": candidate.candidate_id,
        "type": candidate.type,
        "source_unit_ids": candidate.source_unit_ids,
        "content": candidate.content,
        "importance": candidate.importance,
        "confidence": candidate.confidence,
        "rationale": candidate.rationale,
        "related_topics": candidate.related_topics,
        "extraction_scope": candidate.extraction_scope,
        "segment_ids": candidate.segment_ids,
        "evidence_lines": candidate.evidence_lines,
        "evidence_quote": candidate.evidence_quote,
        "support_score": candidate.support_score,
        "grounding_note": candidate.grounding_note,
    }


def _same_span(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_lines = set(left.get("evidence_lines", []))
    right_lines = set(right.get("evidence_lines", []))
    if not left_lines or not right_lines:
        return False
    return bool(left_lines & right_lines)


def _merge_candidate(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    preferred, other = left, right
    if TYPE_PRIORITY.get(str(right.get("type", "")), 0) > TYPE_PRIORITY.get(
        str(left.get("type", "")),
        0,
    ):
        preferred, other = right, left
    merged = dict(preferred)
    merged["candidate_id"] = f"{preferred.get('candidate_id')}+{other.get('candidate_id')}"
    merged["importance"] = max(
        clamp_float(preferred.get("importance", 0.5)),
        clamp_float(other.get("importance", 0.5)),
    )
    merged["confidence"] = max(
        clamp_float(preferred.get("confidence", 0.5)),
        clamp_float(other.get("confidence", 0.5)),
    )
    merged["related_topics"] = unique_strings(
        list(preferred.get("related_topics", [])) + list(other.get("related_topics", []))
    )
    merged["source_unit_ids"] = unique_strings(
        list(preferred.get("source_unit_ids", [])) + list(other.get("source_unit_ids", []))
    )
    merged["segment_ids"] = unique_strings(
        list(preferred.get("segment_ids", [])) + list(other.get("segment_ids", []))
    )
    merged["evidence_lines"] = sorted(
        set(preferred.get("evidence_lines", [])) | set(other.get("evidence_lines", []))
    )
    if len(str(other.get("evidence_quote", ""))) > len(
        str(preferred.get("evidence_quote", ""))
    ):
        merged["evidence_quote"] = other.get("evidence_quote", "")
    merged["resolution_note"] = "merged as semantically redundant cross-type candidates"
    return merged


def _contains_durable_marker(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _DURABLE_MARKERS)


def _multi_agent_importance(
    candidate: dict[str, Any],
    *,
    obj_type: str,
    content: str,
    evidence: str,
    related_topics: list[str],
) -> float:
    model_score = clamp_float(candidate.get("importance", 0.5))
    score = calibrate_l1_importance(
        obj_type,
        model_score,
        content=content,
        evidence=evidence,
        related_topics=related_topics,
    )
    confidence = clamp_float(candidate.get("confidence", 0.5))
    support_score = clamp_float(candidate.get("support_score", 0.0), fallback=0.0)
    evidence_lines = candidate.get("evidence_lines", [])
    evidence_line_count = len(evidence_lines) if isinstance(evidence_lines, list) else 0
    token_count = len(tokenize(content))
    durable_marker = _contains_durable_marker(f"{content}\n{' '.join(related_topics)}")

    weighted_cap = (
        0.38
        + 0.34 * model_score
        + 0.16 * confidence
        + 0.12 * support_score
    )
    if durable_marker and obj_type in {"decision", "method_change"}:
        weighted_cap += 0.03
    if obj_type == "todo":
        weighted_cap -= 0.02
    elif obj_type == "result":
        weighted_cap -= 0.04
    score = min(score, weighted_cap)

    if token_count <= 3:
        score = min(score, 0.30)
    if support_score < 0.25:
        score = min(score, 0.72)
    if confidence < 0.65:
        score = min(score, 0.72)
    if evidence_line_count <= 1:
        if obj_type == "result":
            score = min(score, 0.68)
        elif obj_type == "todo":
            score = min(score, 0.78)
        else:
            score = min(score, 0.84)
    if obj_type == "result" and not durable_marker:
        score = min(score, 0.78)
    if obj_type == "todo":
        score = min(score, 0.88)
    elif obj_type == "result" and support_score < 0.70:
        score = min(score, 0.86)

    return round(clamp_float(score), 2)


def _line_overlap(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    return bool(set(left) & set(right))


def _duplicate_index(rows: list[dict[str, Any]], candidate: dict[str, Any]) -> int | None:
    content = str(candidate.get("content", ""))
    obj_type = str(candidate.get("type", ""))
    evidence_lines = candidate.get("evidence_lines", [])
    for index, row in enumerate(rows):
        row_type = str(row.get("type", ""))
        similarity = jaccard(str(row.get("content", "")), content)
        same_or_colliding_type = (
            row_type == obj_type
            or frozenset({row_type, obj_type})
            in {
                frozenset({"decision", "method_change"}),
                frozenset({"decision", "result"}),
                frozenset({"result", "method_change"}),
            }
        )
        if row_type == obj_type and similarity >= 0.62:
            return index
        if (
            same_or_colliding_type
            and _line_overlap(row.get("_evidence_lines", []), evidence_lines)
            and similarity >= 0.28
        ):
            return index
    return None


def _row_rank(row: dict[str, Any]) -> tuple[int, float, int, int]:
    return (
        TYPE_PRIORITY.get(str(row.get("type", "")), 0),
        clamp_float(row.get("importance", 0.0), fallback=0.0),
        len(row.get("_evidence_lines", [])),
        len(tokenize(str(row.get("content", "")))),
    )


def _merge_memory_rows(preferred: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    merged = dict(preferred)
    merged["importance"] = max(
        clamp_float(preferred.get("importance", 0.0), fallback=0.0),
        clamp_float(other.get("importance", 0.0), fallback=0.0),
    )
    merged["related_topics"] = unique_strings(
        list(preferred.get("related_topics", [])) + list(other.get("related_topics", []))
    )
    merged["_source_candidate_ids"] = unique_strings(
        list(preferred.get("_source_candidate_ids", []))
        + list(other.get("_source_candidate_ids", []))
    )
    merged["_evidence_lines"] = sorted(
        set(preferred.get("_evidence_lines", [])) | set(other.get("_evidence_lines", []))
    )
    if len(str(other.get("evidence", ""))) > len(str(preferred.get("evidence", ""))):
        merged["evidence"] = other.get("evidence", "")
    return merged


def resolve_cross_type_conflicts(
    grounded_candidates: list[GroundedCandidate | dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[ConflictDecision]]:
    pending = [_as_candidate_dict(candidate) for candidate in grounded_candidates]
    kept: list[dict[str, Any]] = []
    decisions: list[ConflictDecision] = []
    dropped_ids: set[str] = set()

    collision_pairs = {
        frozenset({"decision", "method_change"}),
        frozenset({"decision", "result"}),
        frozenset({"result", "method_change"}),
    }

    for index, candidate in enumerate(pending):
        candidate_id = str(candidate.get("candidate_id", ""))
        if candidate_id in dropped_ids:
            continue
        merged = dict(candidate)
        for other in pending[index + 1 :]:
            other_id = str(other.get("candidate_id", ""))
            if other_id in dropped_ids:
                continue
            type_pair = frozenset({str(merged.get("type", "")), str(other.get("type", ""))})
            if type_pair not in collision_pairs:
                continue
            similarity = jaccard(merged.get("content", ""), other.get("content", ""))
            if not _same_span(merged, other):
                continue
            if similarity >= 0.78:
                merged = _merge_candidate(merged, other)
                dropped_ids.add(other_id)
                decisions.append(
                    ConflictDecision(
                        decision_id=f"R-{len(decisions) + 1:03d}",
                        action="merge",
                        candidate_ids=[candidate_id, other_id],
                        output_candidate_id=str(merged.get("candidate_id", "")),
                        reason=(
                            "overlapping evidence and high text similarity; "
                            "preferred operational type before verification"
                        ),
                        rewritten_candidate=merged,
                    )
                )
            else:
                decisions.append(
                    ConflictDecision(
                        decision_id=f"R-{len(decisions) + 1:03d}",
                        action="keep",
                        candidate_ids=[str(merged.get("candidate_id", "")), other_id],
                        output_candidate_id=str(merged.get("candidate_id", "")),
                        reason=(
                            "same evidence span is allowed because candidates answer "
                            "different semantic questions"
                        ),
                    )
                )
        kept.append(merged)

    for candidate in kept:
        decisions.append(
            ConflictDecision(
                decision_id=f"R-{len(decisions) + 1:03d}",
                action="keep",
                candidate_ids=[str(candidate.get("candidate_id", ""))],
                output_candidate_id=str(candidate.get("candidate_id", "")),
                reason="candidate survived cross-type conflict review",
            )
        )
    return kept, decisions


def reduce_l1_patch(
    verified_candidates: list[dict[str, Any]],
    *,
    meeting_id: str,
    start_seq: int = 1,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for candidate in verified_candidates:
        obj_type = str(candidate.get("type", "")).strip()
        content = str(candidate.get("content", "")).strip()
        evidence = str(candidate.get("evidence_quote", "")).strip()
        related_topics = unique_strings(candidate.get("related_topics", []))
        importance = _multi_agent_importance(
            candidate,
            obj_type=obj_type,
            content=content,
            evidence=evidence,
            related_topics=related_topics,
        )
        if not content or importance < MIN_IMPORTANCE_THRESHOLD:
            continue
        row = {
            "type": obj_type,
            "content": content,
            "importance": importance,
            "evidence": evidence,
            "related_topics": related_topics,
            "related_obj_ids": [],
            "_evidence_lines": list(candidate.get("evidence_lines", [])),
            "_source_candidate_ids": [str(candidate.get("candidate_id", ""))],
        }
        duplicate_at = _duplicate_index(rows, {**candidate, **row})
        if duplicate_at is None:
            rows.append(row)
            continue
        existing = rows[duplicate_at]
        preferred, other = (
            (row, existing)
            if _row_rank(row) > _row_rank(existing)
            else (existing, row)
        )
        rows[duplicate_at] = _merge_memory_rows(preferred, other)

    memory_objects: list[dict[str, Any]] = []
    seq = start_seq
    for row in rows:
        memory_objects.append(
            {
                "obj_id": f"L1-{meeting_id}-{seq:03d}",
                "type": row["type"],
                "content": row["content"],
                "importance": row["importance"],
                "evidence": row["evidence"],
                "related_topics": row["related_topics"],
                "related_obj_ids": [],
            }
        )
        seq += 1

    patch = {
        "meeting_id": meeting_id,
        "operation": "replace_meeting_l1",
        "memory_objects": memory_objects,
        "source_candidate_ids": [
            str(candidate.get("candidate_id", "")) for candidate in verified_candidates
        ],
    }
    return patch, memory_objects
