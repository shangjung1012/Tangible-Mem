from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


VALID_OPERATIONS = {"create", "update", "close", "replace", "no_op"}
VALID_SECTIONS = {
    "meeting_window",
    "action_items",
    "method_changes",
    "experiment_todos",
    "next_meeting_focus",
}
INTERNAL_PAYLOAD_KEYS = {"operation", "confidence", "evidence"}


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL").fetchone()
        conn.execute("PRAGMA synchronous = NORMAL")
        yield conn
    finally:
        conn.close()


def ensure_staging_schema(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_candidate_staging (
                candidate_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                meeting_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                target_section TEXT NOT NULL,
                operation TEXT NOT NULL,
                target_id TEXT NOT NULL DEFAULT '',
                candidate_json TEXT NOT NULL,
                evidence_lines_json TEXT NOT NULL DEFAULT '[]',
                evidence_quote TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                warnings_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'staged',
                created_at_utc TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memory_candidate_staging_run
                ON memory_candidate_staging (run_id, agent_name, target_section);
            """
        )


def clear_staging_for_run(db_path: Path, run_id: str) -> None:
    ensure_staging_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM memory_candidate_staging WHERE run_id = ?", (run_id,))
        conn.commit()


def write_staged_candidate(
    db_path: Path,
    *,
    run_id: str,
    meeting_id: str,
    agent_name: str,
    target_section: str,
    operation: str,
    candidate_payload: dict[str, Any],
    target_id: str = "",
    evidence_lines: list[Any] | None = None,
    evidence_quote: str = "",
    confidence: float = 0.0,
    note: str = "",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    ensure_staging_schema(db_path)
    clean_section = str(target_section or "").strip()
    clean_operation = str(operation or "").strip()
    clean_target_id = str(target_id or "").strip()
    parsed_confidence = _safe_float(confidence, 0.0)
    clean_warnings = list(warnings or [])

    if clean_section not in VALID_SECTIONS:
        return {"ok": False, "error": "invalid_target_section"}
    if clean_operation not in VALID_OPERATIONS:
        return {"ok": False, "error": "invalid_operation"}
    if not isinstance(candidate_payload, dict):
        return {"ok": False, "error": "candidate_payload_must_be_object"}
    if clean_operation in {"update", "close", "replace"} and not clean_target_id:
        return {"ok": False, "error": "missing_target_id"}
    if clean_operation != "no_op" and _candidate_payload_is_sparse(candidate_payload):
        return {
            "ok": False,
            "error": "sparse_candidate_payload",
            "message": (
                "candidate_payload must include section content fields, not only "
                "operation/confidence/evidence."
            ),
        }
    if not evidence_lines:
        clean_warnings.append("missing_evidence_lines")
    if not str(evidence_quote or "").strip():
        clean_warnings.append("missing_evidence_quote")

    sequence = _next_sequence(db_path, run_id, agent_name)
    candidate_id = f"{run_id}:{agent_name}:{clean_section}:{sequence:04d}"
    created_at = _utc_now_iso()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO memory_candidate_staging (
                candidate_id,
                run_id,
                meeting_id,
                agent_name,
                target_section,
                operation,
                target_id,
                candidate_json,
                evidence_lines_json,
                evidence_quote,
                confidence,
                note,
                warnings_json,
                status,
                created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                run_id,
                meeting_id,
                agent_name,
                clean_section,
                clean_operation,
                clean_target_id,
                json.dumps(candidate_payload, ensure_ascii=False),
                json.dumps(list(evidence_lines or []), ensure_ascii=False),
                str(evidence_quote or ""),
                parsed_confidence,
                str(note or ""),
                json.dumps(sorted(set(clean_warnings)), ensure_ascii=False),
                "staged",
                created_at,
            ),
        )
        conn.commit()
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "warnings": sorted(set(clean_warnings)),
    }


def load_staged_candidates(
    db_path: Path,
    *,
    run_id: str,
    agent_name: str | None = None,
    target_section: str | None = None,
) -> list[dict[str, Any]]:
    ensure_staging_schema(db_path)
    clauses = ["run_id = ?"]
    params: list[Any] = [run_id]
    if agent_name:
        clauses.append("agent_name = ?")
        params.append(agent_name)
    if target_section:
        clauses.append("target_section = ?")
        params.append(target_section)

    query = (
        "SELECT * FROM memory_candidate_staging WHERE "
        + " AND ".join(clauses)
        + " ORDER BY created_at_utc ASC, candidate_id ASC"
    )
    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_candidate(row) for row in rows]


def _row_to_candidate(row: sqlite3.Row) -> dict[str, Any]:
    payload = _loads_object(row["candidate_json"])
    evidence_lines = _loads_list(row["evidence_lines_json"])
    warnings = _loads_list(row["warnings_json"])
    evidence_quote = str(row["evidence_quote"] or "")
    if "evidence" not in payload:
        evidence = _format_evidence_lines(evidence_lines)
        if evidence:
            payload["evidence"] = evidence
    if "confidence" not in payload:
        payload["confidence"] = float(row["confidence"] or 0.0)
    if "operation" not in payload:
        payload["operation"] = str(row["operation"] or "")
    return {
        "agent": str(row["agent_name"]),
        "section": str(row["target_section"]),
        "candidate_id": str(row["candidate_id"]),
        "operation": str(row["operation"]),
        "target_id": str(row["target_id"] or ""),
        "payload": payload,
        "evidence_lines": evidence_lines,
        "evidence_quote": evidence_quote,
        "confidence": float(row["confidence"] or 0.0),
        "note": str(row["note"] or ""),
        "warnings": warnings,
        "staging_status": str(row["status"] or ""),
    }


def _next_sequence(db_path: Path, run_id: str, agent_name: str) -> int:
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM memory_candidate_staging
            WHERE run_id = ? AND agent_name = ?
            """,
            (run_id, agent_name),
        ).fetchone()
    return int(row["c"] or 0) + 1


def _loads_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _loads_list(raw: str) -> list[Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _format_evidence_lines(values: list[Any]) -> str:
    line_numbers: list[int] = []
    for value in values:
        try:
            line_number = int(value)
        except (TypeError, ValueError):
            continue
        if line_number > 0:
            line_numbers.append(line_number)
    if not line_numbers:
        return ""

    deduped = sorted(set(line_numbers))
    ranges: list[str] = []
    start = deduped[0]
    previous = deduped[0]
    for line_number in deduped[1:]:
        if line_number == previous + 1:
            previous = line_number
            continue
        ranges.append(_format_evidence_range(start, previous))
        start = line_number
        previous = line_number
    ranges.append(_format_evidence_range(start, previous))
    return ", ".join(ranges)


def _format_evidence_range(start: int, end: int) -> str:
    if start == end:
        return f"L{start}"
    return f"L{start}-L{end}"


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _candidate_payload_is_sparse(payload: dict[str, Any]) -> bool:
    content_keys = {
        str(key).strip()
        for key, value in payload.items()
        if str(key).strip()
        and key not in INTERNAL_PAYLOAD_KEYS
        and value not in (None, "", [], {})
    }
    return not content_keys


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
