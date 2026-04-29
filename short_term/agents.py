from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

try:
    from .genai_retry import call_with_retry
    from .graph_state import action_item_index, memory_summary, transcript_items_text
    from .memory_tools import (
        AgentToolContext,
        read_short_term_memory_tool,
        write_memory_candidate_tool,
    )
    from .research_logger import ResearchLogger, elapsed, timed
except ImportError:  # pragma: no cover - script execution fallback
    from genai_retry import call_with_retry
    from graph_state import action_item_index, memory_summary, transcript_items_text
    from memory_tools import (
        AgentToolContext,
        read_short_term_memory_tool,
        write_memory_candidate_tool,
    )
    from research_logger import ResearchLogger, elapsed, timed


PROMPT_VERSION = "short-term-langgraph-v1"
DEFAULT_TEMPERATURE = 0.1

COMMON_RULES = """
你是 Virtual Mentor short-term memory pipeline 的受限子代理。
你不能直接更新 official memory，不能輸出完整 memory。
若可使用工具，需要讀 current memory 時只能呼叫 read_short_term_memory。
若要提出記憶候選，必須呼叫 write_memory_candidate 寫入 staging DB；最後 JSON 只作為 summary。
evidence_lines/evidence_quote 用於 research log/debug，盡量填寫，但不是所有候選的硬性判斷條件。
你必須逐一處理輸入中的所有 idea units；不能因為資訊不完整就忽略，應使用 no_op 或 uncertainty 說明。
不得臆測 owner、status、priority、決策結果；不確定時填 unknown 或輸出 uncertainty。
不得改寫未被要求負責的 section。
輸出必須是 JSON only。
""".strip()


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
        max_tool_rounds: int = 3,
    ) -> AgentRunResult:
        started = timed()
        raw_text = ""
        parsed: dict[str, Any] | None = None
        errors: list[str] = []
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
                )
            raw_text = response.text or ""
            parsed = extract_json(raw_text, parsed=getattr(response, "parsed", None))
            token_usage = _usage_metadata(response)
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
    ) -> Any:
        def read_short_term_memory(
            section: str = "overview",
            offset: int = 0,
            limit: int = 50,
            ids: list[str] | None = None,
        ) -> dict[str, Any]:
            """Read official short-term memory from SQLite for this agent.

            Args:
                section: Allowed memory section name.
                offset: Page offset for list sections.
                limit: Maximum rows to return.
                ids: Optional IDs to filter the returned rows.
            """
            return read_short_term_memory_tool(
                tool_context,
                section=section,
                offset=offset,
                limit=limit,
                ids=ids,
            )

        def write_memory_candidate(
            operation: str,
            target_section: str,
            candidate_payload: dict[str, Any],
            target_id: str = "",
            confidence: float = 0.0,
            note: str = "",
            evidence_lines: list[int] | None = None,
            evidence_quote: str = "",
        ) -> dict[str, Any]:
            """Write one memory candidate into staging, not official memory.

            Args:
                operation: create, update, close, replace, or no_op.
                target_section: The memory section this candidate belongs to.
                candidate_payload: Section-specific payload object.
                target_id: Existing target ID for update/close/replace.
                confidence: Model confidence from 0 to 1.
                note: Short debug note.
                evidence_lines: Transcript line numbers for research logging.
                evidence_quote: Short evidence quote for research logging.
            """
            return write_memory_candidate_tool(
                tool_context,
                operation=operation,
                target_section=target_section,
                target_id=target_id,
                candidate_payload=candidate_payload,
                confidence=confidence,
                note=note,
                evidence_lines=evidence_lines,
                evidence_quote=evidence_quote,
            )

        config = types.GenerateContentConfig(
            system_instruction=(
                "你是受限子代理。需要 current memory 時只能呼叫 read_short_term_memory；"
                "提出候選時必須呼叫 write_memory_candidate 寫入 staging。"
                "最後仍必須回傳符合 response schema 的 JSON summary。"
            ),
            temperature=self.temperature,
            response_mime_type="application/json",
            response_json_schema=self.schema,
            tools=[
                read_short_term_memory,
                write_memory_candidate,
            ],
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

        for round_index in range(1, max_tool_rounds + 1):
            function_calls = list(getattr(response, "function_calls", None) or [])
            if not function_calls:
                return response

            parts: list[types.Part] = []
            for function_call in function_calls:
                tool_name = function_call.name or ""
                args = dict(function_call.args or {})
                tool_start = timed()
                error = ""
                try:
                    if tool_name == "read_short_term_memory":
                        result = read_short_term_memory(**args)
                    elif tool_name == "write_memory_candidate":
                        result = write_memory_candidate(**args)
                    else:
                        result = {"ok": False, "error": f"Unknown tool: {tool_name}"}
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)
                    result = {"ok": False, "error": error}

                logger.tool_call(
                    agent_name=self.name,
                    tool_name=tool_name,
                    args_summary=_summarize_tool_args(args),
                    result_summary=_summarize_tool_result(result),
                    latency_seconds=elapsed(tool_start),
                    error=error,
                )
                parts.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response=result,
                    )
                )

            response = call_with_retry(
                lambda: chat.send_message(parts),
                operation_name=f"{self.name} tool send_message round {round_index}",
                on_retry=retry_events.append,
            )

        return response


