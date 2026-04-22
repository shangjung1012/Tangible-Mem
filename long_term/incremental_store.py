"""Lightweight SQLite working store for incremental L1 bridge runs."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from importance import calibrate_issue_importance


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "incremental_bridge.db"
ISSUE_EPISODE_GAP_LINES = 3
ISSUE_MATCH_THRESHOLD = 0.45
READ_PURPOSES = {
    "forward_scan",
    "lookback",
    "lookahead",
    "candidate_refine",
}

_ICSI_LINE_RE = re.compile(
    r"^\[(?P<speaker>.*?)\s*@\s*(?P<timestamp>[0-9]+(?:\.[0-9]+)?)s\]:\s*(?P<text>.*)$"
)
_BRACKET_SPEAKER_RE = re.compile(r"^\[(?P<speaker>[^\]]+)\]:\s*(?P<text>.*)$")
_COLON_SPEAKER_RE = re.compile(r"^(?P<speaker>[^:\[\]\n]{1,80}):\s*(?P<text>.+)$")
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_ISSUE_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "issue",
    "issues",
    "problem",
    "problems",
    "handling",
    "current",
    "existing",
    "need",
    "needs",
    "問題",
    "議題",
    "處理",
    "需要",
    "目前",
}


def utc_now_iso() -> str:
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
            CREATE TABLE IF NOT EXISTS transcript_lines (
                transcript_id TEXT NOT NULL,
                line_id INTEGER NOT NULL,
                speaker TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                timestamp_sec REAL,
                PRIMARY KEY (transcript_id, line_id)
            );

            CREATE TABLE IF NOT EXISTS issues (
                issue_id TEXT PRIMARY KEY,
                transcript_id TEXT NOT NULL,
                issue_key TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                importance REAL NOT NULL DEFAULT 0.5,
                summary TEXT NOT NULL DEFAULT '',
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS issue_mentions (
                mention_id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT NOT NULL,
                transcript_id TEXT NOT NULL,
                line_id INTEGER NOT NULL,
                purpose TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (issue_id) REFERENCES issues(issue_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS l1_objects (
                obj_id TEXT PRIMARY KEY,
                transcript_id TEXT NOT NULL,
                issue_id TEXT NOT NULL DEFAULT '',
                row_json TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );
            """
        )
        _ensure_column(conn, "issues", "issue_key", "TEXT NOT NULL DEFAULT ''")


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {str(row["name"]) for row in rows}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def parse_transcript_line(raw_line: str) -> dict[str, Any]:
    """Parse common speaker/timestamp line formats without changing source text."""
    line = raw_line.strip()
    speaker = ""
    timestamp_sec: float | None = None
    text = line

    match = _ICSI_LINE_RE.match(line)
    if match:
        speaker = match.group("speaker").strip()
        text = match.group("text").strip()
        try:
            timestamp_sec = float(match.group("timestamp"))
        except ValueError:
            timestamp_sec = None
        return {"speaker": speaker, "text": text, "timestamp_sec": timestamp_sec}

    match = _BRACKET_SPEAKER_RE.match(line)
    if match:
        return {
            "speaker": match.group("speaker").strip(),
            "text": match.group("text").strip(),
            "timestamp_sec": None,
        }

    match = _COLON_SPEAKER_RE.match(line)
    if match:
        return {
            "speaker": match.group("speaker").strip(),
            "text": match.group("text").strip(),
            "timestamp_sec": None,
        }

    return {"speaker": speaker, "text": text, "timestamp_sec": timestamp_sec}


def reset_transcript(db_path: Path, transcript_id: str) -> None:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM issue_mentions WHERE transcript_id = ?", (transcript_id,))
        conn.execute("DELETE FROM l1_objects WHERE transcript_id = ?", (transcript_id,))
        conn.execute("DELETE FROM issues WHERE transcript_id = ?", (transcript_id,))
        conn.execute("DELETE FROM transcript_lines WHERE transcript_id = ?", (transcript_id,))
        conn.commit()


