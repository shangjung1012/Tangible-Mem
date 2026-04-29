"""Gemini function-calling orchestrator for incremental L1 extraction."""

from __future__ import annotations

import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from embedder import EmbedCache
from gemini_clients import create_gemini_client, get_configured_client_count
from incremental_store import (
    READ_PURPOSES,
    get_max_line_id,
    load_issues,
    load_l1_objects,
    read_transcript_span,
    record_issue_mention,
    resolve_issue_reference,
    save_l1_object,
    seed_transcript_lines,
    upsert_issue,
)
from importance import IMPORTANCE_SCALE
from schema import MEMORY_OBJ_TYPES

AUTO_TOOL_ROUND_BUFFER = 40
AUTO_TOOL_ROUND_MULTIPLIER = 8
KNOWN_ISSUES_PROMPT_LIMIT = 16
MAX_ISSUE_EVIDENCE_LINES_PER_UPDATE = 8
CONTEXT_RESET_INTERVAL_ROUNDS = 18
MAX_CONTENT_ITEMS_BEFORE_RESET = 36
SINGLE_KEY_MIN_REQUEST_INTERVAL_S = 12.5
SINGLE_KEY_MAX_RETRIES = 6
_RETRY_DELAY_RE = re.compile(r"retry in ([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)


@dataclass(frozen=True)
class ReadSpanRecord:
    purpose: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class IncrementalExtractionResult:
    transcript_id: str
    db_path: Path
    max_line: int
    max_forward_line: int
    raw_objects: list[dict[str, Any]]
    issues: list[dict[str, Any]]


@dataclass
class ToolLoopState:
    active_forward_span: ReadSpanRecord | None = None
    forward_span_issue_ids: list[str] = field(default_factory=list)
    pending_finalization: bool = False
    final_span: ReadSpanRecord | None = None


def next_forward_span(
    max_forward_line: int,
    max_line: int,
    chunk_size: int,
) -> tuple[int, int]:
    start = min(max_line, max(0, max_forward_line) + 1)
    end = min(max_line, start + max(1, chunk_size) - 1)
    return start, end


def update_forward_progress(
    current_line: int,
    *,
    purpose: str,
    end_line: int,
    max_line: int,
) -> int:
    if purpose != "forward_scan":
        return current_line
    return min(max_line, max(current_line, end_line))


def should_stop(max_forward_line: int, max_line: int) -> bool:
    return max_line <= 0 or max_forward_line >= max_line


def auto_max_tool_rounds(max_line: int, chunk_size: int) -> int:
    forward_spans = max(1, (max_line + max(1, chunk_size) - 1) // max(1, chunk_size))
    return AUTO_TOOL_ROUND_BUFFER + (forward_spans * AUTO_TOOL_ROUND_MULTIPLIER)


def resolve_max_tool_rounds(
    requested_rounds: int,
    *,
    max_line: int,
    chunk_size: int,
) -> tuple[int, bool]:
    requested_rounds = int(requested_rounds or 0)
    if requested_rounds > 0:
        return requested_rounds, False
    return auto_max_tool_rounds(max_line, chunk_size), True


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_float(value: Any, fallback: float = 0.5) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _safe_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _safe_int_list(value: Any) -> list[int]:
    if isinstance(value, list):
        output: list[int] = []
        for item in value:
            try:
                output.append(int(item))
            except (TypeError, ValueError):
                continue
        return output
    try:
        return [int(value)]
    except (TypeError, ValueError):
        return []


def _sanitize_issue_id_ref(value: Any) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    upper = clean.upper()
    if upper.startswith("RAW-") or upper.startswith("L1-"):
        return ""
    return clean


def _normalize_line_ids(line_ids: list[int], max_line: int) -> list[int]:
    output = sorted(
        {
            line_id
            for line_id in line_ids
            if 1 <= int(line_id) <= max(1, int(max_line or 0))
        }
    )
    return output


def _compact_issue_line_ids(
    line_ids: list[int],
    *,
    max_points: int = MAX_ISSUE_EVIDENCE_LINES_PER_UPDATE,
) -> list[int]:
    if len(line_ids) <= max_points:
        return line_ids
    if max_points <= 1:
        return [line_ids[0]]

    selected = {line_ids[0], line_ids[-1]}
    slots = max_points - len(selected)
    if slots > 0:
        span = len(line_ids) - 1
        for index in range(1, slots + 1):
            position = round((index / (slots + 1)) * span)
            selected.add(line_ids[position])
    return sorted(selected)


def _select_recent_span(
    recent_reads: list[ReadSpanRecord],
    *,
    preferred_purpose: str = "",
) -> ReadSpanRecord | None:
    for span in reversed(recent_reads):
        if not preferred_purpose or span.purpose == preferred_purpose:
            return span
    return recent_reads[-1] if recent_reads else None


def _tokenize_overlap_text(text: str) -> set[str]:
    tokens: set[str] = set()
    for chunk in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", str(text or "")):
        clean = chunk.strip().lower()
        if not clean:
            continue
        tokens.add(clean)
        if re.fullmatch(r"[\u4e00-\u9fff]+", clean) and len(clean) > 1:
            tokens.update(clean)
    return tokens


def _token_overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _resolve_current_span_issue_for_object(
    *,
    db_path: Path,
    transcript_id: str,
    tool_state: ToolLoopState,
    content: str,
    evidence: str,
    related_topics: list[str],
) -> str:
    candidate_ids = [issue_id for issue_id in tool_state.forward_span_issue_ids if issue_id]
    if len(candidate_ids) <= 1:
        return candidate_ids[0] if candidate_ids else ""

    issue_by_id = {
        str(issue.get("issue_id") or ""): issue
        for issue in load_issues(db_path, transcript_id)
    }
    object_tokens = _tokenize_overlap_text(
        f"{content}\n{evidence}\n{' '.join(related_topics)}"
    )
    scored: list[tuple[float, str]] = []
    for issue_id in candidate_ids:
        issue = issue_by_id.get(issue_id)
        if issue is None:
            continue
        issue_tokens = _tokenize_overlap_text(
            f"{issue.get('title', '')}\n{issue.get('summary', '')}"
        )
        score = _token_overlap_score(object_tokens, issue_tokens)
        scored.append((score, issue_id))

    if not scored:
        return ""
    scored.sort(reverse=True)
    best_score, best_issue_id = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.12 and (best_score - second_score) >= 0.03:
        return best_issue_id
    return ""


def _bound_line_ids_to_recent_span(
    line_ids: list[int],
    *,
    recent_reads: list[ReadSpanRecord],
    explicit_purpose: str,
) -> list[int]:
    if not line_ids:
        return []
    preferred_purpose = explicit_purpose if explicit_purpose in READ_PURPOSES else ""
    span = _select_recent_span(recent_reads, preferred_purpose=preferred_purpose)
    if span is None:
        return sorted({int(line_id) for line_id in line_ids})
    bounded = [
        min(span.end_line, max(span.start_line, int(line_id)))
        for line_id in line_ids
    ]
    return sorted(set(bounded))


def _infer_issue_purpose(
    *,
    explicit_purpose: str,
    line_ids: list[int],
    recent_reads: list[ReadSpanRecord],
) -> str:
    if explicit_purpose in READ_PURPOSES and explicit_purpose != "candidate_refine":
        return explicit_purpose
    if not line_ids:
        return explicit_purpose if explicit_purpose in READ_PURPOSES else "forward_scan"

    best_span: ReadSpanRecord | None = None
    best_overlap = -1
    for span in reversed(recent_reads):
        overlap = sum(1 for line_id in line_ids if span.start_line <= line_id <= span.end_line)
        if overlap > best_overlap:
            best_overlap = overlap
            best_span = span
    if best_span is not None and best_overlap > 0:
        return best_span.purpose
    if explicit_purpose in READ_PURPOSES:
        return explicit_purpose
    return "forward_scan"


def _tool_declarations() -> types.Tool:
    read_transcript = types.FunctionDeclaration(
        name="read_transcript",
        description=(
            "Read a span of transcript lines. Use forward_scan for top-down progress; "
            "use lookback, lookahead, or candidate_refine only for local context."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "purpose": {
                    "type": "string",
                    "enum": sorted(READ_PURPOSES),
                },
            },
            "required": ["start_line", "end_line", "purpose"],
            "additionalProperties": False,
        },
    )
    update_issue = types.FunctionDeclaration(
        name="update_issue",
        description=(
            "Create or update the working issue table after reading transcript evidence. "
            "Reuse issue_id or issue_key when the same issue returns later. "
            "Importance will be calibrated against separated mention episodes. "
            "Use 1-8 concrete evidence line_ids, not every line in a long span."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "issue_id": {"type": "string"},
                "issue_key": {
                    "type": "string",
                    "description": "Stable snake_case key for the issue, reused across mentions in this transcript.",
                },
                "title": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["open", "resolved", "superseded", "unclear"],
                },
                "importance": {"type": "number"},
                "summary": {"type": "string"},
                "line_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "purpose": {
                    "type": "string",
                    "enum": sorted(READ_PURPOSES),
                },
                "note": {"type": "string"},
            },
            "required": ["title", "summary"],
            "additionalProperties": False,
        },
    )
    create_l1_object = types.FunctionDeclaration(
        name="create_l1_object",
        description=(
            "Create one raw L1 memory object candidate using the existing long_term schema. "
            "Only create durable decisions, todos, method changes, results, open questions, or arguments. "
            "Use the shared 0.0-1.0 importance scale. Prefer one higher-level durable object over many checklist fragments. "
            "Include the exact issue_id returned by update_issue when this object belongs to a known recurring issue. "
            "If you only know issue_key, pass it in issue_key."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "Known issue_id from update_issue when this object belongs to that issue.",
                },
                "issue_key": {
                    "type": "string",
                    "description": "Fallback stable issue_key when issue_id is not available.",
                },
                "type": {
                    "type": "string",
                    "enum": sorted(MEMORY_OBJ_TYPES),
                },
                "content": {"type": "string"},
                "importance": {"type": "number"},
                "evidence": {"type": "string"},
                "related_topics": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["type", "content", "importance", "evidence", "related_topics"],
            "additionalProperties": False,
        },
    )
    return types.Tool(
        function_declarations=[read_transcript, update_issue, create_l1_object]
    )


