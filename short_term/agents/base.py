from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

try:
    from ..runtime.genai_retry import call_with_retry
    from ..storage.memory_tools import (
        AgentToolContext,
        read_short_term_memory_tool,
    )
    from ..runtime.research_logger import ResearchLogger, elapsed, timed
except ImportError:  # pragma: no cover - script execution fallback
    from short_term.runtime.genai_retry import call_with_retry
    from short_term.storage.memory_tools import (
        AgentToolContext,
        read_short_term_memory_tool,
    )
    from short_term.runtime.research_logger import ResearchLogger, elapsed, timed

from .prompts import DEFAULT_TEMPERATURE, PROMPT_VERSION

MAX_FUNCTION_CALLS_PER_RESPONSE = 40
MAX_FUNCTION_CALLS_PER_AGENT_RUN = 120
MAX_TOOL_ROUNDS_PER_AGENT_RUN = 12
MAX_EMPTY_RESPONSE_RETRIES = 2


@dataclass(slots=True)
class AgentRunResult:
    agent_name: str
    parsed: dict[str, Any]
    raw_text: str
    errors: list[str]


class GeminiJsonAgent:
    def __init__(
        self,
        *,
        name: str,
        client: genai.Client,
        model_name: str,
        schema: dict[str, Any],
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        self.name = name
        self.client = client
        self.model_name = model_name
        self.schema = schema
        self.temperature = temperature

    def run(
        self,
        *,
        prompt: str,
        logger: ResearchLogger,
        input_summary: dict[str, Any],
        tool_context: AgentToolContext | None = None,
        max_tool_rounds: int = MAX_TOOL_ROUNDS_PER_AGENT_RUN,
    ) -> AgentRunResult:
        started = timed()
        raw_text = ""
        parsed: dict[str, Any] | None = None
        errors: list[str] = []
        tool_errors: list[str] = []
        retry_events: list[dict[str, Any]] = []

        def invoke_plain() -> Any:
            return self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={
                    "temperature": self.temperature,
                    "response_mime_type": "application/json",
                    "response_json_schema": self.schema,
                },
            )

        try:
            if tool_context is None:
                response = call_with_retry(
                    invoke_plain,
                    operation_name=f"{self.name} generate_content",
                    on_retry=retry_events.append,
                )
            else:
                response = self._run_with_tools(
                    prompt=prompt,
                    logger=logger,
                    tool_context=tool_context,
                    max_tool_rounds=max_tool_rounds,
                    retry_events=retry_events,
                    tool_errors=tool_errors,
                )
            token_usage = _usage_metadata(response)
            raw_text = _response_text(response)
            unresolved_calls = _function_call_names(response)
            if unresolved_calls:
                errors.append(
                    "LLM response still contained unresolved function calls after "
                    f"max_tool_rounds={max_tool_rounds}: "
                    + ", ".join(unresolved_calls)
                )
            else:
                parsed = extract_json(raw_text, parsed=getattr(response, "parsed", None))
            errors.extend(tool_errors)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            token_usage = {}

        logger.agent_call(
            agent_name=self.name,
            prompt_version=PROMPT_VERSION,
            model_name=self.model_name,
            temperature=self.temperature,
            input_summary=input_summary,
            prompt=prompt,
            raw_response=raw_text,
            parsed=parsed,
            errors=errors,
            retry_count=len(retry_events),
            retry_events=retry_events,
            latency_seconds=elapsed(started),
            token_usage=token_usage,
        )
        return AgentRunResult(
            agent_name=self.name,
            parsed=parsed or {},
            raw_text=raw_text,
            errors=errors,
        )

    def _run_with_tools(
        self,
        *,
        prompt: str,
        logger: ResearchLogger,
        tool_context: AgentToolContext,
        max_tool_rounds: int,
        retry_events: list[dict[str, Any]],
        tool_errors: list[str],
    ) -> Any:
        def read_short_term_memory(
            section: str = "overview",
            offset: int = 0,
            limit: int = 50,
            ids: list[str] | None = None,
        ) -> dict[str, Any]:
            return read_short_term_memory_tool(
                tool_context,
                section=section,
                offset=offset,
                limit=limit,
                ids=ids,
            )

        config = types.GenerateContentConfig(
            system_instruction=(
                "你是受限子代理。需要 current memory 時只能呼叫 read_short_term_memory；"
                "不得呼叫任何寫入工具。候選必須完整放在最後 JSON response 中，"
                "後續 deterministic verifier/reducer/normalizer 才能決定是否寫入 DB。"
            ),
            temperature=self.temperature,
            response_mime_type="application/json",
            response_json_schema=self.schema,
            tools=[read_short_term_memory],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")
            ),
        )
        chat = self.client.chats.create(model=self.model_name, config=config)
        response = call_with_retry(
            lambda: chat.send_message(prompt),
            operation_name=f"{self.name} tool send_message initial",
            on_retry=retry_events.append,
        )

        total_function_calls = 0
        empty_response_retries = 0
        for round_index in range(1, max_tool_rounds + 1):
            function_calls = list(getattr(response, "function_calls", None) or [])
            if not function_calls:
                if _response_text(response).strip() or _has_parsed_json_object(response):
                    return response
                if empty_response_retries >= MAX_EMPTY_RESPONSE_RETRIES:
                    return response
                empty_response_retries += 1
                retry_events.append(
                    {
                        "operation_name": f"{self.name} tool final JSON repair",
                        "attempt": empty_response_retries,
                        "max_retries": MAX_EMPTY_RESPONSE_RETRIES,
                        "delay_seconds": 0.0,
                        "error_type": "EmptyModelResponse",
                        "error": "LLM returned an empty final response after tool use.",
                    }
                )
                response = call_with_retry(
                    lambda: chat.send_message(
                        "Previous response was empty. Return only the final JSON "
                        "object matching the response schema. If there is no update "
                        "for this section, return an empty array."
                    ),
                    operation_name=(
                        f"{self.name} tool send_message empty-response repair "
                        f"{empty_response_retries}"
                    ),
                    on_retry=retry_events.append,
                )
                continue
            empty_response_retries = 0
            if len(function_calls) > MAX_FUNCTION_CALLS_PER_RESPONSE:
                raise RuntimeError(
                    f"{self.name} requested {len(function_calls)} function calls in "
                    "one response; refusing to execute an uncontrolled tool batch."
                )

            parts: list[types.Part] = []
            for function_call in function_calls:
                if total_function_calls >= MAX_FUNCTION_CALLS_PER_AGENT_RUN:
                    raise RuntimeError(
                        f"{self.name} exceeded {MAX_FUNCTION_CALLS_PER_AGENT_RUN} "
                        "tool calls in one run; refusing to continue."
                    )
                total_function_calls += 1
                tool_name = function_call.name or ""
                args = dict(function_call.args or {})
                tool_start = timed()
                error = ""
                try:
                    if tool_name == "read_short_term_memory":
                        result = read_short_term_memory(**args)
                    else:
                        result = {"ok": False, "error": f"Unknown tool: {tool_name}"}
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)
                    result = {"ok": False, "error": error}
                if isinstance(result, dict) and not result.get("ok", False):
                    tool_errors.append(
                        "Tool call failed "
                        f"agent={self.name} tool={tool_name or 'unknown'} "
                        f"error={result.get('error', 'unknown')}"
                    )

                logger.tool_call(
                    agent_name=self.name,
                    tool_name=tool_name,
                    args_summary=_summarize_tool_args(args),
                    result_summary=_summarize_tool_result(result),
                    latency_seconds=elapsed(tool_start),
                    error=error,
                )
                parts.append(
                    types.Part.from_function_response(name=tool_name, response=result)
                )

            response = call_with_retry(
                lambda: chat.send_message(parts),
                operation_name=f"{self.name} tool send_message round {round_index}",
                on_retry=retry_events.append,
            )

        return response


