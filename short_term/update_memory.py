from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from short_term.io_utils import (
    dedupe_keep_order,
    load_short_term_memory,
    normalize_str,
    normalize_str_list,
    save_json,
    utc_now_iso,
)
from short_term.merge import (
    GeminiMergeDecider,
    MergeDecider,
    apply_merge_decision,
    normalize_active_state_memory,
    select_candidate_units,
)
from short_term.schema import DEFAULT_MODEL_NAME, MEMORY_SCHEMA_VERSION
from short_term.snapshot_loader import load_snapshot_tree, select_latest_meeting

DEFAULT_MEMORY_JSON_PATH = Path(__file__).resolve().parent / "short_term_memory.json"
DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def _update_meeting_history(memory: dict[str, Any], meeting_id: str) -> None:
    memory["meeting_history_ids"] = dedupe_keep_order(
        normalize_str_list(memory.get("meeting_history_ids")) + [meeting_id]
    )


def _bump_untouched_units(memory: dict[str, Any], touched_unit_ids: set[str]) -> None:
    retained: list[dict[str, Any]] = []
    for unit in memory.get("units", []):
        unit_id = normalize_str(unit.get("unit_id"))
        if unit_id in touched_unit_ids:
            retained.append(unit)
            continue
        try:
            missed = int(unit.get("missed_meeting_count", 0) or 0) + 1
        except (TypeError, ValueError):
            missed = 1
        unit["missed_meeting_count"] = missed
        if missed < 2:
            retained.append(unit)
    memory["units"] = retained


def _memory_snapshot_name(meeting_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in meeting_id)
    return f"{safe or 'unknown'}.json"


def update_memory_from_snapshot(
    *,
    snapshot_path: Path | str,
    memory_json_path: Path | str = DEFAULT_MEMORY_JSON_PATH,
    snapshot_dir: Path | str = DEFAULT_SNAPSHOT_DIR,
    model_name: str | None = None,
    merge_timeout_s: float | None = None,
    merge_decider: MergeDecider | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    snapshot = Path(snapshot_path)
    memory_path = Path(memory_json_path)
    output_snapshot_dir = Path(snapshot_dir)
    tree = load_snapshot_tree(snapshot)
    meeting = select_latest_meeting(tree)
    meeting_id = normalize_str(meeting.get("meeting_id"))
    if not meeting_id:
        raise RuntimeError("latest meeting is missing meeting_id")

    memory = load_short_term_memory(memory_path)
    previous_version = int(memory.get("memory_version", 0) or 0)
    memory["schema_version"] = MEMORY_SCHEMA_VERSION
    _update_meeting_history(memory, meeting_id)

    decider = merge_decider or GeminiMergeDecider(
        model_name=model_name,
        timeout_s=merge_timeout_s,
    )
    touched_unit_ids: set[str] = set()
    objects = [
        obj
        for obj in meeting.get("memory_objects", [])
        if isinstance(obj, dict) and normalize_str(obj.get("obj_id"))
    ]

    for source_obj in objects:
        candidates = select_candidate_units(source_obj, memory)
        decision = decider(source_obj, candidates, meeting)
        unit = apply_merge_decision(
            memory=memory,
            source_obj=source_obj,
            meeting=meeting,
            decision=decision,
        )
        touched_unit_ids.add(normalize_str(unit.get("unit_id")))

    _bump_untouched_units(memory, touched_unit_ids)
    normalize_active_state_memory(memory, current_meeting_id=meeting_id)
    memory["units"] = sorted(
        memory.get("units", []),
        key=lambda unit: normalize_str(unit.get("unit_id")),
    )
    memory["memory_version"] = previous_version + 1
    memory["last_updated_utc"] = utc_now_iso()
    memory["last_updated_meeting_id"] = meeting_id
    memory["processed_snapshot_path"] = str(snapshot)

    if not dry_run:
        save_json(memory_path, memory)
        save_json(output_snapshot_dir / _memory_snapshot_name(meeting_id), memory)
    return memory


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update JSON short-term memory from one share_mem cumulative snapshot."
    )
    parser.add_argument(
        "--snapshot",
        required=True,
        help="Path to one share_mem/snapshots/*_bridge_<meeting>.json file.",
    )
    parser.add_argument(
        "--memory-json",
        default=str(DEFAULT_MEMORY_JSON_PATH),
        help="Canonical short-term memory JSON path.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=str(DEFAULT_SNAPSHOT_DIR),
        help="Directory for per-update short-term memory snapshots.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("GEMINI_MODEL", DEFAULT_MODEL_NAME),
        help=f"Gemini model name for merge decisions. Default: {DEFAULT_MODEL_NAME}.",
    )
    parser.add_argument(
        "--merge-timeout-s",
        type=float,
        default=None,
        help="Per-object Gemini merge timeout. Defaults to SHORT_TERM_MERGE_TIMEOUT_S or 60.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print updated memory without writing memory JSON or snapshots.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    memory = update_memory_from_snapshot(
        snapshot_path=args.snapshot,
        memory_json_path=args.memory_json,
        snapshot_dir=args.snapshot_dir,
        model_name=args.model,
        merge_timeout_s=args.merge_timeout_s,
        dry_run=args.dry_run,
    )
    print(json.dumps(memory, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
