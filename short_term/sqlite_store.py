from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .schema import DEFAULT_MEMORY
except ImportError:  # pragma: no cover - script execution fallback
    from schema import DEFAULT_MEMORY


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "short_term_memory.db"


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
            CREATE TABLE IF NOT EXISTS memory_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meeting_history (
                position INTEGER PRIMARY KEY,
                meeting_id TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS meeting_window (
                position INTEGER NOT NULL,
                meeting_id TEXT PRIMARY KEY,
                row_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS action_items (
                position INTEGER NOT NULL,
                item_id TEXT PRIMARY KEY,
                row_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS method_changes (
                position INTEGER NOT NULL,
                change_id TEXT PRIMARY KEY,
                row_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS experiment_todos (
                position INTEGER NOT NULL,
                todo_id TEXT PRIMARY KEY,
                row_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS next_meeting_focus (
                position INTEGER PRIMARY KEY,
                focus_text TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_utc TEXT NOT NULL,
                meeting_id TEXT NOT NULL,
                memory_json TEXT NOT NULL
            );
            """
        )


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(DEFAULT_MEMORY)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in memory file: {path}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Memory file must be a JSON object: {path}")
    return data


def _safe_int(value: str | int | None, fallback: int = 0) -> int:
    try:
        return int(value or fallback)
    except (TypeError, ValueError):
        return fallback


def _load_object_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT row_json FROM {table} ORDER BY position ASC"
    ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        raw = row["row_json"]
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            output.append(parsed)
    return output


def has_memory_data(db_path: Path) -> bool:
    if not db_path.exists():
        return False

    ensure_schema(db_path)
    with _connect(db_path) as conn:
        tables = [
            "memory_meta",
            "meeting_history",
            "meeting_window",
            "action_items",
            "method_changes",
            "experiment_todos",
            "next_meeting_focus",
        ]
        for table in tables:
            count = conn.execute(f"SELECT COUNT(1) AS c FROM {table}").fetchone()["c"]
            if count and int(count) > 0:
                return True
    return False


def load_memory_from_sqlite(db_path: Path) -> dict[str, Any]:
    ensure_schema(db_path)

    memory: dict[str, Any] = deepcopy(DEFAULT_MEMORY)
    with _connect(db_path) as conn:
        meta_rows = conn.execute("SELECT key, value FROM memory_meta").fetchall()
        meta = {str(row["key"]): str(row["value"]) for row in meta_rows}

        memory["memory_version"] = _safe_int(meta.get("memory_version"), 0)
        memory["last_updated_utc"] = meta.get("last_updated_utc", "")
        memory["last_updated_meeting_id"] = meta.get("last_updated_meeting_id", "")

        memory["meeting_history_ids"] = [
            str(row["meeting_id"])
            for row in conn.execute(
                "SELECT meeting_id FROM meeting_history ORDER BY position ASC"
            ).fetchall()
        ]

        memory["meeting_window"] = _load_object_rows(conn, "meeting_window")
        memory["action_items"] = _load_object_rows(conn, "action_items")
        memory["method_changes"] = _load_object_rows(conn, "method_changes")
        memory["experiment_todos"] = _load_object_rows(conn, "experiment_todos")

        memory["next_meeting_focus"] = [
            str(row["focus_text"])
            for row in conn.execute(
                "SELECT focus_text FROM next_meeting_focus ORDER BY position ASC"
            ).fetchall()
        ]

    return memory


def _replace_object_rows(
    conn: sqlite3.Connection,
    table: str,
    id_key: str,
    rows: list[dict[str, Any]],
) -> None:
    conn.execute(f"DELETE FROM {table}")
    normalized_rows: list[tuple[int, str, str]] = []
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        row_id = str(row.get(id_key, "")).strip()
        if not row_id:
            continue
        payload = dict(row)
        payload[id_key] = row_id
        normalized_rows.append(
            (position, row_id, json.dumps(payload, ensure_ascii=False))
        )

    if normalized_rows:
        conn.executemany(
            f"INSERT INTO {table} (position, {id_key}, row_json) VALUES (?, ?, ?)",
            normalized_rows,
        )


def save_memory_to_sqlite(db_path: Path, memory: dict[str, Any]) -> None:
    ensure_schema(db_path)

    with _connect(db_path) as conn:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM memory_meta")
        conn.executemany(
            "INSERT INTO memory_meta (key, value) VALUES (?, ?)",
            [
                ("memory_version", str(_safe_int(memory.get("memory_version"), 0))),
                ("last_updated_utc", str(memory.get("last_updated_utc", ""))),
                (
                    "last_updated_meeting_id",
                    str(memory.get("last_updated_meeting_id", "")),
                ),
            ],
        )

        conn.execute("DELETE FROM meeting_history")
        history_ids = memory.get("meeting_history_ids", [])
        history_rows = [
            (position, str(meeting_id).strip())
            for position, meeting_id in enumerate(history_ids, start=1)
            if str(meeting_id).strip()
        ]
        if history_rows:
            conn.executemany(
                "INSERT INTO meeting_history (position, meeting_id) VALUES (?, ?)",
                history_rows,
            )

        _replace_object_rows(
            conn,
            table="meeting_window",
            id_key="meeting_id",
            rows=memory.get("meeting_window", []),
        )
        _replace_object_rows(
            conn,
            table="action_items",
            id_key="item_id",
            rows=memory.get("action_items", []),
        )
        _replace_object_rows(
            conn,
            table="method_changes",
            id_key="change_id",
            rows=memory.get("method_changes", []),
        )
        _replace_object_rows(
            conn,
            table="experiment_todos",
            id_key="todo_id",
            rows=memory.get("experiment_todos", []),
        )

        conn.execute("DELETE FROM next_meeting_focus")
        focus_rows = [
            (position, str(text).strip())
            for position, text in enumerate(memory.get("next_meeting_focus", []), start=1)
            if str(text).strip()
        ]
        if focus_rows:
            conn.executemany(
                "INSERT INTO next_meeting_focus (position, focus_text) VALUES (?, ?)",
                focus_rows,
            )

        conn.commit()


def append_snapshot(db_path: Path, meeting_id: str, memory: dict[str, Any]) -> int:
    ensure_schema(db_path)

    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO memory_snapshots (created_at_utc, meeting_id, memory_json)
            VALUES (?, ?, ?)
            """,
            (
                _utc_now_iso(),
                str(meeting_id).strip(),
                json.dumps(memory, ensure_ascii=False),
            ),
        )
        conn.commit()
        snapshot_id = int(cursor.lastrowid or 0)

    return snapshot_id


def export_db_snapshot(
    db_path: Path,
    snapshot_path: Path,
) -> Path:
    """Export a point-in-time SQLite snapshot file via backup API."""
    ensure_schema(db_path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    with _connect(db_path) as source_conn:
        source_conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        with sqlite3.connect(str(snapshot_path)) as target_conn:
            source_conn.backup(target_conn)

    return snapshot_path


def load_memory_with_fallback(
    db_path: Path,
    json_path: Path | None = None,
    bootstrap_from_json: bool = True,
) -> tuple[dict[str, Any], str]:
    if has_memory_data(db_path):
        return load_memory_from_sqlite(db_path), "sqlite"

    if json_path is not None and json_path.exists():
        memory = _load_json_file(json_path)
        if bootstrap_from_json:
            save_memory_to_sqlite(db_path, memory)
            return load_memory_from_sqlite(db_path), "json_bootstrap"
        return memory, "json"

    return deepcopy(DEFAULT_MEMORY), "default"