def _build_system_instruction(
    transcript_id: str,
    existing_topics: list[str],
    chunk_size: int,
    request_constrained: bool = False,
) -> str:
    topics = ", ".join(existing_topics) if existing_topics else "(none)"
    request_constrained_rules = ""
    if request_constrained:
        request_constrained_rules = """
13. You are in request-constrained single-key mode. Minimize generate_content turns and avoid one-call responses when more actions from the same span are already clear.
14. For a typical forward_scan span, prefer to batch all necessary update_issue and create_l1_object calls, then request the next forward_scan span in the same response.
""".rstrip()
    return f"""
You are the incremental long-term memory bridge for transcript {transcript_id}.

Use the existing L1 schema exactly:
decision / todo / method_change / result / open_question / argument.

Importance scale:
{IMPORTANCE_SCALE}

Rules:
1. Start with read_transcript using purpose="forward_scan" and continue top-down.
2. Default chunk size is about {chunk_size} lines.
3. If the first line depends on prior context, read nearby prior lines with purpose="lookback".
4. If the last line is incomplete or an event is unfolding, read nearby next lines with purpose="lookahead".
5. After reading evidence, update_issue before creating L1 objects.
6. Create L1 objects only for durable memory worth preserving in long-term memory.
7. Do not explode one issue into many checklist fragments. Merge sub-items into one higher-level durable memory object whenever they belong to the same decision, method change, or result.
8. Use concise Traditional Chinese for issue titles, issue summaries, and L1 content. Evidence may quote the source language.
9. For update_issue, cite only a few concrete evidence lines (usually 1-4, at most 8).
10. When create_l1_object is linked to an existing issue, prefer the exact issue_id returned by update_issue over issue_key.
11. Batch related update_issue and create_l1_object calls for the same read_transcript span in one response whenever possible.
12. Continue until forward_scan has reached the final transcript line reported by read_transcript.
{request_constrained_rules}

Known related topics: {topics}
""".strip()


