from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from google import genai
from google.genai import errors, types

from normalizer import normalize_memory
from schema import RESPONSE_JSON_SCHEMA, SCHEMA_DESCRIPTION

MAX_GENERATION_ATTEMPTS = 3
MAX_TOOL_ROUNDS = 6
MAX_API_RETRIES = 5
API_RETRY_BASE_DELAY_SECONDS = 2.0
API_RETRY_MAX_DELAY_SECONDS = 20.0


def build_tool_call_prompt(
    transcript: str,
    meeting_id: str,
    source_file: str,
) -> str:
    return f"""
你是一個「短期記憶 SQLite 更新器」。
你必須使用工具完成更新，而不是直接在文字回覆最終 JSON。

任務流程（必須遵守）：
1) 先呼叫 `read_short_term_memory` 取得目前記憶。
2) 根據逐字稿整理更新內容。
3) 呼叫一次 `write_short_term_memory`，把更新內容放進 `updated_memory`。
4) `write_short_term_memory` 之後只做簡短確認，不要再呼叫任何工具。

更新規則：
- 盡量保留既有 item_id / change_id / todo_id，不要無故改號。
- 新增項目才新增新 id。
- 若逐字稿顯示完成/取消/方法修正，更新 status 或 method_changes。
- evidence 優先寫逐字稿中的短證據句。
- 若無法確定 owner / proposer，填 unknown。
- 文字欄位請優先繁體中文。
- 系統會在本地維護 meeting_history_ids，並裁切 meeting_window 成最近三次；你只要提供合理更新即可。

Schema 說明（欄位參考）：
{json.dumps(SCHEMA_DESCRIPTION, ensure_ascii=False, indent=2)}

Current meeting metadata:
- meeting_id: {meeting_id}
- source_file: {source_file}

Transcript:
{transcript}
""".strip()


def build_structured_prompt(
    transcript: str,
    current_memory: dict[str, Any],
    meeting_id: str,
    source_file: str,
) -> str:
    return f"""
你是一個「短期記憶更新器」。
任務：根據單次會議逐字稿，更新 short-term memory。

你必須遵守：
1) 回傳 JSON only，不要有任何額外文字。
2) JSON 結構固定，欄位名稱與型態必須符合 schema。
3) 必須保留舊記憶資訊，僅新增/更新，不能任意刪除未完成項目。
4) meeting_window 不需要負責刪除舊會議；請至少正確提供目前會議的摘要，最近三次的裁切會由系統在本地完成。
5) action_items 要盡量維持 item_id 一致；新項目才新增新 id。系統會在本地只保留最近三次會議範圍內建立或更新過的 action items。
6) 若逐字稿有完成/取消/方法修正跡象，要更新 status 或 method_changes。
7) 能從逐字稿抓到證據時，寫在 evidence 欄位（短句即可）。
8) memory_version 應該是 current_memory.memory_version + 1。
9) 文字欄位請優先使用繁體中文。
10) 若無法確定 owner / proposer，請填 unknown，不要臆測。
11) `meeting_history_ids` 是系統在本地維護的順序欄位；如果你輸出它，請原樣保留 current_memory 的值，不要自行推測或重建。

Schema:
{json.dumps(SCHEMA_DESCRIPTION, ensure_ascii=False, indent=2)}

Current memory JSON:
{json.dumps(current_memory, ensure_ascii=False, indent=2)}

Current meeting metadata:
- meeting_id: {meeting_id}
- source_file: {source_file}

Transcript:
{transcript}
""".strip()


def extract_json(raw_text: str, parsed: Any | None = None) -> dict[str, Any]:
    if isinstance(parsed, dict):
        return parsed

    if hasattr(parsed, "model_dump"):
        dumped = parsed.model_dump()
        if isinstance(dumped, dict):
            return dumped

    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise RuntimeError("Gemini response does not contain valid JSON object.")

    candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse Gemini JSON output.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Gemini JSON output must be an object.")
    return data


def save_failed_response(
    meeting_id: str,
    attempt: int,
    raw_text: str,
    suffix: str = "",
) -> Path:
    debug_dir = Path(__file__).resolve().parent / "debug_raw"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix_str = f"_{suffix}" if suffix else ""
    path = debug_dir / f"{timestamp}_{meeting_id}_attempt{attempt}{suffix_str}.txt"
    path.write_text(raw_text or "", encoding="utf-8")
    return path


