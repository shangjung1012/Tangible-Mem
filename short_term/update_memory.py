from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from genai_client import describe_genai_config, load_dotenv_files, load_genai_config
from io_utils import print_json_safe, save_json
from langgraph_update import run_short_term_langgraph_update
from schema import DEFAULT_MODEL_NAME
from sqlite_store import (
    DEFAULT_DB_PATH,
    append_snapshot,
    export_db_snapshot,
    load_memory_from_sqlite,
)
from transcript_store import (
    DEFAULT_TRANSCRIPT_DB_PATH,
    import_transcript_to_sqlite,
    load_transcript_overview,
)


def parse_args() -> argparse.Namespace:
    load_dotenv_files()
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
        help="Deprecated no-op. JSON is now only exported from SQLite for human review.",
    )
    parser.add_argument(
        "--no-bootstrap-json",
        action="store_true",
        help="Deprecated no-op. JSON bootstrap is disabled.",
    )
    parser.add_argument(
        "--mirror-json",
        action="store_true",
        help="Deprecated no-op. JSON mirror writes are disabled.",
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
        "--log-dir",
        default="short_term/logs",
        help="Directory for update logs. Set to empty string to disable file logging.",
    )
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=0,
        help="Deprecated. LangGraph mode does not use a Gemini tool-calling loop.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=80,
        help="Forward transcript window size for the LangGraph context planner.",
    )
    parser.add_argument(
        "--max-lookback-lines",
        type=int,
        default=20,
        help="Maximum context lines the planner may request before a forward window.",
    )
    parser.add_argument(
        "--max-lookahead-lines",
        type=int,
        default=40,
        help="Maximum context lines the planner may request after a forward window.",
    )
    parser.add_argument(
        "--checkpoint-db",
        default="short_term/langgraph_checkpoints.db",
        help="SQLite checkpoint DB for LangGraph workflow state.",
    )
    parser.add_argument(
        "--research-log-dir",
        default="short_term/research_logs",
        help="Directory for per-run research logs, prompts, responses, and reports.",
    )
    parser.add_argument(
        "--log-level",
        choices=["summary", "debug"],
        default="debug",
        help="Research log detail level. Debug keeps full prompts by default.",
    )
    parser.add_argument(
        "--keep-full-prompts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write full prompts into the research log directory.",
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


def format_langgraph_progress(event: dict[str, object]) -> str:
    node = str(event.get("node", "unknown"))
    phase = str(event.get("event", ""))
    processed = event.get("processed_until_line", 0)
    total = event.get("transcript_line_count", 0)
    line_range = str(event.get("line_range", "") or "")
    raw = event.get("raw_candidates", 0)
    duration = event.get("duration_seconds")
    summary = event.get("summary")

    tag = _progress_node_tag(node)
    label = _progress_node_label(node)
    action = _progress_action(node, phase)
    parts = [f"[{tag}] {phase.upper()} {label}"]
    if action:
        parts.append(f"action={action}")
    if line_range:
        parts.append(f"lines={line_range}")
    parts.append(f"processed={processed}/{total}")
    if node.startswith("extract_") or node in {"verify_candidates", "reduce_patch"}:
        parts.append(f"raw_candidates={raw}")
    if isinstance(duration, (int, float)):
        parts.append(f"duration={float(duration):.1f}s")
    if isinstance(summary, dict) and summary:
        brief = _brief_progress_summary(summary)
        if brief:
            parts.append(brief)
    return " ".join(parts)


def _progress_node_label(node: str) -> str:
    labels = {
        "load_inputs": "load inputs",
        "plan_next_window": "context planner",
        "read_window": "read transcript window",
        "segment_window": "segment transcript",
        "extract_meeting_window": "meeting summary agent",
        "extract_action_items": "action item agent",
        "extract_method_changes": "method change agent",
        "extract_experiment_todos": "experiment todo agent",
        "extract_next_focus": "next focus agent",
        "verify_candidates": "verify candidates",
        "reduce_patch": "reduce patch",
        "normalize_and_persist": "normalize and persist",
        "final_report": "final report",
    }
    return labels.get(node, node)


def _progress_node_tag(node: str) -> str:
    tags = {
        "load_inputs": "load_inputs",
        "plan_next_window": "context_planner",
        "read_window": "read_window",
        "segment_window": "segment_agent",
        "extract_meeting_window": "meeting_summary_agent",
        "extract_action_items": "action_item_agent",
        "extract_method_changes": "method_change_agent",
        "extract_experiment_todos": "experiment_todo_agent",
        "extract_next_focus": "next_focus_agent",
        "verify_candidates": "verifier",
        "reduce_patch": "reducer",
        "normalize_and_persist": "normalizer",
        "final_report": "final_report",
    }
    return tags.get(node, node)


def _progress_action(node: str, phase: str) -> str:
    if phase == "error":
        return "handling error"
    start_actions = {
        "load_inputs": "preparing graph state",
        "plan_next_window": "asking Gemini which transcript lines to inspect next",
        "read_window": "reading transcript lines from SQLite",
        "segment_window": "asking Gemini to split this window into idea units",
        "extract_meeting_window": "asking Gemini for meeting summary candidates",
        "extract_action_items": "asking Gemini for action item candidates",
        "extract_method_changes": "asking Gemini for method change candidates",
        "extract_experiment_todos": "asking Gemini for experiment todo candidates",
        "extract_next_focus": "asking Gemini for next-meeting focus candidates",
        "verify_candidates": "running deterministic validation",
        "reduce_patch": "merging verified candidates into partial patch",
        "normalize_and_persist": "normalizing memory and writing SQLite unless dry-run",
        "final_report": "writing final research report",
    }
    end_actions = {
        "load_inputs": "graph state ready",
        "plan_next_window": "planner response parsed",
        "read_window": "transcript window loaded",
        "segment_window": "idea units parsed",
        "extract_meeting_window": "meeting summary candidates parsed",
        "extract_action_items": "action item candidates parsed",
        "extract_method_changes": "method change candidates parsed",
        "extract_experiment_todos": "experiment todo candidates parsed",
        "extract_next_focus": "next focus candidates parsed",
        "verify_candidates": "candidate validation complete",
        "reduce_patch": "partial patch ready",
        "normalize_and_persist": "memory update complete",
        "final_report": "research report written",
    }
    if phase == "start":
        return start_actions.get(node, "")
    if phase == "end":
        return end_actions.get(node, "")
    return ""


def _brief_progress_summary(summary: dict[str, object]) -> str:
    allowed = (
        "units",
        "needs_more_context",
        "verified",
        "rejected",
        "persisted",
        "error",
    )
    parts: list[str] = []
    for key in allowed:
        if key in summary:
            parts.append(f"{key}={summary[key]}")
    memory = summary.get("memory")
    if isinstance(memory, dict):
        version = memory.get("memory_version")
        meetings = memory.get("meeting_window_count")
        actions = memory.get("action_items_count")
        parts.append(f"memory_version={version}")
        parts.append(f"meeting_window={meetings}")
        parts.append(f"action_items={actions}")
    for key, value in summary.items():
        if key in allowed or key == "memory":
            continue
        if isinstance(value, (int, float, str, bool)):
            parts.append(f"{key}={value}")
    if not parts:
        return ""
    return "summary=" + ",".join(parts)


def main() -> None:
    args = parse_args()

    transcript_path = Path(args.transcript).resolve()
    db_path = Path(args.db).resolve()
    transcript_db_path = Path(args.transcript_db).resolve()
    memory_json_path = Path(args.memory_json).resolve()
    checkpoint_db_path = Path(args.checkpoint_db).resolve()
    research_log_dir = Path(args.research_log_dir).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve() if args.snapshot_dir else None
    db_snapshot_dir = (
        Path(args.db_snapshot_dir).resolve() if args.db_snapshot_dir else None
    )

    if not transcript_path.exists():
        raise RuntimeError(f"Transcript file not found: {transcript_path}")

    meeting_id = transcript_path.stem
    source_file = str(transcript_path)

    log_path: Path | None = None
    if args.log_dir:
        log_dir = Path(args.log_dir).resolve()
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"{timestamp}_{meeting_id}.log"
        log_path.write_text("", encoding="utf-8")

    def emit_line(line: str) -> None:
        if not args.quiet:
            print(line, flush=True)
        if log_path is not None:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def log(message: str) -> None:
        emit_line(f"[update_memory] {message}")

    if log_path is not None:
        log(f"log file: {log_path}")
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
    if args.memory_json != "short_term/current_memory.json":
        log("--memory-json is deprecated and ignored; JSON is human-readable export only")
    if args.no_bootstrap_json:
        log("--no-bootstrap-json is deprecated and ignored; JSON bootstrap is disabled")
    if args.mirror_json:
        log("--mirror-json is deprecated and ignored; JSON mirror writes are disabled")
    log("loading memory source from sqlite only")
    current_memory = load_memory_from_sqlite(db_path)
    memory_source = "sqlite"
    log(
        f"memory loaded from={memory_source} "
        f"version={int(current_memory.get('memory_version', 0) or 0)} "
        f"meeting_history={len(current_memory.get('meeting_history_ids', []))}"
    )
    log("loading Google Gen AI client config")
    genai_config = load_genai_config()
    log(f"using {describe_genai_config(genai_config)}")
    if args.max_tool_rounds < 0:
        raise RuntimeError("--max-tool-rounds must be >= 0")
    if args.max_tool_rounds:
        log("--max-tool-rounds is deprecated and ignored by LangGraph mode")

    log(f"starting GenAI update (model={args.model}, meeting_id={meeting_id})")
    transcript_overview = load_transcript_overview(
        db_path=transcript_db_path,
        meeting_id=meeting_id,
    )

    def emit_langgraph_progress(event: dict[str, object]) -> None:
        emit_line(format_langgraph_progress(event))

    updated_memory, research_run_dir = run_short_term_langgraph_update(
        model_name=args.model,
        client_config=genai_config,
        current_memory=current_memory,
        memory_source=memory_source,
        meeting_id=meeting_id,
        source_file=source_file,
        db_path=db_path,
        transcript_db_path=transcript_db_path,
        transcript_overview=transcript_overview,
        transcript_line_count=transcript_line_count,
        checkpoint_db_path=checkpoint_db_path,
        research_log_dir=research_log_dir,
        log_level=args.log_level,
        keep_full_prompts=args.keep_full_prompts,
        chunk_size=args.chunk_size,
        max_lookback_lines=args.max_lookback_lines,
        max_lookahead_lines=args.max_lookahead_lines,
        dry_run=args.dry_run,
        progress_callback=emit_langgraph_progress,
    )
    log(f"GenAI LangGraph update completed (research_log={research_run_dir})")

    if args.dry_run:
        log("dry-run enabled, skip DB snapshots and JSON snapshot files")
        if log_path is not None:
            emit_line(json.dumps(updated_memory, ensure_ascii=False, indent=2))
        else:
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

    snapshot_tag = meeting_id
    if snapshot_dir is not None:
        snapshot_name = f"{snapshot_tag}.json"
        snapshot_path = snapshot_dir / snapshot_name
        save_json(snapshot_path, persisted_memory)
        emit_line(f"JSON snapshot saved: {snapshot_path}")

    if db_snapshot_dir is not None:
        db_snapshot_path = db_snapshot_dir / f"{snapshot_tag}.db"
        export_db_snapshot(db_path=db_path, snapshot_path=db_snapshot_path)
        emit_line(f"DB file snapshot saved: {db_snapshot_path}")

    emit_line(f"Updated memory DB: {db_path}")
    emit_line(f"Loaded initial memory from: {memory_source}")
    emit_line(f"DB snapshot_id={snapshot_id}")
    emit_line(f"memory_version={persisted_memory['memory_version']}")
    emit_line(
        "meeting_window="
        f"{len(persisted_memory['meeting_window'])} "
        f"action_items={len(persisted_memory['action_items'])}"
    )
    if log_path is not None:
        emit_line(f"Log saved: {log_path}")


if __name__ == "__main__":
    main()