def _build_initial_prompt(
    transcript_id: str,
    max_line: int,
    chunk_size: int,
    *,
    request_constrained: bool = False,
) -> str:
    start, end = next_forward_span(0, max_line, chunk_size)
    prompt = (
        f"Transcript {transcript_id} has {max_line} stored lines. "
        f"Begin by calling read_transcript(start_line={start}, end_line={end}, "
        'purpose="forward_scan"). Continue until the final line is processed.'
    )
    if request_constrained:
        prompt += (
            " Use as few model turns as possible: after reading a span, batch the "
            "needed issue updates and L1 creations together, then request the next "
            "forward_scan span in the same response when the local context is clear."
        )
    return prompt


def _build_finalization_prompt(
    *,
    transcript_id: str,
    max_line: int,
    tool_state: ToolLoopState,
    had_tool_errors: bool = False,
) -> str:
    span = tool_state.final_span or tool_state.active_forward_span
    span_text = (
        f"{span.start_line}-{span.end_line}"
        if span is not None
        else f"ending at line {max_line}"
    )
    active_issue_ids = ", ".join(tool_state.forward_span_issue_ids) or "(none yet)"
    prompt = (
        f"forward_scan is complete for transcript {transcript_id} at line {max_line}. "
        f"You have already read the final span {span_text}. "
        "Do not call read_transcript again. "
        "Finish any remaining issue updates and L1 object creations for that final span now, "
        "in one response if possible. "
        f"Active issue_ids from that final span: {active_issue_ids}. "
        "If more than one issue is active, every create_l1_object must include the explicit issue_id."
    )
    if had_tool_errors:
        prompt += (
            " The previous response had tool-call errors because an object was missing a usable "
            "issue_id/issue_key. Fix those links now."
        )
    prompt += " If nothing remains, return no tool calls."
    return prompt


def _post_tool_round_action(
    *,
    max_forward_line: int,
    max_line: int,
    tool_state: ToolLoopState,
    had_forward_read: bool,
    had_tool_errors: bool,
) -> str:
    if not should_stop(max_forward_line, max_line):
        return "continue"
    if not tool_state.pending_finalization:
        return "complete"
    if had_forward_read:
        return "finalize_next_round"
    if had_tool_errors:
        return "retry_finalization"
    return "complete"


def _build_config(
    transcript_id: str,
    existing_topics: list[str],
    chunk_size: int,
    request_constrained: bool = False,
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=_build_system_instruction(
            transcript_id=transcript_id,
            existing_topics=existing_topics,
            chunk_size=chunk_size,
            request_constrained=request_constrained,
        ),
        temperature=0.15,
        tools=[_tool_declarations()],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")
        ),
    )