def seed_transcript_lines(
    db_path: Path,
    transcript_id: str,
    transcript_text: str,
    *,
    replace: bool = True,
) -> int:
    """Store transcript text as one non-empty row per line."""
    ensure_schema(db_path)
    if replace:
        reset_transcript(db_path, transcript_id)

    rows: list[tuple[str, int, str, str, float | None]] = []
    for line_id, raw_line in enumerate(transcript_text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        parsed = parse_transcript_line(raw_line)
        rows.append(
            (
                transcript_id,
                line_id,
                str(parsed["speaker"]),
                str(parsed["text"]),
                parsed["timestamp_sec"],
            )
        )

    with _connect(db_path) as conn:
        if rows:
            conn.executemany(
                """
                INSERT OR REPLACE INTO transcript_lines
                    (transcript_id, line_id, speaker, text, timestamp_sec)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
        conn.commit()
    return len(rows)


def get_max_line_id(db_path: Path, transcript_id: str) -> int:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(line_id), 0) AS max_line FROM transcript_lines WHERE transcript_id = ?",
            (transcript_id,),
        ).fetchone()
    return int(row["max_line"] or 0)


def _line_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "line_id": int(row["line_id"]),
        "speaker": str(row["speaker"] or ""),
        "text": str(row["text"] or ""),
        "timestamp_sec": row["timestamp_sec"],
    }


def format_transcript_lines(lines: list[dict[str, Any]]) -> str:
    formatted: list[str] = []
    for line in lines:
        prefix = f"{line['line_id']}: "
        speaker = str(line.get("speaker") or "")
        timestamp_sec = line.get("timestamp_sec")
        if speaker and timestamp_sec is not None:
            prefix += f"[{speaker} @ {timestamp_sec}s] "
        elif speaker:
            prefix += f"[{speaker}] "
        formatted.append(prefix + str(line.get("text") or ""))
    return "\n".join(formatted)


def read_transcript_span(
    db_path: Path,
    transcript_id: str,
    start_line: int,
    end_line: int,
    purpose: str,
) -> dict[str, Any]:
    if purpose not in READ_PURPOSES:
        raise ValueError(f"Invalid read purpose: {purpose}")

    max_line = get_max_line_id(db_path, transcript_id)
    if max_line <= 0:
        return {
            "transcript_id": transcript_id,
            "start_line": 0,
            "end_line": 0,
            "purpose": purpose,
            "last_line": 0,
            "lines": [],
            "formatted_text": "",
        }

    start = max(1, int(start_line))
    end = min(max_line, int(end_line))
    if end < start:
        start, end = end, start
    start = max(1, start)
    end = min(max_line, end)

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT line_id, speaker, text, timestamp_sec
            FROM transcript_lines
            WHERE transcript_id = ? AND line_id BETWEEN ? AND ?
            ORDER BY line_id ASC
            """,
            (transcript_id, start, end),
        ).fetchall()

    lines = [_line_row_to_dict(row) for row in rows]
    actual_start = lines[0]["line_id"] if lines else start
    actual_end = lines[-1]["line_id"] if lines else end
    return {
        "transcript_id": transcript_id,
        "start_line": actual_start,
        "end_line": actual_end,
        "purpose": purpose,
        "last_line": max_line,
        "lines": lines,
        "formatted_text": format_transcript_lines(lines),
    }


def _issue_id_from_key(transcript_id: str, issue_key: str) -> str:
    digest = hashlib.sha1(f"{transcript_id}:{issue_key}".encode("utf-8")).hexdigest()[:10]
    return f"ISS-{transcript_id}-{digest}"


def _tokenize_issue_text(text: str) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(str(text or "").lower()):
        clean = token.strip("_- ")
        if clean and clean not in _ISSUE_STOPWORDS:
            tokens.append(clean)
    return tokens


def normalize_issue_key(value: str) -> str:
    tokens = _tokenize_issue_text(value)
    if tokens:
        return "_".join(tokens[:8])
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:10]
    return f"issue_{digest}"


def derive_issue_key(title: str, summary: str = "") -> str:
    combined = f"{title} {summary}".strip()
    return normalize_issue_key(combined)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _issue_similarity(
    *,
    title: str,
    summary: str,
    existing_title: str,
    existing_summary: str,
) -> float:
    new_title_tokens = set(_tokenize_issue_text(title))
    old_title_tokens = set(_tokenize_issue_text(existing_title))
    new_all_tokens = set(_tokenize_issue_text(f"{title} {summary}"))
    old_all_tokens = set(_tokenize_issue_text(f"{existing_title} {existing_summary}"))
    return max(
        _jaccard(new_title_tokens, old_title_tokens),
        _jaccard(new_all_tokens, old_all_tokens),
    )


