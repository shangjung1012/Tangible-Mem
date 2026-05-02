"""Conflict resolution and final L1 patch reduction for multi-agent output."""

from __future__ import annotations

from typing import Any

from importance import MIN_IMPORTANCE_THRESHOLD, calibrate_l1_importance
from multi_agent_state import ConflictDecision, GroundedCandidate
from multi_agent_tools import clamp_float, jaccard, unique_strings

TYPE_PRIORITY = {
    "method_change": 3,
    "decision": 2,
    "result": 1,
    "todo": 1,
}


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
    memory_objects: list[dict[str, Any]] = []
    seq = start_seq
    for candidate in verified_candidates:
        obj_type = str(candidate.get("type", "")).strip()
        content = str(candidate.get("content", "")).strip()
        evidence = str(candidate.get("evidence_quote", "")).strip()
        related_topics = unique_strings(candidate.get("related_topics", []))
        importance = calibrate_l1_importance(
            obj_type,
            candidate.get("importance", 0.5),
            content=content,
            evidence=evidence,
            related_topics=related_topics,
        )
        if not content or importance < MIN_IMPORTANCE_THRESHOLD:
            continue
        memory_objects.append(
            {
                "obj_id": f"L1-{meeting_id}-{seq:03d}",
                "type": obj_type,
                "content": content,
                "importance": importance,
                "evidence": evidence,
                "related_topics": related_topics,
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