def _min_request_interval_for_key_count(key_count: int) -> float:
    return SINGLE_KEY_MIN_REQUEST_INTERVAL_S if key_count <= 1 else 0.0


def _max_retry_attempts_for_key_count(key_count: int) -> int:
    return SINGLE_KEY_MAX_RETRIES if key_count <= 1 else 4


def _is_retryable_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status_code in {429, 500, 502, 503, 504}:
        return True
    msg = str(exc).upper()
    return any(
        token in msg
        for token in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "RESOURCE_EXHAUSTED",
            "UNAVAILABLE",
            "RATE LIMIT",
        )
    )


def _extract_retry_delay_seconds(exc: Exception) -> float | None:
    message = str(exc)
    match = _RETRY_DELAY_RE.search(message)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _line_ids_overlap_span(
    line_ids: list[int],
    span: ReadSpanRecord | None,
) -> bool:
    if span is None:
        return False
    return any(span.start_line <= int(line_id) <= span.end_line for line_id in line_ids)


def _wait_for_request_slot(
    request_state: dict[str, float],
    *,
    min_request_interval_s: float,
    progress: bool,
) -> None:
    if min_request_interval_s <= 0:
        return
    last_started = float(request_state.get("last_request_started_at", 0.0))
    now = time.monotonic()
    wait_s = min_request_interval_s - (now - last_started)
    if wait_s > 0:
        _progress_log(
            progress,
            f"[incremental] pacing single-key Gemini requests, sleeping {wait_s:.1f}s.",
        )
        time.sleep(wait_s)
    request_state["last_request_started_at"] = time.monotonic()


def _generate_with_retry(
    client: Any,
    *,
    model_name: str,
    contents: list[types.Content],
    config: types.GenerateContentConfig,
    max_retries: int = 4,
    min_request_interval_s: float = 0.0,
    request_state: dict[str, float] | None = None,
    progress: bool = False,
) -> types.GenerateContentResponse:
    for attempt in range(1, max_retries + 1):
        try:
            if request_state is not None:
                _wait_for_request_slot(
                    request_state,
                    min_request_interval_s=min_request_interval_s,
                    progress=progress,
                )
            return client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable_error(exc):
                raise
            retry_delay = _extract_retry_delay_seconds(exc) or 0.0
            wait_s = max(
                retry_delay,
                min(30.0, 1.5 * (2 ** (attempt - 1))) + random.uniform(0, 1.0),
            )
            if min_request_interval_s > 0:
                wait_s = max(wait_s, min_request_interval_s)
            print(
                f"  API busy ({type(exc).__name__}), "
                f"retry {attempt}/{max_retries} in {wait_s:.1f}s..."
            )
            time.sleep(wait_s)
    raise RuntimeError("Unexpected retry loop exit.")


def _progress_percent(max_forward_line: int, max_line: int) -> float:
    if max_line <= 0:
        return 100.0
    return min(100.0, max(0.0, (max_forward_line / max_line) * 100.0))


def _progress_log(enabled: bool, message: str) -> None:
    if enabled:
        print(message, file=sys.stderr, flush=True)


def _tool_progress_summary(
    function_call: types.FunctionCall,
    payload: dict[str, Any],
    previous_forward_line: int,
    current_forward_line: int,
) -> str:
    name = function_call.name or "unknown_tool"
    args = function_call.args or {}
    if "error" in payload:
        return f"{name} error={payload['error']}"

    if name == "read_transcript":
        span = payload.get("output", {})
        purpose = span.get("purpose", args.get("purpose", ""))
        start_line = span.get("start_line", "?")
        end_line = span.get("end_line", "?")
        moved = current_forward_line - previous_forward_line
        correction = payload.get("correction", {})
        correction_note = ""
        if correction:
            correction_note = (
                f" enforced_from={correction.get('requested_start_line', '?')}"
                f"-{correction.get('requested_end_line', '?')}"
            )
        if moved > 0:
            return (
                f"read_transcript {purpose} lines {start_line}-{end_line} "
                f"(+{moved}){correction_note}"
            )
        return f"read_transcript {purpose} lines {start_line}-{end_line}{correction_note}"

    if name == "update_issue":
        output = payload.get("output", {})
        issue = output.get("issue", {})
        mention_ids = output.get("mention_ids", [])
        return (
            "update_issue "
            f"{issue.get('issue_id', '?')} "
            f"episodes={issue.get('episode_count', 0)} "
            f"mentions+={len(mention_ids)} "
            f"purpose={issue.get('last_purpose', '?')}"
        )

    if name == "create_l1_object":
        output = payload.get("output", {})
        raw_object = output.get("object", {})
        return (
            "create_l1_object "
            f"{output.get('obj_id', '?')} "
            f"type={raw_object.get('type', '?')}"
        )

    return name


def _extract_function_calls(
    response: types.GenerateContentResponse,
) -> list[types.FunctionCall]:
    calls = list(response.function_calls or [])
    if calls:
        return calls
    output: list[types.FunctionCall] = []
    for candidate in response.candidates or []:
        content = candidate.content
        if not content:
            continue
        for part in content.parts or []:
            if part.function_call:
                output.append(part.function_call)
    return output


