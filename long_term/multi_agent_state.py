"""Typed state objects for the explicit multi-agent L1 pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

L1_MULTI_AGENT_TYPES = {"decision", "todo", "method_change", "result"}
ConflictAction = Literal["keep", "merge", "rewrite", "drop"]


@dataclass(frozen=True)
class TranscriptLine:
    line_id: int
    text: str


@dataclass(frozen=True)
class WindowPlan:
    start_line: int
    end_line: int
    lookback_lines: int
    lookahead_lines: int
    reason: str


@dataclass(frozen=True)
class SegmentProposal:
    segment_id: str
    line_start: int
    line_end: int
    topic_label: str
    needs_more_context: bool = False


@dataclass(frozen=True)
class IdeaUnit:
    unit_id: str
    segment_id: str
    line_start: int
    line_end: int
    text: str
    completeness: str
    uncertainty_note: str = ""


@dataclass(frozen=True)
class L1Candidate:
    candidate_id: str
    type: str
    source_unit_ids: list[str]
    content: str
    importance: float
    confidence: float
    rationale: str
    related_topics: list[str] = field(default_factory=list)
    extraction_scope: str = ""
    segment_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GroundedCandidate:
    candidate_id: str
    type: str
    source_unit_ids: list[str]
    content: str
    importance: float
    confidence: float
    rationale: str
    related_topics: list[str]
    extraction_scope: str
    segment_ids: list[str]
    evidence_lines: list[int]
    evidence_quote: str
    support_score: float
    grounding_note: str


@dataclass(frozen=True)
class ConflictDecision:
    decision_id: str
    action: ConflictAction
    candidate_ids: list[str]
    output_candidate_id: str
    reason: str
    rewritten_candidate: dict[str, Any] | None = None


@dataclass(frozen=True)
class VerificationResult:
    verified_candidates: list[dict[str, Any]]
    rejected_candidates: list[dict[str, Any]]


def to_plain(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    return value


def parse_transcript_lines(transcript: str) -> list[TranscriptLine]:
    lines: list[TranscriptLine] = []
    for index, raw_line in enumerate(str(transcript or "").splitlines(), start=1):
        text = raw_line.strip()
        if text:
            lines.append(TranscriptLine(line_id=index, text=text))
    return lines