def _is_retryable_genai_error(exc: Exception) -> bool:
    if isinstance(exc, errors.ServerError):
        return True

    message = str(exc).upper()
    return "503" in message or "UNAVAILABLE" in message


def _call_with_retry(
    func: Callable[[], Any],
    *,
    log: Callable[[str], None],
    operation_name: str,
    max_retries: int = MAX_API_RETRIES,
) -> Any:
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            if not _is_retryable_genai_error(exc) or attempt >= max_retries:
                raise

            delay_seconds = min(
                API_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
                API_RETRY_MAX_DELAY_SECONDS,
            )
            log(
                f"{operation_name} failed with retryable error "
                f"(attempt {attempt}/{max_retries}): {exc}. "
                f"sleep {delay_seconds:.1f}s before retry"
            )
            time.sleep(delay_seconds)


def _generate_structured_update(
    client: genai.Client,
    model_name: str,
    transcript: str,
    current_memory: dict[str, Any],
    meeting_id: str,
    source_file: str,
    log: Callable[[str], None],
) -> dict[str, Any]:
    prompt = build_structured_prompt(
        transcript=transcript,
        current_memory=current_memory,
        meeting_id=meeting_id,
        source_file=source_file,
    )
    response = _call_with_retry(
        lambda: client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "temperature": 0.0,
                "response_mime_type": "application/json",
                "response_json_schema": RESPONSE_JSON_SCHEMA,
            },
        ),
        log=log,
        operation_name="structured generate_content",
    )
    return extract_json(response.text or "", parsed=getattr(response, "parsed", None))