def _model_content(response: types.GenerateContentResponse) -> types.Content | None:
    candidates = response.candidates or []
    if not candidates:
        return None
    return candidates[0].content


def build_function_response_part(
    function_call: types.FunctionCall,
    response: dict[str, Any],
) -> types.Part:
    """Build a function response part while preserving Gemini call IDs."""
    return types.Part(
        function_response=types.FunctionResponse(
            id=function_call.id,
            name=function_call.name or "",
            response=response,
        )
    )


def _execute_tool_call(
    *,
    db_path: Path,
    transcript_id: str,
    function_call: types.FunctionCall,
    max_line: int,
    max_forward_line: int,
    chunk_size: int,
    recent_reads: list[ReadSpanRecord],
    tool_state: ToolLoopState | None = None,
    api_key: str | list[str] | None = None,
    embed_cache: EmbedCache | None = None,
) -> tuple[dict[str, Any], int]:
    name = function_call.name or ""
    args = function_call.args or {}
    tool_state = tool_state or ToolLoopState()

    try:
        if name == "read_transcript":
            purpose = str(args.get("purpose") or "forward_scan")
            if purpose not in READ_PURPOSES:
                purpose = "forward_scan"

            requested_start_line = _safe_int(args.get("start_line"), max_forward_line + 1)
            requested_end_line = _safe_int(
                args.get("end_line"),
                requested_start_line + chunk_size - 1,
            )
            start_line = requested_start_line
            end_line = requested_end_line
            correction: dict[str, int] = {}

            if purpose == "forward_scan":
                expected_start, expected_end = next_forward_span(
                    max_forward_line, max_line, chunk_size
                )
                start_line = expected_start
                end_line = expected_end
                if (
                    requested_start_line != expected_start
                    or requested_end_line != expected_end
                ):
                    correction = {
                        "requested_start_line": requested_start_line,
                        "requested_end_line": requested_end_line,
                        "enforced_start_line": start_line,
                        "enforced_end_line": end_line,
                    }
            elif end_line < start_line:
                end_line = min(max_line, start_line + chunk_size - 1)

            span = read_transcript_span(
                db_path=db_path,
                transcript_id=transcript_id,
                start_line=start_line,
                end_line=end_line,
                purpose=purpose,
            )
            recent_reads.append(
                ReadSpanRecord(
                    purpose=purpose,
                    start_line=int(span["start_line"]),
                    end_line=int(span["end_line"]),
                )
            )
            del recent_reads[:-8]
            if purpose == "forward_scan":
                tool_state.active_forward_span = ReadSpanRecord(
                    purpose=purpose,
                    start_line=int(span["start_line"]),
                    end_line=int(span["end_line"]),
                )
                tool_state.forward_span_issue_ids.clear()
            new_progress = update_forward_progress(
                max_forward_line,
                purpose=purpose,
                end_line=int(span["end_line"]),
                max_line=max_line,
            )
            if purpose == "forward_scan" and new_progress >= max_line:
                tool_state.pending_finalization = True
                tool_state.final_span = tool_state.active_forward_span
            return (
                {
                    "output": span,
                    "progress": {
                        "max_forward_line": new_progress,
                        "max_line": max_line,
                    },
                    "correction": correction,
                },
                new_progress,
            )

        if name == "update_issue":
            explicit_purpose = str(args.get("purpose") or "")
            line_ids = _compact_issue_line_ids(
                _bound_line_ids_to_recent_span(
                    _normalize_line_ids(
                        _safe_int_list(args.get("line_ids", [])),
                        max_line,
                    ),
                    recent_reads=recent_reads,
                    explicit_purpose=explicit_purpose,
                )
            )
            purpose = _infer_issue_purpose(
                explicit_purpose=explicit_purpose,
                line_ids=line_ids,
                recent_reads=recent_reads,
            )
            issue = upsert_issue(
                db_path=db_path,
                transcript_id=transcript_id,
                issue_id=_sanitize_issue_id_ref(args.get("issue_id")),
                issue_key=str(args.get("issue_key") or ""),
                title=str(args.get("title") or ""),
                status=str(args.get("status") or "open"),
                importance=_safe_float(args.get("importance"), 0.5),
                summary=str(args.get("summary") or ""),
                api_key=api_key,
                embed_cache=embed_cache,
            )
            mention_ids: list[int] = []
            for line_id in line_ids:
                mention_ids.append(
                    record_issue_mention(
                        db_path=db_path,
                        transcript_id=transcript_id,
                        issue_id=issue["issue_id"],
                        line_id=line_id,
                        purpose=purpose,
                        note=str(args.get("note") or ""),
                    )
                )
            refreshed_issue = next(
                (
                    item
                    for item in load_issues(db_path, transcript_id)
                    if item.get("issue_id") == issue["issue_id"]
                ),
                issue,
            )
            refreshed_issue = dict(refreshed_issue)
            refreshed_issue["last_purpose"] = purpose
            if purpose == "forward_scan" and (
                not line_ids or _line_ids_overlap_span(line_ids, tool_state.active_forward_span)
            ):
                issue_id = str(refreshed_issue.get("issue_id") or "").strip()
                if issue_id and issue_id not in tool_state.forward_span_issue_ids:
                    tool_state.forward_span_issue_ids.append(issue_id)
            return {
                "output": {
                    "issue": refreshed_issue,
                    "mention_ids": mention_ids,
                    "bounded_line_ids": line_ids,
                }
            }, max_forward_line

        if name == "create_l1_object":
            obj_type = str(args.get("type") or "decision").lower()
            if obj_type not in MEMORY_OBJ_TYPES:
                obj_type = "decision"
            content = str(args.get("content") or "").strip()
            evidence = str(args.get("evidence") or "").strip()
            related_topics = _safe_str_list(args.get("related_topics", []))
            issue_ref = _sanitize_issue_id_ref(args.get("issue_id"))
            issue_key = str(args.get("issue_key") or "").strip()
            if not issue_ref and not issue_key:
                if len(tool_state.forward_span_issue_ids) == 1:
                    issue_ref = tool_state.forward_span_issue_ids[0]
                elif len(tool_state.forward_span_issue_ids) > 1:
                    issue_ref = _resolve_current_span_issue_for_object(
                        db_path=db_path,
                        transcript_id=transcript_id,
                        tool_state=tool_state,
                        content=content,
                        evidence=evidence,
                        related_topics=related_topics,
                    )
                    if issue_ref:
                        issue_key = ""
                elif not tool_state.forward_span_issue_ids and tool_state.active_forward_span is not None:
                    span = tool_state.active_forward_span
                    return {
                        "error": (
                            "create_l1_object requires update_issue first for the current "
                            f"forward_scan span {span.start_line}-{span.end_line}. "
                            "Call update_issue with a concise title/summary and a few evidence line_ids, "
                            "then retry create_l1_object with that issue_id."
                        )
                    }, max_forward_line
                if len(tool_state.forward_span_issue_ids) > 1 and not issue_ref and not issue_key:
                    return {
                        "error": (
                            "create_l1_object requires an explicit issue_id or issue_key because "
                            "multiple issues were already updated for the current forward_scan span: "
                            + ", ".join(tool_state.forward_span_issue_ids)
                        )
                    }, max_forward_line
            resolved_issue = resolve_issue_reference(
                db_path,
                transcript_id,
                issue_ref=issue_ref,
                issue_key=issue_key,
                api_key=api_key,
                embed_cache=embed_cache,
            )
            if not str(resolved_issue.get("issue_id") or "").strip() and not str(
                resolved_issue.get("issue_key") or ""
            ).strip():
                return {
                    "error": (
                        "create_l1_object could not resolve a linked issue. "
                        "Call update_issue first, then retry with the returned issue_id."
                    )
                }, max_forward_line
            raw_object = {
                "type": obj_type,
                "content": content,
                "importance": _safe_float(args.get("importance"), 0.5),
                "evidence": evidence,
                "related_topics": related_topics,
            }
            obj_id = save_l1_object(
                db_path=db_path,
                transcript_id=transcript_id,
                issue_id=resolved_issue["issue_id"],
                issue_key=resolved_issue["issue_key"],
                row=raw_object,
            )
            return {
                "output": {
                    "obj_id": obj_id,
                    "object": raw_object,
                    "issue_id": resolved_issue["issue_id"],
                }
            }, max_forward_line

        return {"error": f"Unknown tool: {name}"}, max_forward_line
    except Exception as exc:
        return {"error": str(exc)}, max_forward_line


