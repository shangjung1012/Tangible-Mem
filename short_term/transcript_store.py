from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TRANSCRIPT_DB_PATH = Path(__file__).resolve().parent / "transcripts.db"
DEFAULT_TRANSCRIPT_PAGE_SIZE = 30
MAX_TRANSCRIPT_PAGE_SIZE = 80

_SPEAKER_LINE_RE = re.compile(r"^\[(?P<speaker>[^\]]+)\]:\s*(?P<text>.*)$")


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def ensure_schema(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transcripts (
                meeting_id TEXT PRIMARY KEY,
                source_file TEXT NOT NULL,
                imported_at_utc TEXT NOT NULL,
                line_count INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transcript_lines (
                meeting_id TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                speaker TEXT NOT NULL,
                text TEXT NOT NULL,
                raw_line TEXT NOT NULL,
                PRIMARY KEY (meeting_id, line_number),
                FOREIGN KEY (meeting_id)
                    REFERENCES transcripts(meeting_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_transcript_lines_meeting_line
                ON transcript_lines(meeting_id, line_number);
            """
        )


def _parse_transcript_line(raw_line: str) -> tuple[str, str]:
    stripped = raw_line.strip()
    match = _SPEAKER_LINE_RE.match(stripped)
    if match:
        return match.group("speaker").strip(), match.group("text").strip()
    return "", stripped


def import_transcript_to_sqlite(
    db_path: Path,
    meeting_id: str,
    source_file: str,
    transcript: str,
) -> int:
    ensure_schema(db_path)

    parsed_rows: list[tuple[str, int, str, str, str]] = []
    line_number = 0
    for raw_line in transcript.splitlines():
        if not raw_line.strip():
            continue
        line_number += 1
        speaker, text = _parse_transcript_line(raw_line)
        parsed_rows.append(
            (meeting_id, line_number, speaker, text, raw_line.rstrip())
        )

    with _connect(db_path) as conn:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM transcripts WHERE meeting_id = ?", (meeting_id,))
        conn.execute(
            """
            INSERT INTO transcripts
                (meeting_id, source_file, imported_at_utc, line_count)
            VALUES (?, ?, ?, ?)
            """,
            (meeting_id, source_file, _utc_now_iso(), len(parsed_rows)),
        )
        if parsed_rows:
            conn.executemany(
                """
                INSERT INTO transcript_lines
                    (meeting_id, line_number, speaker, text, raw_line)
                VALUES (?, ?, ?, ?, ?)
                """,
                parsed_rows,
            )
        conn.commit()

    return len(parsed_rows)


def load_transcript_overview(
    db_path: Path,
    meeting_id: str,
    preview_limit: int = 3,
) -> dict[str, Any]:
    ensure_schema(db_path)
    safe_preview_limit = max(min(int(preview_limit or 3), 10), 0)

    with _connect(db_path) as conn:
        transcript_row = conn.execute(
            """
            SELECT meeting_id, source_file, imported_at_utc, line_count
            FROM transcripts
            WHERE meeting_id = ?
            """,
            (meeting_id,),
        ).fetchone()
        if transcript_row is None:
            return {
                "ok": False,
                "error": f"Transcript not found for meeting_id={meeting_id}",
                "meeting_id": meeting_id,
            }

        first_rows = conn.execute(
            """
            SELECT line_number, speaker, text, raw_line
            FROM transcript_lines
            WHERE meeting_id = ?
            ORDER BY line_number ASC
            LIMIT ?
            """,
            (meeting_id, safe_preview_limit),
        ).fetchall()
        last_rows = conn.execute(
            """
            SELECT line_number, speaker, text, raw_line
            FROM transcript_lines
            WHERE meeting_id = ?
            ORDER BY line_number DESC
            LIMIT ?
            """,
            (meeting_id, safe_preview_limit),
        ).fetchall()

    return {
        "ok": True,
        "meeting_id": str(transcript_row["meeting_id"]),
        "source_file": str(transcript_row["source_file"]),
        "imported_at_utc": str(transcript_row["imported_at_utc"]),
        "line_count": int(transcript_row["line_count"]),
        "first_lines": [_row_to_dict(row) for row in first_rows],
        "last_lines": [_row_to_dict(row) for row in reversed(last_rows)],
        "recommended_start_line": 1,
        "recommended_page_size": DEFAULT_TRANSCRIPT_PAGE_SIZE,
        "max_page_size": MAX_TRANSCRIPT_PAGE_SIZE,
    }


def load_transcript_lines(
    db_path: Path,
    meeting_id: str,
    start_line: int = 1,
    end_line: int | None = None,
    limit: int = DEFAULT_TRANSCRIPT_PAGE_SIZE,
) -> dict[str, Any]:
    ensure_schema(db_path)
    safe_start = max(int(start_line or 1), 1)
    safe_limit = max(
        min(int(limit or DEFAULT_TRANSCRIPT_PAGE_SIZE), MAX_TRANSCRIPT_PAGE_SIZE),
        1,
    )
    safe_end = int(end_line) if end_line is not None else safe_start + safe_limit - 1
    safe_end = max(safe_end, safe_start)
    safe_end = min(safe_end, safe_start + safe_limit - 1)

    with _connect(db_path) as conn:
        meta = conn.execute(
            "SELECT line_count FROM transcripts WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()
        if meta is None:
            return {
                "ok": False,
                "error": f"Transcript not found for meeting_id={meeting_id}",
                "meeting_id": meeting_id,
            }

        rows = conn.execute(
            """
            SELECT line_number, speaker, text, raw_line
            FROM transcript_lines
            WHERE meeting_id = ?
              AND line_number BETWEEN ? AND ?
            ORDER BY line_number ASC
            """,
            (meeting_id, safe_start, safe_end),
        ).fetchall()

    line_count = int(meta["line_count"])
    returned_count = len(rows)
    next_start_line = safe_start + returned_count if returned_count else safe_end + 1
    return {
        "ok": True,
        "meeting_id": meeting_id,
        "start_line": safe_start,
        "end_line": safe_end,
        "returned_count": returned_count,
        "line_count": line_count,
        "has_more": safe_end < line_count,
        "next_start_line": next_start_line if safe_end < line_count else None,
        "items": [_row_to_dict(row) for row in rows],
    }


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "line_number": int(row["line_number"]),
        "speaker": str(row["speaker"]),
        "text": str(row["text"]),
        "raw_line": str(row["raw_line"]),
    }
