from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_MODEL_NAME = "gemini-2.5-pro"
MEMORY_SCHEMA_VERSION = 1

DEFAULT_MEMORY: dict[str, Any] = {
    "schema_version": MEMORY_SCHEMA_VERSION,
    "memory_version": 0,
    "last_updated_utc": "",
    "last_updated_meeting_id": "",
    "processed_snapshot_path": "",
    "meeting_history_ids": [],
    "units": [],
}

MERGE_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["merge_existing", "create_new"],
        },
        "unit_id": {
            "type": "string",
            "description": "Required only when action=merge_existing.",
        },
        "title": {
            "type": "string",
            "description": "Short topic title for the short-term unit.",
        },
        "summary": {
            "type": "string",
            "description": "Current short-term summary after applying this L1 object.",
        },
        "related_topics": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rationale": {
            "type": "string",
            "description": "Brief reason for merge/create decision.",
        },
    },
    "required": ["action", "title", "summary", "related_topics"],
    "additionalProperties": False,
}


def empty_memory() -> dict[str, Any]:
    return deepcopy(DEFAULT_MEMORY)

