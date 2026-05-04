"""Evidence grounding and deterministic verification for multi-agent L1."""

from __future__ import annotations

from typing import Any

from multi_agent_state import (
    GroundedCandidate,
    IdeaUnit,
    L1Candidate,
    L1_MULTI_AGENT_TYPES,
    VerificationResult,
)
from multi_agent_tools import clamp_float, evidence_quote, jaccard, local_alignment_score, tokenize


def ground_candidates(
    candidates: list[L1Candidate],
    *,
    idea_units: list[IdeaUnit],
    transcript_lines: Any,
) -> list[GroundedCandidate]:
    unit_by_id = {unit.unit_id: unit for unit in idea_units}
    grounded: list[GroundedCandidate] = []
    for candidate in candidates:
        source_units = [
            unit_by_id[unit_id]
            for unit_id in candidate.source_unit_ids
            if unit_id in unit_by_id
        ]
        evidence_lines = sorted(
            {
                line_id
                for unit in source_units
                for line_id in range(unit.line_start, unit.line_end + 1)
            }
        )
        unit_text = " ".join(unit.text for unit in source_units)
        quote = evidence_quote(transcript_lines, evidence_lines)
        evidence_text = f"{unit_text}\n{quote}".strip()
        support_score, alignment_signals = local_alignment_score(
            candidate.content,
            evidence_text,
        )
        note = (
            "local evidence-content alignment from source idea unit spans"
            if evidence_lines
            else "missing source idea unit"
        )
        grounded.append(
            GroundedCandidate(
                candidate_id=candidate.candidate_id,
                type=candidate.type,
                source_unit_ids=candidate.source_unit_ids,
                content=candidate.content,
                importance=candidate.importance,
                confidence=candidate.confidence,
                rationale=candidate.rationale,
                related_topics=candidate.related_topics,
                extraction_scope=candidate.extraction_scope,
                segment_ids=candidate.segment_ids,
                evidence_lines=evidence_lines,
                evidence_quote=quote,
                support_score=support_score,
                grounding_note=f"{note}; signals={alignment_signals}",
            )
        )
    return grounded


def verify_l1_candidates(
    candidates: list[dict[str, Any]],
    *,
    max_line: int,
) -> VerificationResult:
    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: list[dict[str, Any]] = []

    for candidate in candidates:
        row = dict(candidate)
        reasons: list[str] = []
        obj_type = str(row.get("type", "")).strip()
        content = str(row.get("content", "")).strip()
        if obj_type not in L1_MULTI_AGENT_TYPES:
            reasons.append("invalid_type")
        if not content:
            reasons.append("empty_content")
        importance = clamp_float(row.get("importance", 0.5))
        row["importance"] = importance
        evidence_lines = row.get("evidence_lines", [])
        if not isinstance(evidence_lines, list) or not evidence_lines:
            reasons.append("missing_evidence_lines")
        else:
            clean_lines: list[int] = []
            for line_id in evidence_lines:
                try:
                    int_line = int(line_id)
                except (TypeError, ValueError):
                    continue
                if 1 <= int_line <= max_line:
                    clean_lines.append(int_line)
            row["evidence_lines"] = sorted(set(clean_lines))
            if not row["evidence_lines"]:
                reasons.append("evidence_out_of_bounds")
        if float(row.get("support_score", 0.0) or 0.0) < 0.18:
            reasons.append("weak_grounding")

        duplicate_of = ""
        for existing in seen:
            if existing.get("type") != obj_type:
                continue
            overlap = set(existing.get("evidence_lines", [])) & set(
                row.get("evidence_lines", [])
            )
            similar = jaccard(existing.get("content", ""), content)
            if overlap and similar >= 0.72:
                duplicate_of = str(existing.get("candidate_id", ""))
                break
        if duplicate_of:
            reasons.append(f"duplicate_of:{duplicate_of}")

        row["verification_reasons"] = reasons
        if reasons:
            rejected.append(row)
        else:
            row["content_tokens"] = sorted(tokenize(content))
            verified.append(row)
            seen.append(row)

    return VerificationResult(verified_candidates=verified, rejected_candidates=rejected)
