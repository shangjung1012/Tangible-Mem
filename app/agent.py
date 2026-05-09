from __future__ import annotations

from collections.abc import Callable
import json
import random
import time
from typing import Any

from google import genai
from google.genai import errors
from google.genai import types

from config import MODEL_NAME, SYSTEM_PROMPT
from tools.memory_tools import (
    get_memory_context,
    get_long_term_memory_context,
    get_short_term_memory_context,
)


class MeetingQAAgent:
    """Chat agent with Gemini function-calling for meeting memory retrieval."""

    def __init__(
        self,
        client: genai.Client,
        model_name: str = MODEL_NAME,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.25,
        max_retries: int = 4,
    ) -> None:
        self.model_name = model_name
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_retries = max(1, max_retries)
        self.client = client
        self._tools: dict[str, Callable[..., Any]] = {
            "get_memory_context": get_memory_context,
            "get_short_term_memory_context": get_short_term_memory_context,
            "get_long_term_memory_context": get_long_term_memory_context,
        }
        self.chat = self._build_chat()

    def _build_chat(self) -> genai.chats.Chat:
        config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=self.temperature,
            tools=list(self._tools.values()),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="AUTO",
                )
            ),
        )
        return self.client.chats.create(model=self.model_name, config=config)

    def _is_transient_error(self, exc: Exception) -> bool:
        if isinstance(exc, errors.ServerError):
            return True
        if isinstance(exc, errors.ClientError):
            status = getattr(exc, "status", None)
            msg = str(exc)
            if status in (429, 503):
                return True
            if "429" in msg or "503" in msg or "UNAVAILABLE" in msg:
                return True
        return False

    def _send_message_with_retry(
        self,
        message: str | list[types.Part],
        config: types.GenerateContentConfig | None = None,
    ) -> types.GenerateContentResponse:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self.chat.send_message(message, config=config)
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries or not self._is_transient_error(exc):
                    raise
                delay = min(10.0, 1.1 * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
                print(
                    f"\n[Retry] transient API error (attempt {attempt}/{self.max_retries}), "
                    f"waiting {delay:.1f}s..."
                )
                time.sleep(delay)
        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected retry flow.")

    def ask(self, user_text: str) -> str:
        response = self._send_message_with_retry(user_text)

        max_tool_rounds = 4
        seen_calls: set[str] = set()
        tool_result_log: list[dict[str, Any]] = []
        for _ in range(max_tool_rounds):
            function_calls = list(response.function_calls or [])
            if not function_calls:
                break

            response_parts: list[types.Part] = []
            repeated_only = True
            for function_call in function_calls:
                tool_name = function_call.name or ""
                tool = self._tools.get(tool_name)
                args = function_call.args or {}
                signature = f"{tool_name}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
                if signature not in seen_calls:
                    repeated_only = False
                seen_calls.add(signature)

                if tool is None:
                    tool_result: dict[str, Any] = {
                        "error": f"Unknown tool: {tool_name}"
                    }
                else:
                    try:
                        tool_output = tool(**args)
                        tool_result = (
                            tool_output
                            if isinstance(tool_output, dict)
                            else {"result": str(tool_output)}
                        )
                    except Exception as exc:
                        tool_result = {"error": str(exc)}
                tool_result_log.append(
                    {
                        "tool": tool_name,
                        "args": args,
                        "result": tool_result,
                    }
                )

                response_parts.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response=tool_result,
                    )
                )

            if repeated_only:
                break
            response = self._send_message_with_retry(response_parts)

        final_text = (response.text or "").strip()
        if final_text:
            return final_text

        # Fallback: force final answer without additional tool calls.
        tool_lines: list[str] = []
        for index, row in enumerate(tool_result_log, start=1):
            tool_lines.append(
                f"[{index}] tool={row['tool']} args={json.dumps(row['args'], ensure_ascii=False)}"
            )
            result_text = json.dumps(row["result"], ensure_ascii=False)
            if len(result_text) > 1500:
                result_text = result_text[:1500] + "...(truncated)"
            tool_lines.append(result_text)
        tool_summary = "\n".join(tool_lines) if tool_lines else "（無工具結果）"

        final_prompt = (
            "請根據以下工具結果直接回答使用者問題，不要再呼叫任何工具。\n"
            f"使用者問題：{user_text}\n"
            f"工具結果：\n{tool_summary}"
        )
        final_config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=self.temperature,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE")
            ),
        )
        final_response = self._send_message_with_retry(final_prompt, config=final_config)
        final_text = (final_response.text or "").strip()
        if final_text:
            return final_text
        return "目前沒有可用回覆，請換個問法再試一次。"
