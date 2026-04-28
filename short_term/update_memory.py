from __future__ import annotations

import argparse
import os
from pathlib import Path

from io_utils import load_env, print_json_safe, save_json
from llm_client import generate_updated_memory
from schema import DEFAULT_MODEL_NAME
from sqlite_store import (
    DEFAULT_DB_PATH,
    append_snapshot,
    export_db_snapshot,
    load_memory_from_sqlite,
    load_memory_with_fallback,
    save_memory_to_sqlite,
)
from transcript_store import (
    DEFAULT_TRANSCRIPT_DB_PATH,
    import_transcript_to_sqlite,
    load_transcript_lines,
    load_transcript_overview,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update short-term memory from one transcript.")
    parser.add_argument(
        "--transcript",
        required=True,
        help="Path to one meeting transcript file.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to SQLite database for short-term memory.",
    )
    parser.add_argument(
        "--transcript-db",
        default=str(DEFAULT_TRANSCRIPT_DB_PATH),
        help="Path to SQLite database used to store/read transcript lines.",
    )
    parser.add_argument(
        "--memory-json",
        default="short_term/current_memory.json",
        help="Legacy JSON path used for bootstrap (read) and optional mirror (write).",
    )
    parser.add_argument(
        "--no-bootstrap-json",
        action="store_true",
        help="Do not import legacy JSON when SQLite is empty.",
    )
    parser.add_argument(
        "--mirror-json",
        action="store_true",
        help="Also mirror latest memory into --memory-json after DB write.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="short_term/snapshots",
        help="Directory for JSON snapshots. Default keeps a snapshot for every run.",
    )
    parser.add_argument(
        "--db-snapshot-dir",
        default="short_term/db_snapshots",
        help="Directory for SQLite DB snapshots. Default keeps a DB snapshot for every run.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("GEMINI_MODEL", DEFAULT_MODEL_NAME),
        help=f"Gemini model name (default: {DEFAULT_MODEL_NAME}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print updated memory JSON without writing files.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce progress logs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    def log(message: str) -> None:
        if not args.quiet:
            print(f"[update_memory] {message}", flush=True)

    transcript_path = Path(args.transcript).resolve()
    db_path = Path(args.db).resolve()
    transcript_db_path = Path(args.transcript_db).resolve()
    memory_json_path = Path(args.memory_json).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve() if args.snapshot_dir else None
    db_snapshot_dir = (
        Path(args.db_snapshot_dir).resolve() if args.db_snapshot_dir else None
    )

    if not transcript_path.exists():
        raise RuntimeError(f"Transcript file not found: {transcript_path}")

    meeting_id = transcript_path.stem
    source_file = str(transcript_path)
    log(f"loading transcript: {transcript_path}")
    transcript = transcript_path.read_text(encoding="utf-8")
    log(f"importing transcript into sqlite: {transcript_db_path}")
    transcript_line_count = import_transcript_to_sqlite(
        db_path=transcript_db_path,
        meeting_id=meeting_id,
        source_file=source_file,
        transcript=transcript,
    )
    log(f"transcript imported lines={transcript_line_count}")
    log("loading memory source (sqlite/json fallback)")
    current_memory, memory_source = load_memory_with_fallback(
        db_path=db_path,
        json_path=memory_json_path,
        bootstrap_from_json=not args.no_bootstrap_json,
    )
    log(
        f"memory loaded from={memory_source} "
        f"version={int(current_memory.get('memory_version', 0) or 0)} "
        f"meeting_history={len(current_memory.get('meeting_history_ids', []))}"
    )
    log("loading GEMINI_API_KEY from .env")
    api_key = load_env()

    def on_memory_read() -> dict[str, object]:
        return load_memory_from_sqlite(db_path)

    def on_memory_write(memory: dict[str, object]) -> None:
        log(f"writing sqlite db: {db_path}")
        save_memory_to_sqlite(db_path, memory)

    def on_transcript_overview_read() -> dict[str, object]:
        return load_transcript_overview(
            db_path=transcript_db_path,
            meeting_id=meeting_id,
        )

    def on_transcript_lines_read(
        start_line: int,
        end_line: int | None,
        limit: int,
    ) -> dict[str, object]:
        return load_transcript_lines(
            db_path=transcript_db_path,
            meeting_id=meeting_id,
            start_line=start_line,
            end_line=end_line,
            limit=limit,
        )

    log(f"starting Gemini update (model={args.model}, meeting_id={meeting_id})")
    updated_memory = generate_updated_memory(
        model_name=args.model,
        api_key=api_key,
        transcript=transcript,
        current_memory=current_memory,
        meeting_id=meeting_id,
        source_file=source_file,
        transcript_line_count=transcript_line_count,
        on_transcript_overview_read=on_transcript_overview_read,
        on_transcript_lines_read=on_transcript_lines_read,
        on_memory_read=None if args.dry_run else on_memory_read,
        on_memory_write=None if args.dry_run else on_memory_write,
        verbose=not args.quiet,
    )
    log("Gemini update completed")

    if args.dry_run:
        log("dry-run enabled, skip DB snapshots and JSON snapshot files")
        print_json_safe(updated_memory)
        return

    log("reloading persisted memory from sqlite")
    persisted_memory = load_memory_from_sqlite(db_path)

    log("append DB snapshot")
    snapshot_id = append_snapshot(
        db_path=db_path,
        meeting_id=meeting_id,
        memory=persisted_memory,
    )

    if args.mirror_json:
        log(f"writing mirror json from sqlite: {memory_json_path}")
        save_json(memory_json_path, persisted_memory)

    snapshot_tag = meeting_id
    if snapshot_dir is not None:
        snapshot_name = f"{snapshot_tag}.json"
        snapshot_path = snapshot_dir / snapshot_name
        save_json(snapshot_path, persisted_memory)
        print(f"JSON snapshot saved: {snapshot_path}")

    if db_snapshot_dir is not None:
        db_snapshot_path = db_snapshot_dir / f"{snapshot_tag}.db"
        export_db_snapshot(db_path=db_path, snapshot_path=db_snapshot_path)
        print(f"DB file snapshot saved: {db_snapshot_path}")

    print(f"Updated memory DB: {db_path}")
    print(f"Loaded initial memory from: {memory_source}")
    print(f"DB snapshot_id={snapshot_id}")
    print(f"memory_version={persisted_memory['memory_version']}")
    print(
        "meeting_window="
        f"{len(persisted_memory['meeting_window'])} "
        f"action_items={len(persisted_memory['action_items'])}"
    )


if __name__ == "__main__":
    main()
