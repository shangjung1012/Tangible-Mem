from __future__ import annotations

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
