"""Prompted agents for the explicit multi-agent L1 extraction pipeline."""

from __future__ import annotations

from typing import Any

from gemini_clients import create_gemini_client
from multi_agent_logger import ResearchLogger
from multi_agent_state import (
    IdeaUnit,
    L1Candidate,
    SegmentProposal,
    TranscriptLine,
    WindowPlan,
)
from multi_agent_tools import (
    clamp_float,
    extract_json_object,
    format_lines,
    slice_lines,
    unique_strings,
)

MAX_L1_CANDIDATES_PER_TYPE = 2
MAX_FALLBACK_CANDIDATES = 3

SEGMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "topic_label": {"type": "string"},
                    "needs_more_context": {"type": "boolean"},
                },
                "required": [
                    "line_start",
                    "line_end",
                    "topic_label",
                    "needs_more_context",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}

IDEA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "idea_units": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "text": {"type": "string"},
                    "completeness": {"type": "string"},
                    "uncertainty_note": {"type": "string"},
                },
                "required": [
                    "line_start",
                    "line_end",
                    "text",
                    "completeness",
                    "uncertainty_note",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["idea_units"],
    "additionalProperties": False,
}

CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "maxItems": MAX_L1_CANDIDATES_PER_TYPE,
            "items": {
                "type": "object",
                "properties": {
                    "source_unit_ids": {"type": "array", "items": {"type": "string"}},
                    "content": {"type": "string"},
                    "importance": {"type": "number"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                    "related_topics": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "source_unit_ids",
                    "content",
                    "importance",
                    "confidence",
                    "rationale",
                    "related_topics",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

FALLBACK_CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "maxItems": MAX_FALLBACK_CANDIDATES,
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "source_unit_ids": {"type": "array", "items": {"type": "string"}},
                    "content": {"type": "string"},
                    "importance": {"type": "number"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                    "related_topics": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "type",
                    "source_unit_ids",
                    "content",
                    "importance",
                    "confidence",
                    "rationale",
                    "related_topics",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

TYPE_DEFINITIONS = {
    "decision": "high-level conclusion, adoption, rejection, focus choice, or resolved direction",
    "todo": "explicit next step, assigned follow-up, pending action, or unresolved work item with execution expectation",
    "method_change": "change in method, process, procedure, strategy, data handling, or evaluation approach",
    "result": "observation, outcome, finding, experiment result, failure mode, comparison, or evidence report",
}


class MultiAgentLLMRunner:
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | list[str],
        logger: ResearchLogger,
    ) -> None:
        self.model_name = model_name
        self.client = create_gemini_client(api_key)
        self.logger = logger

    def call_json(self, stage: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.logger.write_prompt(stage, prompt)
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config={
                "temperature": 0.1,
                "response_mime_type": "application/json",
                "response_json_schema": schema,
            },
        )
        raw_text = response.text or ""
        self.logger.write_response(stage, raw_text)
        return extract_json_object(raw_text)


def plan_context_windows(
    lines: list[TranscriptLine],
    *,
    window_size: int,
    lookback_lines: int,
    lookahead_lines: int,
) -> list[WindowPlan]:
    plans: list[WindowPlan] = []
    if not lines:
        return plans
    max_line = lines[-1].line_id
    start = lines[0].line_id
    while start <= max_line:
        end = min(max_line, start + max(1, window_size) - 1)
        plans.append(
            WindowPlan(
                start_line=start,
                end_line=end,
                lookback_lines=max(0, lookback_lines),
                lookahead_lines=max(0, lookahead_lines),
                reason="deterministic forward window with bounded context overlap",
            )
        )
        start = end + 1
    return plans


def segmentation_agent(
    runner: MultiAgentLLMRunner,
    *,
    meeting_id: str,
    plan: WindowPlan,
    transcript_lines: list[TranscriptLine],
) -> list[SegmentProposal]:
    start = max(1, plan.start_line - plan.lookback_lines)
    end = plan.end_line + plan.lookahead_lines
    lines = slice_lines(transcript_lines, start, end)
    prompt = f"""
You are segmentation_agent for a long-term memory extraction pipeline.
Return JSON only. Split the transcript window into topic-coherent segments.
Use original line numbers.

Create durable discussion segments, not sentence-level or checklist-like slices.
Prefer 10-24 primary-window lines per segment and no more than 6 segments for an
80-line primary window unless there is a major topic shift.
Do not split every small subpoint into a segment; downstream idea units will handle
the smaller claims inside each durable segment.

Meeting: {meeting_id}
Primary window: {plan.start_line}-{plan.end_line}

Transcript lines:
{format_lines(lines)}
""".strip()
    data = runner.call_json(
        f"segmentation_{plan.start_line}_{plan.end_line}",
        prompt,
        SEGMENT_SCHEMA,
    )
    segments: list[SegmentProposal] = []
    for index, row in enumerate(data.get("segments", []), start=1):
        line_start = max(plan.start_line, int(row.get("line_start", plan.start_line)))
        line_end = min(plan.end_line, int(row.get("line_end", line_start)))
        if line_end < line_start:
            continue
        segments.append(
            SegmentProposal(
                segment_id=f"S-{plan.start_line:04d}-{index:02d}",
                line_start=line_start,
                line_end=line_end,
                topic_label=str(row.get("topic_label", "")).strip() or "untitled",
                needs_more_context=bool(row.get("needs_more_context", False)),
            )
        )
    return segments


def idea_unit_agent(
    runner: MultiAgentLLMRunner,
    *,
    segment: SegmentProposal,
    transcript_lines: list[TranscriptLine],
) -> list[IdeaUnit]:
    lines = slice_lines(transcript_lines, segment.line_start, segment.line_end)
    prompt = f"""
You are idea_unit_agent. Convert this segment into compact idea units.
Each unit should express one checkable idea that downstream L1 agents can share.
Do not classify memory types here. Return JSON only.

Return at most 6 idea units. Do not split every sentence into a separate unit.
Prefer durable, self-contained units that combine related details across several
lines. Ignore filler, acknowledgements, and local wording clarifications unless
they change the project method, decision, result, or todo.

Segment: {segment.segment_id}
Topic: {segment.topic_label}

Transcript lines:
{format_lines(lines)}
""".strip()
    data = runner.call_json(f"idea_units_{segment.segment_id}", prompt, IDEA_SCHEMA)
    units: list[IdeaUnit] = []
    for index, row in enumerate(data.get("idea_units", []), start=1):
        line_start = max(segment.line_start, int(row.get("line_start", segment.line_start)))
        line_end = min(segment.line_end, int(row.get("line_end", line_start)))
        text = str(row.get("text", "")).strip()
        if not text or line_end < line_start:
            continue
        units.append(
            IdeaUnit(
                unit_id=f"U-{segment.segment_id}-{index:02d}",
                segment_id=segment.segment_id,
                line_start=line_start,
                line_end=line_end,
                text=text,
                completeness=str(row.get("completeness", "")).strip() or "unknown",
                uncertainty_note=str(row.get("uncertainty_note", "")).strip(),
            )
        )
    return units


def l1_type_agent(
    runner: MultiAgentLLMRunner,
    *,
    obj_type: str,
    idea_units: list[IdeaUnit],
    existing_topics: list[str],
    extraction_scope: str = "",
    segment_ids: list[str] | None = None,
) -> list[L1Candidate]:
    segment_ids = segment_ids or []
    allowed_unit_ids = {unit.unit_id for unit in idea_units}
    units_text = "\n".join(
        f"{unit.unit_id} ({unit.line_start}-{unit.line_end}): {unit.text}"
        for unit in idea_units
    )
    prompt = f"""
You are l1_{obj_type}_agent in a multi-agent long-term memory pipeline.
Your operational type definition: {TYPE_DEFINITIONS[obj_type]}.

Read only the bounded idea units below and propose only {obj_type} candidates.
Do not infer from outside this extraction scope.
The same idea unit may support other memory types; do not suppress valid {obj_type} objects for that reason.
Return at most {MAX_L1_CANDIDATES_PER_TYPE} candidates. Return an empty list when the
batch has no durable {obj_type}.

Only output durable long-term memory:
- keep project-level decisions, method changes, concrete follow-ups, or stable findings
- do not restate each idea unit as a candidate
- do not output local clarifications, filler, examples, or one-line observations
- use importance >= 0.90 only for project-level or future-steering items
- use 0.50-0.70 for useful but local meeting-level context
Return JSON only. Text fields should prefer Traditional Chinese when the transcript is Chinese.

Extraction scope: {extraction_scope or "(single bounded batch)"}
Segment IDs: {", ".join(segment_ids) if segment_ids else "(not provided)"}
Known related topics: {", ".join(existing_topics[:80]) if existing_topics else "(none)"}

Bounded idea units:
{units_text}
""".strip()
    safe_scope = (extraction_scope or "batch").replace("/", "_").replace(" ", "_")
    data = runner.call_json(f"l1_{obj_type}_agent_{safe_scope}", prompt, CANDIDATE_SCHEMA)
    candidates: list[L1Candidate] = []
    for index, row in enumerate(data.get("candidates", []), start=1):
        content = str(row.get("content", "")).strip()
        if not content:
            continue
        source_unit_ids = [
            unit_id
            for unit_id in unique_strings(row.get("source_unit_ids", []))
            if unit_id in allowed_unit_ids
        ]
        if not source_unit_ids:
            continue
        candidates.append(
            L1Candidate(
                candidate_id=f"C-{safe_scope}-{obj_type}-{index:03d}",
                type=obj_type,
                source_unit_ids=source_unit_ids,
                content=content,
                importance=clamp_float(row.get("importance", 0.5)),
                confidence=clamp_float(row.get("confidence", 0.5)),
                rationale=str(row.get("rationale", "")).strip(),
                related_topics=unique_strings(row.get("related_topics", [])),
                extraction_scope=extraction_scope,
                segment_ids=segment_ids,
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: (candidate.importance, candidate.confidence),
        reverse=True,
    )[:MAX_L1_CANDIDATES_PER_TYPE]


def l1_fallback_agent(
    runner: MultiAgentLLMRunner,
    *,
    idea_units: list[IdeaUnit],
    existing_topics: list[str],
    extraction_scope: str = "",
    segment_ids: list[str] | None = None,
) -> list[L1Candidate]:
    """Conservative fallback when typed agents produce nothing for a non-empty batch."""
    segment_ids = segment_ids or []
    allowed_unit_ids = {unit.unit_id for unit in idea_units}
    units_text = "\n".join(
        f"{unit.unit_id} ({unit.line_start}-{unit.line_end}): {unit.text}"
        for unit in idea_units
    )
    allowed_types = ", ".join(sorted(TYPE_DEFINITIONS))
    prompt = f"""
You are general_l1_fallback_agent in a multi-agent long-term memory pipeline.
This fallback runs only because the typed L1 agents produced no candidates for this bounded batch.

Read only the bounded idea units below. Propose a small number of durable L1 candidates only if
the batch clearly contains one of these types: {allowed_types}.
Return an empty candidates list if the batch is purely filler, logistics, acknowledgements, or unclear.
Do not invent information outside the supplied unit IDs.
Return at most {MAX_FALLBACK_CANDIDATES} candidates.
Return JSON only. Text fields should prefer Traditional Chinese when the transcript is Chinese.

Extraction scope: {extraction_scope or "(single bounded batch)"}
Segment IDs: {", ".join(segment_ids) if segment_ids else "(not provided)"}
Known related topics: {", ".join(existing_topics[:80]) if existing_topics else "(none)"}

Bounded idea units:
{units_text}
""".strip()
    safe_scope = (extraction_scope or "batch").replace("/", "_").replace(" ", "_")
    data = runner.call_json(
        f"l1_fallback_agent_{safe_scope}",
        prompt,
        FALLBACK_CANDIDATE_SCHEMA,
    )
    candidates: list[L1Candidate] = []
    for index, row in enumerate(data.get("candidates", []), start=1):
        obj_type = str(row.get("type", "")).strip().lower()
        if obj_type not in TYPE_DEFINITIONS:
            continue
        content = str(row.get("content", "")).strip()
        if not content:
            continue
        source_unit_ids = [
            unit_id
            for unit_id in unique_strings(row.get("source_unit_ids", []))
            if unit_id in allowed_unit_ids
        ]
        if not source_unit_ids:
            continue
        candidates.append(
            L1Candidate(
                candidate_id=f"C-{safe_scope}-fallback-{obj_type}-{index:03d}",
                type=obj_type,
                source_unit_ids=source_unit_ids,
                content=content,
                importance=clamp_float(row.get("importance", 0.5)),
                confidence=clamp_float(row.get("confidence", 0.5)),
                rationale=str(row.get("rationale", "")).strip(),
                related_topics=unique_strings(row.get("related_topics", [])),
                extraction_scope=extraction_scope,
                segment_ids=segment_ids,
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: (candidate.importance, candidate.confidence),
        reverse=True,
    )[:MAX_FALLBACK_CANDIDATES]