class ShortTermAgentSuite:
    def __init__(self, client: genai.Client, model_name: str) -> None:
        self.context_planner = GeminiJsonAgent(
            name="context_planner",
            client=client,
            model_name=model_name,
            schema=CONTEXT_PLANNER_SCHEMA,
        )
        self.segment = GeminiJsonAgent(
            name="segment_agent",
            client=client,
            model_name=model_name,
            schema=SEGMENT_SCHEMA,
        )
        self.meeting = GeminiJsonAgent(
            name="meeting_summary_agent",
            client=client,
            model_name=model_name,
            schema=MEETING_SCHEMA,
        )
        self.action = GeminiJsonAgent(
            name="action_item_agent",
            client=client,
            model_name=model_name,
            schema=ACTION_SCHEMA,
        )
        self.method = GeminiJsonAgent(
            name="method_change_agent",
            client=client,
            model_name=model_name,
            schema=METHOD_SCHEMA,
        )
        self.experiment = GeminiJsonAgent(
            name="experiment_todo_agent",
            client=client,
            model_name=model_name,
            schema=EXPERIMENT_SCHEMA,
        )
        self.focus = GeminiJsonAgent(
            name="next_focus_agent",
            client=client,
            model_name=model_name,
            schema=FOCUS_SCHEMA,
        )


def build_context_planner_prompt(state: dict[str, Any]) -> str:
    processed = int(state.get("processed_until_line", 0) or 0)
    return f"""
{COMMON_RULES}

你只負責規劃下一次讀取範圍，不抽取記憶。
若上一段開頭像延續前文，要求 lookback。
若上一段結尾句意未完、討論正在轉折、有人提出問題但尚未回答，要求 lookahead。
不要為了抽取方便要求過大範圍。

限制：
- forward window 建議 {state.get('chunk_size', 80)} 行。
- lookback_lines 不得超過 {state.get('max_lookback_lines', 20)}。
- lookahead_lines 不得超過 {state.get('max_lookahead_lines', 40)}。
- start_line 必須從 processed_until_line + 1 開始，除非正在補上下文。

Meeting:
- meeting_id: {state.get('meeting_id')}
- total_lines: {state.get('transcript_line_count')}
- processed_until_line: {processed}

Transcript overview:
{json.dumps(state.get('transcript_overview', {}), ensure_ascii=False, indent=2)}

Current memory summary:
{json.dumps(memory_summary(state.get('current_memory', {})), ensure_ascii=False, indent=2)}

Planner history:
{json.dumps(state.get('planner_history', [])[-5:], ensure_ascii=False, indent=2)}
""".strip()


def build_segment_prompt(state: dict[str, Any]) -> str:
    window = state.get("current_window", {})
    items = window.get("items", []) if isinstance(window, dict) else []
    return f"""
{COMMON_RULES}

你只負責把 transcript window 切成完整 idea units，不抽取記憶。
如果一個 topic 尚未講完，needs_more_context 必須為 true。
line_start/line_end 必須落在提供的 transcript lines 內。
不要因為 topic 看似瑣碎就省略；所有可能影響 meeting summary、action item、method change、experiment todo、next focus 的對話都要切成 unit。
kind_hint 可包含多個可能 section；不確定時保守加入可能的 hint，讓後續 agent 判斷。

Window:
{json.dumps(_window_summary(window), ensure_ascii=False, indent=2)}

Transcript lines:
{transcript_items_text(items)}
""".strip()


