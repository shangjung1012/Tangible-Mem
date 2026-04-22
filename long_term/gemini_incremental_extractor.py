"""Gemini function-calling orchestrator for incremental L1 extraction."""

from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from gemini_clients import create_gemini_client
from incremental_store import (
    READ_PURPOSES,
    get_max_line_id,
    load_issues,
    load_l1_objects,
    read_transcript_span,
    record_issue_mention,
    save_l1_object,
    seed_transcript_lines,
    upsert_issue,
)
from importance import IMPORTANCE_SCALE
from schema import MEMORY_OBJ_TYPES

AUTO_TOOL_ROUND_BUFFER = 20
AUTO_TOOL_ROUND_MULTIPLIER = 4


@dataclass(frozen=True)
class IncrementalExtractionResult:
    transcript_id: str
    db_path: Path
    max_line: int
    max_forward_line: int
    raw_objects: list[dict[str, Any]]
    issues: list[dict[str, Any]]


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
            "Importance will be calibrated against separated mention episodes."
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
            "Use the shared 0.0-1.0 importance scale."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "issue_id": {"type": "string"},
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
) -> str:
    topics = ", ".join(existing_topics) if existing_topics else "(none)"
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
7. Use Traditional Chinese for content when possible; evidence may quote the source language.
8. Continue until forward_scan has reached the final transcript line reported by read_transcript.