def _find_matching_issue(
    conn: sqlite3.Connection,
    transcript_id: str,
    *,
    issue_id: str,
    issue_key: str,
    title: str,
    summary: str,
) -> sqlite3.Row | None:
    clean_issue_id = issue_id.strip()
    if clean_issue_id:
        row = conn.execute(
            "SELECT * FROM issues WHERE issue_id = ? AND transcript_id = ?",
            (clean_issue_id, transcript_id),
        ).fetchone()
        if row:
            return row

    clean_issue_key = issue_key.strip()
    if clean_issue_key:
        row = conn.execute(
            """
            SELECT *
            FROM issues
            WHERE transcript_id = ? AND issue_key = ?
            ORDER BY updated_at_utc DESC
            LIMIT 1
            """,
            (transcript_id, clean_issue_key),
        ).fetchone()
        if row:
            return row

    rows = conn.execute(
        """
        SELECT *
        FROM issues
        WHERE transcript_id = ?
        ORDER BY updated_at_utc DESC
        """,
        (transcript_id,),
    ).fetchall()
    best_row: sqlite3.Row | None = None
    best_score = 0.0
    for row in rows:
        score = _issue_similarity(
            title=title,
            summary=summary,
            existing_title=str(row["title"] or ""),
            existing_summary=str(row["summary"] or ""),
        )
        if score > best_score:
            best_score = score
            best_row = row
    if best_score >= ISSUE_MATCH_THRESHOLD:
        return best_row
    return None


def count_issue_episodes(line_ids: list[int], gap_lines: int = ISSUE_EPISODE_GAP_LINES) -> int:
    unique_lines = sorted({int(line_id) for line_id in line_ids})
    if not unique_lines:
        return 0
    episodes = 1
    previous = unique_lines[0]
    for line_id in unique_lines[1:]:
        if line_id - previous > gap_lines:
            episodes += 1
        previous = line_id
    return episodes


def get_issue_episode_count(
    conn: sqlite3.Connection,
    issue_id: str,
    gap_lines: int = ISSUE_EPISODE_GAP_LINES,
) -> int:
    rows = conn.execute(
        "SELECT line_id FROM issue_mentions WHERE issue_id = ? ORDER BY line_id ASC",
        (issue_id,),
    ).fetchall()
    return count_issue_episodes([int(row["line_id"]) for row in rows], gap_lines)


def upsert_issue(
    db_path: Path,
    transcript_id: str,
    title: str,
    *,
    issue_id: str = "",
    issue_key: str = "",
    status: str = "open",
    importance: float = 0.5,
    summary: str = "",
) -> dict[str, Any]:
    ensure_schema(db_path)
    clean_title = str(title).strip()
    if not clean_title:
        raise ValueError("Issue title is required.")
    clean_summary = str(summary).strip()
    clean_issue_key = normalize_issue_key(issue_key) if str(issue_key).strip() else derive_issue_key(clean_title, clean_summary)
    try:
        score = float(importance)
    except (TypeError, ValueError):
        score = 0.5
    score = max(0.0, min(1.0, round(score, 2)))
    now = utc_now_iso()

    with _connect(db_path) as conn:
        existing = _find_matching_issue(
            conn,
            transcript_id,
            issue_id=str(issue_id or ""),
            issue_key=clean_issue_key,
            title=clean_title,
            summary=clean_summary,
        )
        clean_issue_id = (
            str(existing["issue_id"])
            if existing is not None
            else str(issue_id).strip() or _issue_id_from_key(transcript_id, clean_issue_key)
        )
        if existing is not None and not str(issue_key).strip():
            clean_issue_key = str(existing["issue_key"] or clean_issue_key)
        episode_count = get_issue_episode_count(conn, clean_issue_id)
        calibrated_score = calibrate_issue_importance(
            score,
            episode_count=episode_count,
            status=status,
        )
        conn.execute(
            """
            INSERT INTO issues
                (issue_id, transcript_id, issue_key, title, status, importance, summary, updated_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(issue_id) DO UPDATE SET
                transcript_id = excluded.transcript_id,
                issue_key = excluded.issue_key,
                title = excluded.title,
                status = excluded.status,
                importance = excluded.importance,
                summary = excluded.summary,
                updated_at_utc = excluded.updated_at_utc
            """,
            (
                clean_issue_id,
                transcript_id,
                clean_issue_key,
                clean_title,
                str(status).strip() or "open",
                calibrated_score,
                clean_summary,
                now,
            ),
        )
        conn.commit()

    return {
        "issue_id": clean_issue_id,
        "transcript_id": transcript_id,
        "issue_key": clean_issue_key,
        "title": clean_title,
        "status": str(status).strip() or "open",
        "importance": calibrated_score,
        "summary": clean_summary,
        "updated_at_utc": now,
    }