def flatten_agent_candidates(
    agent_name: str,
    section: str,
    parsed: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = parsed.get(section, [])
    if not isinstance(rows, list):
        return []
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        output.append(
            {
                "agent": agent_name,
                "section": section,
                "candidate_id": f"{agent_name}:{section}:{index}",
                "payload": row,
            }
        )
    return output


def extract_json(raw_text: str, parsed: Any | None = None) -> dict[str, Any]:
    if isinstance(parsed, dict):
        return parsed
    if hasattr(parsed, "model_dump"):
        dumped = parsed.model_dump()
        if isinstance(dumped, dict):
            return dumped
    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("LLM returned an empty response.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("LLM response does not contain a JSON object.")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("LLM JSON output must be an object.")
    return data


def _usage_metadata(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        dumped = usage.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(usage, dict):
        return usage
    return {"raw": str(usage)}


def _function_call_names(response: Any) -> list[str]:
    names: list[str] = []
    for function_call in getattr(response, "function_calls", None) or []:
        name = str(getattr(function_call, "name", "") or "").strip()
        names.append(name or "unknown")
    return names


def _has_parsed_json_object(response: Any) -> bool:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return True
    if hasattr(parsed, "model_dump"):
        return isinstance(parsed.model_dump(), dict)
    return False


def _response_text(response: Any) -> str:
    text_parts: list[str] = []
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            if getattr(part, "function_call", None) is not None:
                continue
            text = getattr(part, "text", None)
            if text:
                text_parts.append(str(text))
    if text_parts:
        return "".join(text_parts)
    if getattr(response, "function_calls", None):
        return ""
    return str(getattr(response, "text", "") or "")


def _summarize_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "section",
        "target_section",
        "operation",
        "target_id",
        "offset",
        "limit",
        "confidence",
    ):
        if key in args:
            summary[key] = args[key]
    payload = args.get("candidate_payload")
    if isinstance(payload, dict):
        summary["candidate_payload_keys"] = sorted(payload.keys())
    evidence_lines = args.get("evidence_lines")
    if isinstance(evidence_lines, list):
        summary["evidence_line_count"] = len(evidence_lines)
    return summary


def _summarize_tool_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"raw": str(result)}
    summary: dict[str, Any] = {"ok": bool(result.get("ok"))}
    for key in (
        "error",
        "section",
        "candidate_id",
        "returned_count",
        "total_count",
        "has_more",
        "warnings",
        "missing_sections",
    ):
        if key in result:
            summary[key] = result[key]
    return summary