def build_extraction_prompt(
    *,
    agent_kind: str,
    state: dict[str, Any],
    instructions: str,
) -> str:
    window = state.get("current_window", {})
    items = window.get("items", []) if isinstance(window, dict) else []
    return f"""
{COMMON_RULES}

Agent responsibility:
{instructions}

Tool rules:
- 需要 current memory 時呼叫 read_short_term_memory。
- 產生候選時呼叫 write_memory_candidate 寫入 staging；不要只把候選放在最後 JSON。
- write_memory_candidate 必須包含 operation、target_section、candidate_payload、confidence、note。
- update/close/replace 必須填 target_id；create 可留空 target_id。
- evidence_lines/evidence_quote 請盡量填，供 research log/debug 使用。
- 你必須逐一檢查 Accepted idea units。若某個 unit 與你的責任無關，可以不寫候選；若相關但不應更新，請用 operation=no_op 寫入 staging 並在 note 說明原因。
- 若需要比對既有項目，必須先 read_short_term_memory 讀你的 section，再決定 create/update/close/replace/no_op。
- 不要只因欄位不完整就跳過：可用 unknown、空陣列或 no_op 表達不確定，但要讓 log 看得出你處理過。
- 最後 JSON summary 必須反映已寫入 staging 的候選；不要在 JSON 中新增未透過 tool 寫入的候選。

Meeting metadata:
- meeting_id: {state.get('meeting_id')}
- source_file: {state.get('source_file')}

Current memory summary:
{json.dumps(memory_summary(state.get('current_memory', {})), ensure_ascii=False, indent=2)}

Current action item index:
{json.dumps(action_item_index(state.get('current_memory', {})), ensure_ascii=False, indent=2)}

Accepted idea units:
{json.dumps(state.get('current_units', []), ensure_ascii=False, indent=2)}

Transcript lines:
{transcript_items_text(items)}

輸出只能包含 {agent_kind} schema 負責的欄位。沒有明確 create/update/close/replace 時，若有相關但不更新的 unit，仍應先用 write_memory_candidate 寫 no_op staging candidate；最後 JSON 可回傳空陣列或 summary。
""".strip()


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
    summary: dict[str, Any] = {
        "ok": bool(result.get("ok")),
    }
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


def _window_summary(window: Any) -> dict[str, Any]:
    if not isinstance(window, dict):
        return {}
    return {
        "context_start_line": window.get("context_start_line"),
        "context_end_line": window.get("context_end_line"),
        "forward_start_line": window.get("forward_start_line"),
        "forward_end_line": window.get("forward_end_line"),
        "returned_count": len(window.get("items", [])),
    }


CONTEXT_PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"},
        "lookback_lines": {"type": "integer"},
        "lookahead_lines": {"type": "integer"},
        "reason": {"type": "string"},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": [
        "start_line",
        "end_line",
        "lookback_lines",
        "lookahead_lines",
        "reason",
        "risk",
    ],
    "additionalProperties": False,
}

SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "topic": {"type": "string"},
                    "kind_hint": {"type": "array", "items": {"type": "string"}},
                    "needs_more_context": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": [
                    "unit_id",
                    "line_start",
                    "line_end",
                    "topic",
                    "kind_hint",
                    "needs_more_context",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["units"],
    "additionalProperties": False,
}

MEETING_SCHEMA = {
    "type": "object",
    "properties": {
        "meeting_window": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "string"},
                    "source_file": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "open_questions": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "meeting_id",
                    "source_file",
                    "summary",
                    "key_points",
                    "open_questions",
                    "evidence",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["meeting_window"],
    "additionalProperties": False,
}

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "proposer": {"type": "string"},
                    "owner": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["open", "in_progress", "completed", "cancelled"],
                    },
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": ["create", "update", "close", "no_op"],
                    },
                    "confidence": {"type": "number"},
                },
                "required": [
                    "item_id",
                    "title",
                    "detail",
                    "proposer",
                    "owner",
                    "status",
                    "priority",
                    "dependencies",
                    "evidence",
                    "operation",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["action_items"],
    "additionalProperties": False,
}

METHOD_SCHEMA = {
    "type": "object",
    "properties": {
        "method_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "change_id": {"type": "string"},
                    "topic": {"type": "string"},
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                    "reason": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "reverted", "superseded"],
                    },
                    "evidence": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": ["create", "update", "no_op"],
                    },
                    "confidence": {"type": "number"},
                },
                "required": [
                    "change_id",
                    "topic",
                    "before",
                    "after",
                    "reason",
                    "status",
                    "evidence",
                    "operation",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["method_changes"],
    "additionalProperties": False,
}

EXPERIMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "experiment_todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["open", "in_progress", "completed", "blocked"],
                    },
                    "owner": {"type": "string"},
                    "related_action_item_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "evidence": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": ["create", "update", "close", "no_op"],
                    },
                    "confidence": {"type": "number"},
                },
                "required": [
                    "todo_id",
                    "description",
                    "status",
                    "owner",
                    "related_action_item_ids",
                    "evidence",
                    "operation",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["experiment_todos"],
    "additionalProperties": False,
}

FOCUS_SCHEMA = {
    "type": "object",
    "properties": {
        "next_meeting_focus": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["text", "evidence", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["next_meeting_focus"],
    "additionalProperties": False,
}