def _select_known_issues(issues: list[dict[str, Any]], limit: int = KNOWN_ISSUES_PROMPT_LIMIT) -> list[dict[str, Any]]:
    return sorted(
        issues,
        key=lambda issue: (
            -int(issue.get("episode_count", 0) or 0),
            -float(issue.get("importance", 0.0) or 0.0),
            -int(issue.get("mention_count", 0) or 0),
            str(issue.get("updated_at_utc") or ""),
        ),
    )[:limit]


def _format_known_issues(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return "(none)"
    lines: list[str] = []
    for issue in _select_known_issues(issues):
        summary = str(issue.get("summary") or "")
        if len(summary) > 140:
            summary = summary[:140] + "..."
        lines.append(
            "- "
            f"issue_id={issue.get('issue_id')} "
            f"issue_key={issue.get('issue_key')} "
            f"title={issue.get('title')} "
            f"episodes={issue.get('episode_count', 0)} "
            f"summary={summary}"
        )
    return "\n".join(lines)


def _continue_prompt(
    max_forward_line: int,
    max_line: int,
    chunk_size: int,
    known_issues: list[dict[str, Any]],
    *,
    request_constrained: bool = False,
) -> str:
    start, end = next_forward_span(max_forward_line, max_line, chunk_size)
    prompt = (
        "Continue the top-down scan. "
        f"The next unread forward_scan span should start at line {start} "
        f"and may end around line {end}. Do not stop until line {max_line} is processed.\n\n"
        "Batch related issue updates and L1 object creations from the same span instead of issuing one tiny tool call at a time.\n\n"
        "Known issues in this transcript. Reuse issue_id/issue_key if the new span returns to the same issue:\n"
        f"{_format_known_issues(known_issues)}"
    )
    if request_constrained:
        prompt += (
            "\n\nRequest-constrained single-key mode: prefer about one to two model turns "
            "per forward_scan span. Avoid separate one-call turns when the same span already "
            "supports multiple issue updates, object creations, or the next forward_scan."
        )
    return prompt


def _reset_contents(
    *,
    transcript_id: str,
    max_forward_line: int,
    max_line: int,
    chunk_size: int,
    known_issues: list[dict[str, Any]],
    request_constrained: bool = False,
) -> list[types.Content]:
    return [
        types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        f"Resume incremental extraction for transcript {transcript_id}. "
                        f"forward_scan has already processed through line {max_forward_line} of {max_line}.\n\n"
                        f"{_continue_prompt(max_forward_line, max_line, chunk_size, known_issues, request_constrained=request_constrained)}\n\n"
                        "Persisted issues and raw L1 candidates already exist in the SQLite working store. "
                        "Do not recreate near-duplicate objects; refine or extend only when the new span adds durable information."
                    )
                )
            ],
        )
    ]