def generate_updated_memory(
    model_name: str,
    api_key: str,
    transcript: str,
    current_memory: dict[str, Any],
    meeting_id: str,
    source_file: str,
    on_memory_read: Callable[[], dict[str, Any]] | None = None,
    on_memory_write: Callable[[dict[str, Any]], None] | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    def log(message: str) -> None:
        if verbose:
            print(f"[llm_update] {message}", flush=True)

    client = genai.Client(api_key=api_key)
    prompt = build_tool_call_prompt(
        transcript=transcript,
        meeting_id=meeting_id,
        source_file=source_file,
    )
    log(
        f"start model={model_name} meeting_id={meeting_id} "
        f"memory_version={int(current_memory.get('memory_version', 0) or 0)}"
    )

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        log(f"attempt {attempt}/{MAX_GENERATION_ATTEMPTS}: creating tool-calling chat")
        state: dict[str, Any] = {
            "base_memory": current_memory,
            "latest_memory": current_memory,
            "write_done": False,
            "written_memory": None,
        }

        def read_short_term_memory() -> dict[str, Any]:
            """Read current short-term memory snapshot from SQLite-backed storage."""
            memory = on_memory_read() if on_memory_read is not None else state["latest_memory"]
            state["latest_memory"] = memory
            return {
                "memory": memory,
                "summary": {
                    "memory_version": int(memory.get("memory_version", 0) or 0),
                    "meeting_history_count": len(memory.get("meeting_history_ids", [])),
                    "meeting_window_count": len(memory.get("meeting_window", [])),
                    "action_items_count": len(memory.get("action_items", [])),
                    "method_changes_count": len(memory.get("method_changes", [])),
                    "experiment_todos_count": len(memory.get("experiment_todos", [])),
                },
            }

        def write_short_term_memory(
            updated_memory: dict[str, Any],
            note: str = "",
        ) -> dict[str, Any]:
            """
            Persist one memory update patch.

            Args:
                updated_memory: Partial or full memory object following the short-term schema.
                note: Optional explanation for this write.
            """
            if state["write_done"]:
                return {
                    "ok": False,
                    "error": "write_short_term_memory can only be called once per update run.",
                }

            if not isinstance(updated_memory, dict):
                return {
                    "ok": False,
                    "error": "updated_memory must be a JSON object.",
                }

            normalized = normalize_memory(
                updated_memory=updated_memory,
                previous_memory=state["base_memory"],
                meeting_id=meeting_id,
                source_file=source_file,
            )
            log(
                "tool write_short_term_memory normalized "
                f"memory_version={normalized['memory_version']} "
                f"meeting_window={len(normalized.get('meeting_window', []))} "
                f"action_items={len(normalized.get('action_items', []))}"
            )

            if on_memory_write is not None:
                log("tool write_short_term_memory persisting to storage")
                on_memory_write(normalized)

            persisted_memory = on_memory_read() if on_memory_read is not None else normalized
            state["latest_memory"] = persisted_memory
            state["written_memory"] = persisted_memory
            state["write_done"] = True

            return {
                "ok": True,
                "note": note,
                "memory_version": persisted_memory["memory_version"],
                "last_updated_meeting_id": persisted_memory["last_updated_meeting_id"],
                "meeting_window_ids": [
                    row.get("meeting_id", "")
                    for row in persisted_memory.get("meeting_window", [])
                ],
                "action_items_count": len(persisted_memory.get("action_items", [])),
            }

        config = types.GenerateContentConfig(
            system_instruction="你是嚴謹的短期記憶維護助手，必須先讀後寫，並只呼叫必要工具。",
            temperature=0.1,
            tools=[read_short_term_memory, write_short_term_memory],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")
            ),
        )

        chat = client.chats.create(model=model_name, config=config)
        log("sending initial prompt to Gemini")
        response = _call_with_retry(
            lambda: chat.send_message(prompt),
            log=log,
            operation_name="tool-calling send_message initial",
        )

        seen_calls: set[str] = set()
        for round_index in range(1, MAX_TOOL_ROUNDS + 1):
            function_calls = list(response.function_calls or [])
            if not function_calls:
                log(f"round {round_index}: no tool call returned")
                break

            parts: list[types.Part] = []
            repeated_only = True
            log(f"round {round_index}: {len(function_calls)} tool call(s)")
            for function_call in function_calls:
                tool_name = function_call.name or ""
                args = function_call.args or {}
                log(
                    f"round {round_index}: invoking tool={tool_name} "
                    f"args_keys={sorted(args.keys())}"
                )
                signature = f"{tool_name}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
                if signature not in seen_calls:
                    repeated_only = False
                seen_calls.add(signature)

                if tool_name == "read_short_term_memory":
                    tool_result = read_short_term_memory()
                elif tool_name == "write_short_term_memory":
                    try:
                        tool_result = write_short_term_memory(**args)
                    except TypeError as exc:
                        tool_result = {
                            "ok": False,
                            "error": f"Invalid tool args for write_short_term_memory: {exc}",
                        }
                else:
                    tool_result = {"ok": False, "error": f"Unknown tool: {tool_name}"}

                parts.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response=tool_result,
                    )
                )

            if repeated_only:
                log(f"round {round_index}: repeated tool signatures only, stop tool loop")
                break
            log(f"round {round_index}: sending tool responses back to Gemini")
            response = _call_with_retry(
                lambda: chat.send_message(parts),
                log=log,
                operation_name=f"tool-calling send_message round {round_index}",
            )

        written_memory = state.get("written_memory")
        if isinstance(written_memory, dict):
            log(
                "tool-calling update finished successfully "
                f"memory_version={written_memory['memory_version']}"
            )
            return written_memory

        raw_text = response.text or ""
        debug_path = save_failed_response(
            meeting_id=meeting_id,
            attempt=attempt,
            raw_text=raw_text,
            suffix="tool_call_no_write",
        )
        log(
            "tool-calling did not produce write call, "
            f"fallback to structured JSON mode (debug={debug_path})"
        )

        try:
            structured_update = _generate_structured_update(
                client=client,
                model_name=model_name,
                transcript=transcript,
                current_memory=current_memory,
                meeting_id=meeting_id,
                source_file=source_file,
                log=log,
            )
            normalized = normalize_memory(
                updated_memory=structured_update,
                previous_memory=current_memory,
                meeting_id=meeting_id,
                source_file=source_file,
            )
            if on_memory_write is not None:
                log("structured fallback persisting to storage")
                on_memory_write(normalized)
                normalized = (
                    on_memory_read() if on_memory_read is not None else normalized
                )
            log(
                "structured fallback succeeded "
                f"memory_version={normalized['memory_version']}"
            )
            return normalized
        except Exception as exc:  # noqa: BLE001
            log(f"structured fallback failed on attempt {attempt}: {exc}")
            if attempt >= MAX_GENERATION_ATTEMPTS:
                raise RuntimeError(
                    "Failed to update memory via tool calling and structured fallback. "
                    f"Last tool-response debug file: {debug_path}"
                ) from exc

    raise RuntimeError("Unreachable: generation attempts exhausted unexpectedly.")
