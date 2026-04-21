from __future__ import annotations

from typing import Any

DEFAULT_MODEL_NAME = "gemini-2.5-pro"

ACTION_ITEM_STATUS = {"open", "in_progress", "completed", "cancelled"}
METHOD_CHANGE_STATUS = {"active", "reverted", "superseded"}
EXPERIMENT_STATUS = {"open", "in_progress", "completed", "blocked"}
PRIORITY_LEVELS = {"high", "medium", "low"}

DEFAULT_MEMORY: dict[str, Any] = {
    "memory_version": 0,
    "last_updated_utc": "",
    "last_updated_meeting_id": "",
    "meeting_history_ids": [],
    "meeting_window": [],
    "action_items": [],
    "method_changes": [],
    "experiment_todos": [],
    "next_meeting_focus": [],
}

SCHEMA_DESCRIPTION = {
    "memory_version": "int, every update must +1",
    "last_updated_utc": "ISO8601 UTC string",
    "last_updated_meeting_id": "string",
    "meeting_history_ids": [
        "string, system-managed ordered meeting ids from oldest to newest"
    ],
    "meeting_window": [
        {
            "meeting_id": "string",
            "source_file": "string",
            "summary": "string",
            "key_points": ["string"],
            "open_questions": ["string"],
        }
    ],
    "action_items": [
        {
            "item_id": "A###",
            "title": "string",
            "detail": "string",
            "proposer": "string",
            "owner": "string",
            "created_meeting_id": "string",
            "created_time_hint": "string",
            "dependencies": ["A###"],
            "status": "open|in_progress|completed|cancelled",
            "priority": "high|medium|low",
            "evidence": "string",
            "last_updated_meeting_id": "string",
            "history": [
                {
                    "version": "int",
                    "meeting_id": "string",
                    "change": "string",
                }
            ],
        }
    ],
    "method_changes": [
        {
            "change_id": "M###",
            "topic": "string",
            "before": "string",
            "after": "string",
            "reason": "string",
            "status": "active|reverted|superseded",
            "meeting_id": "string",
            "evidence": "string",
        }
    ],
    "experiment_todos": [
        {
            "todo_id": "E###",
            "description": "string",
            "status": "open|in_progress|completed|blocked",
            "owner": "string",
            "related_action_item_ids": ["A###"],
            "meeting_id": "string",
            "evidence": "string",
        }
    ],
    "next_meeting_focus": ["string"],
}

RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "memory_version": {
            "type": "integer",
            "description": "Short-term memory version. Should increase by 1 every update.",
        },
        "last_updated_utc": {
            "type": "string",
            "description": "Last update time in ISO8601 UTC format.",
        },
        "last_updated_meeting_id": {
            "type": "string",
            "description": "Meeting ID that triggered this update.",
        },
        "meeting_history_ids": {
            "type": "array",
            "description": "System-managed ordered meeting IDs from oldest to newest. The application maintains this field locally.",
            "items": {"type": "string"},
        },
        "meeting_window": {
            "type": "array",
            "description": "Recent meetings window, max 3 meetings.",
            "items": {
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "string"},
                    "source_file": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "open_questions": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "meeting_id",
                    "source_file",
                    "summary",
                    "key_points",
                    "open_questions",
                ],
                "additionalProperties": False,
            },
        },
        "action_items": {
            "type": "array",
            "description": "Action items and TODOs scoped to the recent three-meeting window.",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "proposer": {"type": "string"},
                    "owner": {"type": "string"},
                    "created_meeting_id": {"type": "string"},
                    "created_time_hint": {"type": "string"},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "status": {
                        "type": "string",
                        "enum": sorted(ACTION_ITEM_STATUS),
                    },
                    "priority": {
                        "type": "string",
                        "enum": sorted(PRIORITY_LEVELS),
                    },
                    "evidence": {"type": "string"},
                    "last_updated_meeting_id": {"type": "string"},
                    "history": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "version": {"type": "integer"},
                                "meeting_id": {"type": "string"},
                                "change": {"type": "string"},
                            },
                            "required": ["version", "meeting_id", "change"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "item_id",
                    "title",
                    "detail",
                    "proposer",
                    "owner",
                    "created_meeting_id",
                    "created_time_hint",
                    "dependencies",
                    "status",
                    "priority",
                    "evidence",
                    "last_updated_meeting_id",
                    "history",
                ],
                "additionalProperties": False,
            },
        },
        "method_changes": {
            "type": "array",
            "description": "Recent method changes and rationale.",
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
                        "enum": sorted(METHOD_CHANGE_STATUS),
                    },
                    "meeting_id": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": [
                    "change_id",
                    "topic",
                    "before",
                    "after",
                    "reason",
                    "status",
                    "meeting_id",
                    "evidence",
                ],
                "additionalProperties": False,
            },
        },
        "experiment_todos": {
            "type": "array",
            "description": "Experiment-specific TODOs.",
            "items": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": sorted(EXPERIMENT_STATUS),
                    },
                    "owner": {"type": "string"},
                    "related_action_item_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "meeting_id": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": [
                    "todo_id",
                    "description",
                    "status",
                    "owner",
                    "related_action_item_ids",
                    "meeting_id",
                    "evidence",
                ],
                "additionalProperties": False,
            },
        },
        "next_meeting_focus": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Suggested focus points for next meeting.",
        },
    },
    "required": [
        "memory_version",
        "last_updated_utc",
        "last_updated_meeting_id",
        "meeting_window",
        "action_items",
        "method_changes",
        "experiment_todos",
        "next_meeting_focus",
    ],
    "additionalProperties": False,
}