Known related topics: {topics}
""".strip()


def _build_initial_prompt(transcript_id: str, max_line: int, chunk_size: int) -> str:
    start, end = next_forward_span(0, max_line, chunk_size)
    return (
        f"Transcript {transcript_id} has {max_line} stored lines. "
        f"Begin by calling read_transcript(start_line={start}, end_line={end}, "
        'purpose="forward_scan"). Continue until the final line is processed.'
    )


def _build_config(
    transcript_id: str,
    existing_topics: list[str],
    chunk_size: int,
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=_build_system_instruction(
            transcript_id=transcript_id,
            existing_topics=existing_topics,
            chunk_size=chunk_size,
        ),
        temperature=0.15,
        tools=[_tool_declarations()],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")
        ),
    )


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


def _generate_with_retry(
    client: Any,
    *,
    model_name: str,
    contents: list[types.Content],
    config: types.GenerateContentConfig,
    max_retries: int = 4,
) -> types.GenerateContentResponse:
    for attempt in range(1, max_retries + 1):
        try:
            return client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable_error(exc):
                raise
            wait_s = min(30.0, 1.5 * (2 ** (attempt - 1))) + random.uniform(0, 1.0)
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
        if moved > 0:
            return f"read_transcript {purpose} lines {start_line}-{end_line} (+{moved})"
        return f"read_transcript {purpose} lines {start_line}-{end_line}"

    if name == "update_issue":
        output = payload.get("output", {})
        issue = output.get("issue", {})
        mention_ids = output.get("mention_ids", [])
        return (
            "update_issue "
            f"{issue.get('issue_id', '?')} "
            f"episodes={issue.get('episode_count', 0)} "
            f"mentions+={len(mention_ids)}"
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
) -> tuple[dict[str, Any], int]:
    name = function_call.name or ""
    args = function_call.args or {}

    try:
        if name == "read_transcript":
            purpose = str(args.get("purpose") or "forward_scan")
            if purpose not in READ_PURPOSES:
                purpose = "forward_scan"

            start_line = _safe_int(args.get("start_line"), max_forward_line + 1)
            end_line = _safe_int(args.get("end_line"), start_line + chunk_size - 1)

            if purpose == "forward_scan":
                expected_start, expected_end = next_forward_span(
                    max_forward_line, max_line, chunk_size
                )
                if start_line > expected_start:
                    start_line = expected_start
                    end_line = expected_end
                elif end_line < start_line:
                    end_line = min(max_line, start_line + chunk_size - 1)

            span = read_transcript_span(
                db_path=db_path,
                transcript_id=transcript_id,
                start_line=start_line,
                end_line=end_line,
                purpose=purpose,
            )
            new_progress = update_forward_progress(
                max_forward_line,
                purpose=purpose,
                end_line=int(span["end_line"]),
                max_line=max_line,
            )
            return (
                {
                    "output": span,
                    "progress": {
                        "max_forward_line": new_progress,
                        "max_line": max_line,
                    },
                },
                new_progress,
            )

        if name == "update_issue":
            purpose = str(args.get("purpose") or "candidate_refine")
            if purpose not in READ_PURPOSES:
                purpose = "candidate_refine"
            issue = upsert_issue(
                db_path=db_path,
                transcript_id=transcript_id,
                issue_id=str(args.get("issue_id") or ""),
                issue_key=str(args.get("issue_key") or ""),
                title=str(args.get("title") or ""),
                status=str(args.get("status") or "open"),
                importance=_safe_float(args.get("importance"), 0.5),
                summary=str(args.get("summary") or ""),
            )
            mention_ids: list[int] = []
            for line_id in _safe_int_list(args.get("line_ids", [])):
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
            return {"output": {"issue": issue, "mention_ids": mention_ids}}, max_forward_line

        if name == "create_l1_object":
            raw_object = {
                "type": str(args.get("type") or "decision"),
                "content": str(args.get("content") or "").strip(),
                "importance": _safe_float(args.get("importance"), 0.5),
                "evidence": str(args.get("evidence") or "").strip(),
                "related_topics": _safe_str_list(args.get("related_topics", [])),
            }
            obj_id = save_l1_object(
                db_path=db_path,
                transcript_id=transcript_id,
                issue_id=str(args.get("issue_id") or ""),
                row=raw_object,
            )
            return {"output": {"obj_id": obj_id, "object": raw_object}}, max_forward_line

        return {"error": f"Unknown tool: {name}"}, max_forward_line
    except Exception as exc:
        return {"error": str(exc)}, max_forward_line


def _format_known_issues(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return "(none)"
    lines: list[str] = []
    for issue in issues[:12]:
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
) -> str:
    start, end = next_forward_span(max_forward_line, max_line, chunk_size)
    return (
        "Continue the top-down scan. "
        f"The next unread forward_scan span should start at line {start} "
        f"and may end around line {end}. Do not stop until line {max_line} is processed.\n\n"
        "Known issues in this transcript. Reuse issue_id/issue_key if the new span returns to the same issue:\n"
        f"{_format_known_issues(known_issues)}"
    )


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
    config = _build_config(
        transcript_id=transcript_id,
        existing_topics=existing_topics,
        chunk_size=chunk_size,
    )
    contents: list[types.Content] = [
        types.Content(
            role="user",
            parts=[
                types.Part(text=_build_initial_prompt(transcript_id, max_line, chunk_size))
            ],
        )
    ]

    max_forward_line = 0
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
        )
        function_calls = _extract_function_calls(response)
        model_content = _model_content(response)

        if function_calls:
            if model_content is not None:
                contents.append(model_content)
            response_parts: list[types.Part] = []
            summaries: list[str] = []
            for function_call in function_calls:
                previous_forward_line = max_forward_line
                payload, max_forward_line = _execute_tool_call(
                    db_path=db_path,
                    transcript_id=transcript_id,
                    function_call=function_call,
                    max_line=max_line,
                    max_forward_line=max_forward_line,
                    chunk_size=chunk_size,
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

    if not should_stop(max_forward_line, max_line):
        raise RuntimeError(
            "Incremental extraction stopped before the final transcript line "
            f"({max_forward_line}/{max_line}) after {max_tool_rounds} tool rounds. "
            "Re-run with a larger --chunk-size or --max-tool-rounds."
        )

    raw_objects = load_l1_objects(db_path, transcript_id)
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
