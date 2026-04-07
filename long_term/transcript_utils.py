"""Helpers for parsing ICSI MRT transcripts."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_SEGMENT_RE = re.compile(
    r'<Segment\s+StartTime="([^"]+)"\s+EndTime="[^"]+"\s+Participant="([^"]+)">'
    r"(.*?)</Segment>",
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def mrt_to_text(mrt_path: Path) -> str:
    """Parse ICSI .mrt XML into plain speaker-turn text."""
    raw = mrt_path.read_text(encoding="iso-8859-1")
    lines: list[str] = []
    for match in _SEGMENT_RE.finditer(raw):
        start_time, speaker, body = match.group(1), match.group(2), match.group(3)
        text = _TAG_RE.sub("", body).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            lines.append(f"[{speaker} @ {start_time}s]: {text}")
    return "\n".join(lines)


def infer_meeting_date(mrt_path: Path) -> str:
    """Best-effort extract YYYY-MM-DD from file stem; fallback to empty."""
    stem = mrt_path.stem
    match = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", stem)
    if not match:
        return ""

    date_str = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    try:
        datetime.fromisoformat(date_str)
    except ValueError:
        return ""
    return date_str