def record_issue_mention(
    db_path: Path,
    transcript_id: str,
    issue_id: str,
    line_id: int,
    purpose: str,
    *,
    note: str = "",
) -> int:
    if purpose not in READ_PURPOSES:
        raise ValueError(f"Invalid mention purpose: {purpose}")
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        existing = conn.execute(
            """
            SELECT mention_id
            FROM issue_mentions
            WHERE issue_id = ? AND transcript_id = ? AND line_id = ? AND purpose = ?
            """,
            (issue_id, transcript_id, int(line_id), purpose),
        ).fetchone()
        if existing:
            return int(existing["mention_id"])

        cursor = conn.execute(
            """
            INSERT INTO issue_mentions (issue_id, transcript_id, line_id, purpose, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (issue_id, transcript_id, int(line_id), purpose, str(note).strip()),
        )
        issue_row = conn.execute(
            "SELECT importance, status FROM issues WHERE issue_id = ?",
            (issue_id,),
        ).fetchone()
        if issue_row:
            episode_count = get_issue_episode_count(conn, issue_id)
            new_importance = calibrate_issue_importance(
                issue_row["importance"],
                episode_count=episode_count,
                status=str(issue_row["status"] or "open"),
            )
            conn.execute(
                """
                UPDATE issues
                SET importance = ?, updated_at_utc = ?
                WHERE issue_id = ?
                """,
                (new_importance, utc_now_iso(), issue_id),
            )
        conn.commit()
    return int(cursor.lastrowid)


def load_issues(db_path: Path, transcript_id: str) -> list[dict[str, Any]]:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                i.issue_id,
                i.transcript_id,
                i.issue_key,
                i.title,
                i.status,
                i.importance,
                i.summary,
                i.updated_at_utc,
                COUNT(m.mention_id) AS mention_count,
                GROUP_CONCAT(m.line_id) AS mention_line_ids
            FROM issues i
            LEFT JOIN issue_mentions m ON i.issue_id = m.issue_id
            WHERE i.transcript_id = ?
            GROUP BY
                i.issue_id,
                i.transcript_id,
                i.issue_key,
                i.title,
                i.status,
                i.importance,
                i.summary,
                i.updated_at_utc
            ORDER BY i.updated_at_utc ASC, i.issue_id ASC
            """,
            (transcript_id,),
        ).fetchall()
    issues: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw_line_ids = str(item.pop("mention_line_ids") or "")
        line_ids = [
            int(value)
            for value in raw_line_ids.split(",")
            if value.strip().isdigit()
        ]
        item["episode_count"] = count_issue_episodes(line_ids)
        issues.append(item)
    return issues


def load_issue_mentions(db_path: Path, transcript_id: str) -> list[dict[str, Any]]:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT mention_id, issue_id, transcript_id, line_id, purpose, note
            FROM issue_mentions
            WHERE transcript_id = ?
            ORDER BY mention_id ASC
            """,
            (transcript_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_l1_object(
    db_path: Path,
    transcript_id: str,
    row: dict[str, Any],
    *,
    issue_id: str = "",
    obj_id: str = "",
) -> str:
    ensure_schema(db_path)
    clean_obj_id = str(obj_id).strip()
    if not clean_obj_id:
        digest = hashlib.sha1(
            json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:10]
        clean_obj_id = f"RAW-{transcript_id}-{digest}"

    payload = dict(row)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO l1_objects
                (obj_id, transcript_id, issue_id, row_json, created_at_utc)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                clean_obj_id,
                transcript_id,
                str(issue_id).strip(),
                json.dumps(payload, ensure_ascii=False),
                utc_now_iso(),
            ),
        )
        conn.commit()
    return clean_obj_id


def load_l1_objects(db_path: Path, transcript_id: str) -> list[dict[str, Any]]:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT row_json
            FROM l1_objects
            WHERE transcript_id = ?
            ORDER BY created_at_utc ASC, obj_id ASC
            """,
            (transcript_id,),
        ).fetchall()

    objects: list[dict[str, Any]] = []
    for row in rows:
        try:
            parsed = json.loads(str(row["row_json"]))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    return objects
