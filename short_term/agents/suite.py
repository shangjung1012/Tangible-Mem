from __future__ import annotations

from google import genai

from . import action_items, context_planner, experiment_todos, meeting_summary
from . import method_changes, next_focus, segment
from .base import GeminiJsonAgent
from .schemas import (
    ACTION_SCHEMA,
    CONTEXT_PLANNER_SCHEMA,
    EXPERIMENT_SCHEMA,
    FOCUS_SCHEMA,
    MEETING_SCHEMA,
    METHOD_SCHEMA,
    SEGMENT_SCHEMA,
)


class ShortTermAgentSuite:
    def __init__(self, client: genai.Client, model_name: str) -> None:
        self.context_planner = GeminiJsonAgent(
            name=context_planner.AGENT_NAME,
            client=client,
            model_name=model_name,
            schema=CONTEXT_PLANNER_SCHEMA,
        )
        self.segment = GeminiJsonAgent(
            name=segment.AGENT_NAME,
            client=client,
            model_name=model_name,
            schema=SEGMENT_SCHEMA,
        )
        self.meeting = GeminiJsonAgent(
            name=meeting_summary.AGENT_NAME,
            client=client,
            model_name=model_name,
            schema=MEETING_SCHEMA,
        )
        self.action = GeminiJsonAgent(
            name=action_items.AGENT_NAME,
            client=client,
            model_name=model_name,
            schema=ACTION_SCHEMA,
        )
        self.method = GeminiJsonAgent(
            name=method_changes.AGENT_NAME,
            client=client,
            model_name=model_name,
            schema=METHOD_SCHEMA,
        )
        self.experiment = GeminiJsonAgent(
            name=experiment_todos.AGENT_NAME,
            client=client,
            model_name=model_name,
            schema=EXPERIMENT_SCHEMA,
        )
        self.focus = GeminiJsonAgent(
            name=next_focus.AGENT_NAME,
            client=client,
            model_name=model_name,
            schema=FOCUS_SCHEMA,
        )
