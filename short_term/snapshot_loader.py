from __future__ import annotations

from pathlib import Path
from typing import Any

from .io_utils import load_json_object, normalize_str


def load_snapshot_tree(path: Path | str) -> dict[str, Any]:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        raise RuntimeError(f"share_mem snapshot file not found: {snapshot_path}")
    tree = load_json_object(snapshot_path)
    meetings = tree.get("meetings")
    if not isinstance(meetings, list):
        keys = ", ".join(sorted(str(key) for key in tree.keys()))
        detail = f" Found top-level keys: {keys}" if keys else ""
        raise RuntimeError(
            f"share_mem snapshot must contain meetings[]: {snapshot_path}.{detail}"
        )
    return tree


def _meeting_sort_key(meeting: dict[str, Any]) -> tuple[int, str, str, str]:
    meeting_date = normalize_str(meeting.get("meeting_date"))
    timestamp = normalize_str(meeting.get("timestamp"))
    meeting_id = normalize_str(meeting.get("meeting_id"))
    has_date = 1 if meeting_date else 0
    return (has_date, meeting_date or timestamp, meeting_id, timestamp)


def sorted_meetings(tree: dict[str, Any]) -> list[dict[str, Any]]:
    meetings = [
        meeting
        for meeting in tree.get("meetings", [])
        if isinstance(meeting, dict) and normalize_str(meeting.get("meeting_id"))
    ]
    return sorted(meetings, key=_meeting_sort_key)


def select_latest_meeting(tree: dict[str, Any]) -> dict[str, Any]:
    meetings = sorted_meetings(tree)
    if not meetings:
        raise RuntimeError("share_mem snapshot contains no meetings")
    return meetings[-1]
