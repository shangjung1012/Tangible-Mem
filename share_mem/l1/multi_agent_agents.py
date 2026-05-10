"""Prompted agents for the explicit multi-agent L1 extraction pipeline."""

from __future__ import annotations

import time
import os
import signal
import threading
import json
from collections import Counter
from contextlib import contextmanager
from typing import Any

from .gemini_clients import DEFAULT_HTTP_TIMEOUT_S, create_gemini_client
from .multi_agent_logger import ResearchLogger
from .multi_agent_state import (
    IdeaUnit,
    L1Candidate,
    SegmentProposal,
    TranscriptLine,
    WindowPlan,
)
from .multi_agent_tools import (
    clamp_float,
    extract_json_object,
    format_lines,
    slice_lines,
    unique_strings,
)
from .multi_agent_validators import normalize_idea_completeness
from .prior_context import format_prior_context_for_prompt
from .taxonomy import (
    LEGACY_COMPATIBILITY_DESCRIPTIONS,
    candidate_schema_for_taxonomy,
    fallback_candidate_schema_for_taxonomy,
    normalize_legacy_type,
    normalize_taxonomy,
    type_definitions_for_taxonomy,
    type_set_for_taxonomy,
)

MAX_SEGMENTS_PER_WINDOW = 10
MAX_IDEA_UNITS_PER_AGENT = 12
MAX_L1_CANDIDATES_PER_TYPE = 6
MAX_FALLBACK_CANDIDATES = 3

L1_LANGUAGE_POLICY = """
Language contract:
- content MUST be written in Traditional Chinese for canonical share_mem L1 output.
  This still applies when the bounded idea units are English intermediate summaries
  of a Chinese transcript. Translate the memory summary back into Traditional
  Chinese, while keeping technical anchors in English when they are the normal
  project terms, such as RAG, L1/L2/L3, API, topic lifecycle, manager-agent,
  full context, and short-term/long-term memory.
- content should be a concise human-facing memory summary, not a literal transcript
  quote and not an English-only paraphrase of Chinese discussion.
- related_topics MUST be English machine-facing topic keys. Use concise normalized
  labels, preferably lowercase words separated by spaces. Do not translate
  related_topics into Chinese.
- evidence should stay faithful to the source wording and may preserve the original
  transcript language or mixed-language technical phrasing.
""".strip()

SEGMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "maxItems": MAX_SEGMENTS_PER_WINDOW,
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
            "maxItems": MAX_IDEA_UNITS_PER_AGENT,
            "items": {
                "type": "object",
                "properties": {
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "text": {"type": "string"},
                    "completeness": {
                        "type": "string",
                        "enum": ["complete", "partial", "incomplete", "uncertain"],
                    },
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

IDEA_REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "idea_units": {
            "type": "array",
            "maxItems": MAX_IDEA_UNITS_PER_AGENT,
            "items": {
                "type": "object",
                "properties": {
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "text": {"type": "string"},
                    "completeness": {
                        "type": "string",
                        "enum": ["complete", "partial", "incomplete", "uncertain"],
                    },
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
        },
        "non_memory_context_ranges": {
            "type": "array",
            "maxItems": MAX_IDEA_UNITS_PER_AGENT,
            "items": {
                "type": "object",
                "properties": {
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["line_start", "line_end", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["idea_units", "non_memory_context_ranges"],
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
                    "content": {
                        "type": "string",
                        "description": (
                            "Human-facing L1 memory summary. Use Traditional Chinese "
                            "for canonical share_mem L1 output, even when idea units "
                            "are English intermediate summaries. Preserve technical "
                            "English anchors."
                        ),
                    },
                    "importance": {"type": "number"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                    "related_topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Machine-facing topic keys in English normalized labels; "
                            "do not translate topic keys into Chinese."
                        ),
                    },
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
                    "content": {
                        "type": "string",
                        "description": (
                            "Human-facing L1 memory summary. Use Traditional Chinese "
                            "for canonical share_mem L1 output, even when idea units "
                            "are English intermediate summaries. Preserve technical "
                            "English anchors."
                        ),
                    },
                    "importance": {"type": "number"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                    "related_topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Machine-facing topic keys in English normalized labels; "
                            "do not translate topic keys into Chinese."
                        ),
                    },
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
    "argument": "reasoning, tradeoff, constraint, or justification that explains why a decision or method direction is preferred",
    "open_question": "unresolved research question, blocker, uncertainty, or decision point that still needs clarification",
}


class LLMCallTimeoutError(TimeoutError):
    """Raised when a multi-agent Gemini call exceeds the local hard timeout."""


def _resolve_call_timeout_s() -> int:
    raw_value = (
        os.getenv("GEMINI_MULTI_AGENT_CALL_TIMEOUT_S", "").strip()
        or os.getenv("GEMINI_HTTP_TIMEOUT_S", "").strip()
    )
    if not raw_value:
        return DEFAULT_HTTP_TIMEOUT_S
    try:
        timeout_s = int(raw_value)
    except ValueError:
        return DEFAULT_HTTP_TIMEOUT_S
    return max(1, timeout_s)


def _resolve_max_attempts() -> int:
    raw_value = os.getenv("GEMINI_MULTI_AGENT_MAX_ATTEMPTS", "").strip()
    if not raw_value:
        return 2
    try:
        attempts = int(raw_value)
    except ValueError:
        return 2
    return max(1, attempts)


def _is_retryable_llm_error(exc: Exception) -> bool:
    if isinstance(exc, LLMCallTimeoutError):
        return True
    exc_type = type(exc)
    if exc_type.__module__.split(".", 1)[0] == "httpx" and exc_type.__name__ in {
        "ConnectError",
        "ConnectTimeout",
        "PoolTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "TransportError",
        "WriteError",
        "WriteTimeout",
    }:
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code in {429, 499, 500, 502, 503, 504}:
        return True
    message = str(exc).upper()
    return any(
        token in message
        for token in (
            "429",
            "499",
            "500",
            "502",
            "503",
            "504",
            "RESOURCE_EXHAUSTED",
            "UNAVAILABLE",
            "TIMEOUT",
            "TIMED OUT",
            "READTIMEOUT",
        )
    )


@contextmanager
def _hard_timeout(stage: str, timeout_s: int):
    if (
        timeout_s <= 0
        or threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "setitimer")
    ):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def _raise_timeout(_signum: int, _frame: Any) -> None:
        raise LLMCallTimeoutError(
            f"Gemini call timed out after {timeout_s}s at stage {stage}."
        )

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


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
        self.call_records: list[dict[str, Any]] = []
        self.call_counts: Counter[str] = Counter()

    def call_json(self, stage: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.logger.write_prompt(stage, prompt)
        timeout_s = _resolve_call_timeout_s()
        max_attempts = _resolve_max_attempts()
        last_error: Exception | None = None
        config = {
            "temperature": 0.1,
            "response_mime_type": "application/json",
            "response_json_schema": schema,
        }
        for attempt in range(1, max_attempts + 1):
            started_at = time.monotonic()
            raw_text = ""
            parsed_json: dict[str, Any] | None = None
            try:
                with _hard_timeout(stage, timeout_s):
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=config,
                    )
                raw_text = response.text or ""
                self.logger.write_response(stage, raw_text)
                parsed_json = extract_json_object(raw_text)
            except Exception as exc:
                latency_sec = round(time.monotonic() - started_at, 3)
                error_payload = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                self.logger.write_api_call(
                    stage=stage,
                    attempt=attempt,
                    model=self.model_name,
                    config=config,
                    schema=schema,
                    prompt=prompt,
                    raw_response=raw_text,
                    parsed_json=parsed_json,
                    latency_sec=latency_sec,
                    success=False,
                    error=error_payload,
                )
                record = {
                    "stage": stage,
                    "success": False,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "latency_sec": latency_sec,
                    "timeout_s": timeout_s,
                    "prompt_chars": len(prompt),
                    "response_chars": len(raw_text),
                    "error_type": type(exc).__name__,
                }
                self.call_records.append(record)
                self.call_counts[stage] += 1
                self.logger.append_event("llm_call:error", record)
                last_error = exc
                if attempt < max_attempts and _is_retryable_llm_error(exc):
                    wait_s = min(10.0, 2.0 * attempt)
                    self.logger.append_event(
                        "llm_call:retry",
                        {
                            "stage": stage,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "wait_s": wait_s,
                            "previous_error_type": type(exc).__name__,
                        },
                    )
                    time.sleep(wait_s)
                    continue
                raise

            latency_sec = round(time.monotonic() - started_at, 3)
            self.logger.write_api_call(
                stage=stage,
                attempt=attempt,
                model=self.model_name,
                config=config,
                schema=schema,
                prompt=prompt,
                raw_response=raw_text,
                parsed_json=parsed_json,
                latency_sec=latency_sec,
                success=True,
                error=None,
            )
            record = {
                "stage": stage,
                "success": True,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "latency_sec": latency_sec,
                "timeout_s": timeout_s,
                "prompt_chars": len(prompt),
                "response_chars": len(raw_text),
            }
            self.call_records.append(record)
            self.call_counts[stage] += 1
            self.logger.append_event("llm_call:done", record)
            return parsed_json
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Gemini call failed without an error at stage {stage}.")


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
Normally return 3-6 segments for an 80-line primary window.
You may return up to {MAX_SEGMENTS_PER_WINDOW} segments only when there are clear
major topic shifts. Prefer 10-24 primary-window lines per segment.
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

Normally return 3-8 idea units. You may return up to {MAX_IDEA_UNITS_PER_AGENT}
only when the segment contains many distinct durable claims.
Do not split every sentence into a separate unit.
Prefer durable, self-contained units that combine related details across several
lines. Preserve questions, objections, counterexamples, method exploration,
evaluation criteria, comparison rationale, and unresolved design discussions
when they affect future project decisions or memory behavior.
Ignore only true filler, acknowledgements, local wording clarifications, and
purely social turns that do not affect the project state.

Use completeness exactly as one of: complete, partial, incomplete, uncertain.
Completeness rubric:
- complete: the unit is self-contained enough for downstream L1 extraction.
- partial: the unit is useful, but nearby context is needed for pronouns, target, or rationale.
- incomplete: the discussion is cut off, still unfolding, or missing a conclusion.
- uncertain: the text is ambiguous, exploratory, hypothetical, or unclear whether it was adopted.
Do not use fallback or compacted; those are reserved for deterministic validators.

Segment: {segment.segment_id}
Topic: {segment.topic_label}

Transcript lines:
{format_lines(lines)}
""".strip()
    data = runner.call_json(f"idea_units_{segment.segment_id}", prompt, IDEA_SCHEMA)
    return _idea_units_from_rows(
        data.get("idea_units", []),
        segment=segment,
        unit_id_prefix=f"U-{segment.segment_id}",
    )


def _idea_units_from_rows(
    rows: list[dict[str, Any]],
    *,
    segment: SegmentProposal,
    unit_id_prefix: str,
) -> list[IdeaUnit]:
    units: list[IdeaUnit] = []
    for index, row in enumerate(rows, start=1):
        line_start = max(segment.line_start, int(row.get("line_start", segment.line_start)))
        line_end = min(segment.line_end, int(row.get("line_end", line_start)))
        text = str(row.get("text", "")).strip()
        if not text or line_end < line_start:
            continue
        units.append(
            IdeaUnit(
                unit_id=f"{unit_id_prefix}-{index:02d}",
                segment_id=segment.segment_id,
                line_start=line_start,
                line_end=line_end,
                text=text,
                completeness=normalize_idea_completeness(
                    str(row.get("completeness", "")).strip()
                ),
                uncertainty_note=str(row.get("uncertainty_note", "")).strip(),
            )
        )
    return units


def idea_unit_repair_agent(
    runner: MultiAgentLLMRunner,
    *,
    segment: SegmentProposal,
    transcript_lines: list[TranscriptLine],
    current_units: list[IdeaUnit],
    validation_report: dict[str, Any],
) -> tuple[list[IdeaUnit], list[dict[str, Any]]]:
    """Ask the model to semantically repair idea-unit coverage before fallback."""
    lines = slice_lines(transcript_lines, segment.line_start, segment.line_end)
    current_units_json = [
        {
            "unit_id": unit.unit_id,
            "line_start": unit.line_start,
            "line_end": unit.line_end,
            "text": unit.text,
            "completeness": unit.completeness,
            "uncertainty_note": unit.uncertainty_note,
        }
        for unit in current_units
    ]
    prompt = f"""
You are idea_unit_repair_agent. Repair idea-unit coverage for one segment.
Return a full revised set of semantic idea units for the segment, not a patch.
Return JSON only.

The validator found issues in the first idea-unit pass. Your job is to avoid
deterministic fallback by creating durable semantic units where there is useful
project content, or marking true filler as non_memory_context_ranges.

Preserve questions, objections, counterexamples, method exploration, evaluation
criteria, comparison rationale, and unresolved design discussions when they
affect future project decisions or memory behavior. Do not dismiss these as
filler.

Use completeness exactly as one of: complete, partial, incomplete, uncertain.
Completeness rubric:
- complete: the unit is self-contained enough for downstream L1 extraction.
- partial: the unit is useful, but nearby context is needed for pronouns, target, or rationale.
- incomplete: the discussion is cut off, still unfolding, or missing a conclusion.
- uncertain: the text is ambiguous, exploratory, hypothetical, or unclear whether it was adopted.
Do not use fallback or compacted.

For non_memory_context_ranges, include only lines that are purely filler,
acknowledgements, local wording clarification, or social closing with no memory
value.

Segment: {segment.segment_id}
Topic: {segment.topic_label}

Transcript lines:
{format_lines(lines)}

Current idea units:
{json.dumps(current_units_json, ensure_ascii=False, indent=2)}

Validator report:
{json.dumps(validation_report, ensure_ascii=False, indent=2)}
""".strip()
    data = runner.call_json(
        f"idea_unit_repair_agent_{segment.segment_id}",
        prompt,
        IDEA_REPAIR_SCHEMA,
    )
    repaired_units = _idea_units_from_rows(
        data.get("idea_units", []),
        segment=segment,
        unit_id_prefix=f"U-{segment.segment_id}-SR",
    )
    non_memory_ranges: list[dict[str, Any]] = []
    for row in data.get("non_memory_context_ranges", []):
        try:
            line_start = max(segment.line_start, int(row.get("line_start", segment.line_start)))
            line_end = min(segment.line_end, int(row.get("line_end", line_start)))
        except (TypeError, ValueError):
            continue
        reason = str(row.get("reason", "")).strip()
        if line_end < line_start:
            continue
        non_memory_ranges.append(
            {
                "start_line": line_start,
                "end_line": line_end,
                "reason": reason or "model marked as non-memory context",
            }
        )
    return repaired_units, non_memory_ranges


def format_previous_context_for_prompt(previous_context: dict[str, Any] | None) -> str:
    """Render compact previous extraction-packet hints for typed agents."""
    if not previous_context or not previous_context.get("enabled"):
        return ""
    items = previous_context.get("items", [])
    if not items:
        return (
            "Previous extraction-packet context: enabled, but no prior unverified candidate "
            "summaries are available yet."
        )
    lines = [
        "Previous extraction-packet context (unverified, read-only; not evidence):",
        "- Use only to resolve pronouns, understand continuation, and avoid duplicates.",
        "- These summaries have not passed grounding or final reduction yet.",
        "- Do not increase candidate count just because previous context mentions a topic.",
        "- Do not cite previous context or use it as support.",
        "- Every source_unit_id must still come from the current bounded idea units.",
    ]
    for item in items:
        obj_type = str(item.get("type", "unknown") or "unknown")
        source_batch_id = str(item.get("source_batch_id", "previous") or "previous")
        content = str(item.get("content", "") or "").strip()
        if content:
            lines.append(f"- [{source_batch_id} {obj_type}] {content}")
    return "\n".join(lines)


def format_batch_metadata_for_prompt(batch_metadata: dict[str, Any] | None) -> str:
    """Render split-family metadata for bounded extraction prompts."""
    if not batch_metadata or not batch_metadata.get("parent_batch_id"):
        return ""
    parent_batch_id = str(batch_metadata.get("parent_batch_id", "") or "")
    split_index = str(batch_metadata.get("split_index", "") or "")
    split_count = str(batch_metadata.get("split_count", "") or "")
    split_reason = str(batch_metadata.get("split_reason", "") or "")
    overlap_unit_ids = unique_strings(batch_metadata.get("overlap_unit_ids", []))
    parent_segment_ids = unique_strings(
        batch_metadata.get("semantic_parent_segment_ids", [])
    )
    lines = [
        "Split-family scope metadata (not evidence):",
        f"- parent_extraction_packet_id={parent_batch_id}; split_index={split_index}/{split_count}",
        f"- split_reason={split_reason or 'bounded extraction chunk'}",
        "- If this extraction packet is part of a split family, avoid creating a partial candidate solely because the chunk boundary cuts a larger idea.",
        "- Overlap idea units may be cited as normal bounded evidence when they appear below.",
        "- Do not cite sibling metadata or infer from unseen sibling extraction packets.",
    ]
    if overlap_unit_ids:
        lines.append(f"- overlap_unit_ids={', '.join(overlap_unit_ids)}")
    if parent_segment_ids:
        lines.append(f"- semantic_parent_segment_ids={', '.join(parent_segment_ids)}")
    return "\n".join(lines)


def l1_type_agent(
    runner: MultiAgentLLMRunner,
    *,
    obj_type: str,
    idea_units: list[IdeaUnit],
    existing_topics: list[str],
    prior_context_pack: dict[str, Any] | None = None,
    previous_context: dict[str, Any] | None = None,
    batch_metadata: dict[str, Any] | None = None,
    extraction_scope: str = "",
    segment_ids: list[str] | None = None,
    taxonomy: str = "v1",
    include_legacy_type: bool = False,
) -> list[L1Candidate]:
    segment_ids = segment_ids or []
    taxonomy = normalize_taxonomy(taxonomy)
    type_definitions = type_definitions_for_taxonomy(taxonomy)
    allowed_unit_ids = {unit.unit_id for unit in idea_units}
    units_text = "\n".join(
        f"{unit.unit_id} ({unit.line_start}-{unit.line_end}): {unit.text}"
        for unit in idea_units
    )
    prior_context_text = format_prior_context_for_prompt(prior_context_pack)
    previous_context_text = format_previous_context_for_prompt(previous_context)
    batch_metadata_text = format_batch_metadata_for_prompt(batch_metadata)
    prompt = f"""
You are l1_{obj_type}_agent in a multi-agent long-term memory pipeline.
Your operational type definition: {type_definitions[obj_type]}.

Read only the bounded idea units below and propose only {obj_type} candidates.
Do not infer from outside this extraction scope.
Prior context may help disambiguate references, but it is never evidence.
Every candidate must be supported by the bounded idea units below.
The same idea unit may support other memory types; do not suppress valid {obj_type} objects for that reason.
{"Every candidate must set type exactly to " + obj_type + "." if taxonomy != "v1" else ""}
{"Every candidate must include legacy_type using one of: " + ", ".join(sorted(LEGACY_COMPATIBILITY_DESCRIPTIONS)) + ". Use the closest old taxonomy role for comparison only." if include_legacy_type else ""}
Normally return 0-4 candidates. You may return up to {MAX_L1_CANDIDATES_PER_TYPE} only
when there are clearly distinct durable {obj_type} memories. Return an empty list when
this extraction packet has no durable {obj_type}. Do not pad the response to fill the limit.

Only output durable long-term memory:
- keep project-level decisions, method changes, concrete follow-ups, stable findings,
  unresolved research questions, or decision-supporting arguments
- do not restate each idea unit as a candidate
- do not output local clarifications, filler, examples, or one-line observations
- preserve requirement/scope clarifications when they resolve or constrain system behavior
  (for example whether a demo must be real-time); use finding/decision for resolved
  clarifications and open_issue only when the requirement still remains unresolved
- preserve unresolved implementation questions about memory-object filtering,
  discard as L1, or how the importance score is used; use open_issue when the
  supplied scope does not resolve the question
- preserve evaluation design details when they define benchmark baselines,
  comparison conditions, or metrics, including full-context, RAG, prior-paper,
  ablation, or precision/recall baselines
- preserve model capability judgments that affect pipeline design or evaluation,
  such as whether Gemini can identify or judge good idea units
- for argument, preserve only reasoning that explains a meaningful tradeoff or choice
- for open_question, preserve only questions that remain unresolved after the supplied scope
- for proposal, preserve only suggested options or hypotheses that are not yet adopted
- for action_item, preserve only executable follow-ups with a clear expectation of work
- for open_issue, preserve only unresolved issues that matter after this scope
- use importance >= 0.90 only for project-level or future-steering items
- use 0.50-0.70 for useful but local meeting-level context
Return JSON only.

{L1_LANGUAGE_POLICY}

Extraction packet: {extraction_scope or "(single bounded extraction packet)"}
Segment IDs: {", ".join(segment_ids) if segment_ids else "(not provided)"}
Known related topics: {", ".join(existing_topics[:80]) if existing_topics else "(none)"}

{prior_context_text}

{previous_context_text}

{batch_metadata_text}

Bounded idea units:
{units_text}
""".strip()
    safe_scope = (extraction_scope or "batch").replace("/", "_").replace(" ", "_")
    schema = (
        candidate_schema_for_taxonomy(
            taxonomy,
            include_legacy_type=include_legacy_type,
            max_items=MAX_L1_CANDIDATES_PER_TYPE,
        )
        if taxonomy != "v1" or include_legacy_type
        else CANDIDATE_SCHEMA
    )
    data = runner.call_json(f"l1_{obj_type}_agent_{safe_scope}", prompt, schema)
    candidates: list[L1Candidate] = []
    for index, row in enumerate(data.get("candidates", []), start=1):
        row_type = str(row.get("type") or obj_type).strip().lower()
        if row_type != obj_type:
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
                candidate_id=f"C-{safe_scope}-{obj_type}-{index:03d}",
                type=row_type,
                source_unit_ids=source_unit_ids,
                content=content,
                importance=clamp_float(row.get("importance", 0.5)),
                confidence=clamp_float(row.get("confidence", 0.5)),
                rationale=str(row.get("rationale", "")).strip(),
                related_topics=unique_strings(row.get("related_topics", [])),
                extraction_scope=extraction_scope,
                segment_ids=segment_ids,
                legacy_type=(
                    normalize_legacy_type(row.get("legacy_type"), obj_type=row_type)
                    if include_legacy_type
                    else ""
                ),
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
    prior_context_pack: dict[str, Any] | None = None,
    previous_context: dict[str, Any] | None = None,
    batch_metadata: dict[str, Any] | None = None,
    extraction_scope: str = "",
    segment_ids: list[str] | None = None,
    taxonomy: str = "v1",
    include_legacy_type: bool = False,
) -> list[L1Candidate]:
    """Conservative fallback when typed agents produce nothing for a non-empty extraction packet."""
    segment_ids = segment_ids or []
    taxonomy = normalize_taxonomy(taxonomy)
    type_definitions = type_definitions_for_taxonomy(taxonomy)
    allowed_type_set = type_set_for_taxonomy(taxonomy)
    allowed_unit_ids = {unit.unit_id for unit in idea_units}
    units_text = "\n".join(
        f"{unit.unit_id} ({unit.line_start}-{unit.line_end}): {unit.text}"
        for unit in idea_units
    )
    allowed_types = ", ".join(sorted(type_definitions))
    prior_context_text = format_prior_context_for_prompt(prior_context_pack)
    previous_context_text = format_previous_context_for_prompt(previous_context)
    batch_metadata_text = format_batch_metadata_for_prompt(batch_metadata)
    prompt = f"""
You are general_l1_fallback_agent in a multi-agent long-term memory pipeline.
This fallback runs only because the typed L1 agents produced no candidates for this bounded extraction packet.

Read only the bounded idea units below. Propose a small number of durable L1 candidates only if
this extraction packet clearly contains one of these types: {allowed_types}.
Return an empty candidates list if the extraction packet is purely filler, logistics, acknowledgements, or unclear.
Do not invent information outside the supplied unit IDs.
Prior context may help disambiguate references, but it is never evidence.
Return at most {MAX_FALLBACK_CANDIDATES} candidates.
{"Every candidate must include legacy_type using one of: " + ", ".join(sorted(LEGACY_COMPATIBILITY_DESCRIPTIONS)) + "." if include_legacy_type else ""}
Return JSON only.

{L1_LANGUAGE_POLICY}

Extraction packet: {extraction_scope or "(single bounded extraction packet)"}
Segment IDs: {", ".join(segment_ids) if segment_ids else "(not provided)"}
Known related topics: {", ".join(existing_topics[:80]) if existing_topics else "(none)"}

{prior_context_text}

{previous_context_text}

{batch_metadata_text}

Bounded idea units:
{units_text}
""".strip()
    safe_scope = (extraction_scope or "batch").replace("/", "_").replace(" ", "_")
    data = runner.call_json(
        f"l1_fallback_agent_{safe_scope}",
        prompt,
        (
            fallback_candidate_schema_for_taxonomy(
                taxonomy,
                include_legacy_type=include_legacy_type,
                max_items=MAX_FALLBACK_CANDIDATES,
            )
            if taxonomy != "v1" or include_legacy_type
            else FALLBACK_CANDIDATE_SCHEMA
        ),
    )
    candidates: list[L1Candidate] = []
    for index, row in enumerate(data.get("candidates", []), start=1):
        obj_type = str(row.get("type", "")).strip().lower()
        if obj_type not in allowed_type_set:
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
                legacy_type=(
                    normalize_legacy_type(row.get("legacy_type"), obj_type=obj_type)
                    if include_legacy_type
                    else ""
                ),
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: (candidate.importance, candidate.confidence),
        reverse=True,
    )[:MAX_FALLBACK_CANDIDATES]
