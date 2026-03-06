from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from io_utils import load_env, load_memory, print_json_safe, save_json
from llm_client import generate_updated_memory
from normalizer import normalize_memory
from schema import DEFAULT_MODEL_NAME


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update short-term memory from one transcript.")
    parser.add_argument(
        "--transcript",
        required=True,
        help="Path to one meeting transcript file.",
    )
    parser.add_argument(
        "--memory",
        default="short_term/current_memory.json",
        help="Path to current short-term memory JSON.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="short_term/snapshots",
        help="Directory for versioned memory snapshots.",
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    transcript_path = Path(args.transcript).resolve()
    memory_path = Path(args.memory).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve()

    if not transcript_path.exists():
        raise RuntimeError(f"Transcript file not found: {transcript_path}")

    meeting_id = transcript_path.stem
    source_file = str(transcript_path)
    transcript = transcript_path.read_text(encoding="utf-8")
    current_memory = load_memory(memory_path)
    api_key = load_env()

    llm_output = generate_updated_memory(
        model_name=args.model,
        api_key=api_key,
        transcript=transcript,
        current_memory=current_memory,
        meeting_id=meeting_id,
        source_file=source_file,
    )

    normalized = normalize_memory(
        updated_memory=llm_output,
        previous_memory=current_memory,
        meeting_id=meeting_id,
        source_file=source_file,
    )

    if args.dry_run:
        print_json_safe(normalized)
        return

    save_json(memory_path, normalized)
    snapshot_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_meeting_{meeting_id}.json"
    snapshot_path = snapshot_dir / snapshot_name
    save_json(snapshot_path, normalized)

    print(f"Updated memory: {memory_path}")
    print(f"Snapshot saved: {snapshot_path}")
    print(f"memory_version={normalized['memory_version']}")
    print(
        f"meeting_window={len(normalized['meeting_window'])} action_items={len(normalized['action_items'])}"
    )


if __name__ == "__main__":
    main()
