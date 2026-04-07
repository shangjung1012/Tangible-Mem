from __future__ import annotations

from google import genai
from google.genai import types

from config import MODEL_NAME, SYSTEM_PROMPT
from tools.memory_tools import (
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
    ) -> None:
        self.model_name = model_name
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.client = client
        self.chat = self._build_chat()

    def _build_chat(self) -> genai.chats.Chat:
        config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=self.temperature,
            tools=[get_short_term_memory_context, get_long_term_memory_context],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=False
            ),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="AUTO",
                )
            ),
        )
        return self.client.chats.create(model=self.model_name, config=config)

    def ask(self, user_text: str) -> str:
        response = self.chat.send_message(user_text)
        return (response.text or "").strip()