def extract_incremental_l1_objects(
    *,
    model_name: str,
    api_key: str | list[str],
    transcript: str,
    transcript_id: str,
    db_path: Path,
    existing_topics: list[str],
    chunk_size: int = 40,
    max_tool_rounds: int = 0,
    progress: bool = True,
    client: Any | None = None,
) -> IncrementalExtractionResult:
    db_path = Path(db_path)
    chunk_size = max(1, int(chunk_size))
    requested_tool_rounds = int(max_tool_rounds or 0)

    seed_transcript_lines(db_path, transcript_id, transcript, replace=True)
    max_line = get_max_line_id(db_path, transcript_id)
    if max_line <= 0:
        return IncrementalExtractionResult(
            transcript_id=transcript_id,
            db_path=db_path,
            max_line=0,
            max_forward_line=0,
            raw_objects=[],
            issues=[],
        )

    max_tool_rounds, auto_rounds = resolve_max_tool_rounds(
        requested_tool_rounds,
        max_line=max_line,
        chunk_size=chunk_size,
    )
    round_source = "auto" if auto_rounds else "manual"
    _progress_log(
        progress,
        (
            f"[incremental] {transcript_id}: {max_line} transcript lines, "
            f"chunk_size={chunk_size}, max_tool_rounds={max_tool_rounds} ({round_source})"
        ),
    )

    client = client or create_gemini_client(api_key)
    key_count = get_configured_client_count(api_key)
    request_constrained = key_count <= 1
    min_request_interval_s = _min_request_interval_for_key_count(key_count)
    max_retries = _max_retry_attempts_for_key_count(key_count)
    if min_request_interval_s > 0:
        _progress_log(
            progress,
            (
                f"[incremental] single-key pacing enabled: "
                f"min_request_interval={min_request_interval_s:.1f}s"
            ),
        )
    config = _build_config(
        transcript_id=transcript_id,
        existing_topics=existing_topics,
        chunk_size=chunk_size,
        request_constrained=request_constrained,
    )
    contents: list[types.Content] = [
        types.Content(
            role="user",
            parts=[
                types.Part(
                    text=_build_initial_prompt(
                        transcript_id,
                        max_line,
                        chunk_size,
                        request_constrained=request_constrained,
                    )
                )
            ],
        )
    ]

    max_forward_line = 0
    recent_reads: list[ReadSpanRecord] = []
    tool_state = ToolLoopState()
    request_state: dict[str, float] = {}
    issue_embed_cache = EmbedCache()
    try:
        for round_index in range(1, max_tool_rounds + 1):
            _progress_log(
                progress,
                (
                    f"[incremental] round {round_index}/{max_tool_rounds}: "
                    f"requesting Gemini, progress={max_forward_line}/{max_line} "
                    f"({_progress_percent(max_forward_line, max_line):.1f}%)"
                ),
            )
            response = _generate_with_retry(
                client,
                model_name=model_name,
                contents=contents,
                config=config,
                max_retries=max_retries,
                min_request_interval_s=min_request_interval_s,
                request_state=request_state,
                progress=progress,
            )
            function_calls = _extract_function_calls(response)
            model_content = _model_content(response)

            if function_calls:
                if model_content is not None:
                    contents.append(model_content)
                response_parts: list[types.Part] = []
                summaries: list[str] = []
                had_tool_errors = False
                had_forward_read = False
                for function_call in function_calls:
                    previous_forward_line = max_forward_line
                    payload, max_forward_line = _execute_tool_call(
                        db_path=db_path,
                        transcript_id=transcript_id,
                        function_call=function_call,
                        max_line=max_line,
                        max_forward_line=max_forward_line,
                        chunk_size=chunk_size,
                        recent_reads=recent_reads,
                        tool_state=tool_state,
                        api_key=api_key,
                        embed_cache=issue_embed_cache,
                    )
                    had_tool_errors = had_tool_errors or ("error" in payload)
                    had_forward_read = had_forward_read or (
                        (function_call.name or "") == "read_transcript"
                        and str((function_call.args or {}).get("purpose") or "forward_scan") == "forward_scan"
                    )
                    summaries.append(
                        _tool_progress_summary(
                            function_call,
                            payload,
                            previous_forward_line,
                            max_forward_line,
                        )
                    )
                    response_parts.append(
                        build_function_response_part(function_call, payload)
                    )
                contents.append(types.Content(role="user", parts=response_parts))
                _progress_log(
                    progress,
                    (
                        f"[incremental] round {round_index}/{max_tool_rounds}: "
                        f"{'; '.join(summaries)}; "
                        f"progress={max_forward_line}/{max_line} "
                        f"({_progress_percent(max_forward_line, max_line):.1f}%), "
                        f"issues={len(load_issues(db_path, transcript_id))}, "
                        f"raw_l1={len(load_l1_objects(db_path, transcript_id))}"
                    ),
                )
                post_round_action = _post_tool_round_action(
                    max_forward_line=max_forward_line,
                    max_line=max_line,
                    tool_state=tool_state,
                    had_forward_read=had_forward_read,
                    had_tool_errors=had_tool_errors,
                )
                if post_round_action in {"finalize_next_round", "retry_finalization"}:
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[
                                types.Part(
                                    text=_build_finalization_prompt(
                                        transcript_id=transcript_id,
                                        max_line=max_line,
                                        tool_state=tool_state,
                                        had_tool_errors=had_tool_errors,
                                    )
                                )
                            ],
                        )
                    )
                    _progress_log(
                        progress,
                        (
                            f"[incremental] round {round_index}/{max_tool_rounds}: "
                            "forward_scan reached the final line; "
                            "entering finalization mode for the last span."
                        ),
                    )
                    continue
                if post_round_action == "complete":
                    tool_state.pending_finalization = False
                    _progress_log(
                        progress,
                        (
                            f"[incremental] completed scan at line "
                            f"{max_forward_line}/{max_line}."
                        ),
                    )
                    break
                if (
                    round_index % CONTEXT_RESET_INTERVAL_ROUNDS == 0
                    or len(contents) >= MAX_CONTENT_ITEMS_BEFORE_RESET
                ):
                    known_issues = load_issues(db_path, transcript_id)
                    contents = _reset_contents(
                        transcript_id=transcript_id,
                        max_forward_line=max_forward_line,
                        max_line=max_line,
                        chunk_size=chunk_size,
                        known_issues=known_issues,
                        request_constrained=request_constrained,
                    )
                    _progress_log(
                        progress,
                        (
                            f"[incremental] round {round_index}/{max_tool_rounds}: "
                            "compacted Gemini context from persisted DB state."
                        ),
                    )
                continue

            if should_stop(max_forward_line, max_line):
                _progress_log(
                    progress,
                    (
                        f"[incremental] completed scan at line "
                        f"{max_forward_line}/{max_line}."
                    ),
                )
                break

            if model_content is not None:
                contents.append(model_content)
            next_start, next_end = next_forward_span(max_forward_line, max_line, chunk_size)
            _progress_log(
                progress,
                (
                    f"[incremental] round {round_index}/{max_tool_rounds}: "
                    "Gemini returned no tool call; nudging next forward_scan "
                    f"lines {next_start}-{next_end}."
                ),
            )
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=_continue_prompt(
                                max_forward_line,
                                max_line,
                                chunk_size,
                                load_issues(db_path, transcript_id),
                            )
                        )
                    ],
                )
            )
        else:
            if not should_stop(max_forward_line, max_line):
                raise RuntimeError(
                    "Incremental extraction stopped before the final transcript line "
                    f"({max_forward_line}/{max_line}) after {max_tool_rounds} tool rounds. "
                    "Re-run with a larger --chunk-size or --max-tool-rounds."
                )
    finally:
        issue_embed_cache.save()

    if not should_stop(max_forward_line, max_line):
            raise RuntimeError(
                "Incremental extraction stopped before the final transcript line "
                f"({max_forward_line}/{max_line}) after {max_tool_rounds} tool rounds. "
                "Re-run with a larger --chunk-size or --max-tool-rounds."
            )

    raw_objects = load_l1_objects(
        db_path,
        transcript_id,
        include_issue_metadata=True,
    )
    issues = load_issues(db_path, transcript_id)
    _progress_log(
        progress,
        (
            f"[incremental] {transcript_id}: done, "
            f"issues={len(issues)}, raw_l1={len(raw_objects)}, db={db_path}"
        ),
    )

    return IncrementalExtractionResult(
        transcript_id=transcript_id,
        db_path=db_path,
        max_line=max_line,
        max_forward_line=max_forward_line,
        raw_objects=raw_objects,
        issues=issues,
    )
