from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from .store import (
        DEFAULT_SHARE_MEM_ROOT,
        clean_generated_outputs,
        load_share_tree,
        refresh_share_mem_outputs,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from store import (  # type: ignore
        DEFAULT_SHARE_MEM_ROOT,
        clean_generated_outputs,
        load_share_tree,
        refresh_share_mem_outputs,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_TRANSCRIPT_DIR = REPO_ROOT / "meeting_recording" / "transcript" / "grace"
DEFAULT_MODEL = "gemini-2.5-pro"
GRACE_MEETING_YEAR = 2026


def discover_transcripts(transcript_dir: Path | str) -> list[Path]:
    return sorted(Path(transcript_dir).glob("*.txt"), key=lambda path: path.name)


def infer_grace_meeting_date(meeting_id: str) -> str:
    match = re.fullmatch(r"(\d{2})(\d{2})", str(meeting_id).strip())
    if not match:
        return ""
    month = int(match.group(1))
    day = int(match.group(2))
    try:
        datetime(GRACE_MEETING_YEAR, month, day)
    except ValueError:
        return ""
    return f"{GRACE_MEETING_YEAR:04d}-{month:02d}-{day:02d}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build canonical share_mem L1 store from Grace transcripts."
    )
    parser.add_argument(
        "--transcript-dir",
        default=str(DEFAULT_TRANSCRIPT_DIR),
        help="Directory containing Grace .txt transcripts.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_SHARE_MEM_ROOT),
        help="share_mem output root.",
    )
    parser.add_argument(
        "--mode",
        choices=["multi-agent"],
        default="multi-agent",
        help="L1 extraction mode. share_mem only supports multi-agent.",
    )
    parser.add_argument(
        "--dataset-profile",
        default="grace",
        help="Dataset profile passed to share_mem L1 bridge.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Gemini model passed to share_mem L1 bridge.",
    )
    parser.add_argument(
        "--taxonomy",
        choices=["v1", "v2-memory-roles"],
        default="v1",
        help="L1 taxonomy passed to the multi-agent bridge.",
    )
    parser.add_argument(
        "--include-legacy-type",
        action="store_true",
        help="Include legacy_type compatibility labels in experiment outputs.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove generated share_mem outputs before rebuilding.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List transcripts and output paths without calling the LLM.",
    )
    return parser.parse_args(argv)


def _run_bridge_for_transcript(
    *,
    transcript_path: Path,
    tree_path: Path,
    snapshot_dir: Path,
    research_log_dir: Path,
    dataset_profile: str,
    model: str,
    taxonomy: str = "v1",
    include_legacy_type: bool = False,
) -> None:
    from share_mem.l1 import bridge

    bridge_argv = [
        "--transcript",
        str(transcript_path),
        "--tree",
        str(tree_path),
        "--snapshot-dir",
        str(snapshot_dir),
        "--research-log-dir",
        str(research_log_dir),
        "--mode",
        "multi-agent",
        "--dataset-profile",
        dataset_profile,
        "--model",
        model,
        "--taxonomy",
        taxonomy,
    ]
    if include_legacy_type:
        bridge_argv.append("--include-legacy-type")
    meeting_date = infer_grace_meeting_date(transcript_path.stem)
    if meeting_date:
        bridge_argv.extend(["--meeting-date", meeting_date])

    bridge.main(bridge_argv)


def build_share_mem_tree(args: argparse.Namespace) -> dict:
    transcript_dir = Path(args.transcript_dir).resolve()
    output_root = Path(args.output_root).resolve()
    tree_path = output_root / "tree.json"
    snapshot_dir = output_root / "snapshots"
    research_log_dir = output_root / "research_logs"

    transcripts = discover_transcripts(transcript_dir)
    if not transcripts:
        raise RuntimeError(f"No .txt transcripts found in {transcript_dir}")

    if args.clean and not args.dry_run:
        clean_generated_outputs(output_root)

    if args.dry_run:
        return {
            "transcript_dir": str(transcript_dir),
            "output_root": str(output_root),
            "taxonomy": str(args.taxonomy),
            "include_legacy_type": bool(args.include_legacy_type),
            "transcripts": [path.name for path in transcripts],
        }

    for transcript_path in transcripts:
        print(f"[share_mem] multi-agent bridge: {transcript_path.name}", flush=True)
        _run_bridge_for_transcript(
            transcript_path=transcript_path,
            tree_path=tree_path,
            snapshot_dir=snapshot_dir,
            research_log_dir=research_log_dir,
            dataset_profile=str(args.dataset_profile),
            model=str(args.model),
            taxonomy=str(args.taxonomy),
            include_legacy_type=bool(args.include_legacy_type),
        )

    tree = load_share_tree(output_root)
    manifest = refresh_share_mem_outputs(
        root=output_root,
        tree=tree,
        source_transcript_dir=transcript_dir,
    )
    print(
        "[share_mem] refreshed outputs: "
        f"{manifest['meeting_count']} meetings, {manifest['object_count']} L1 objects",
        flush=True,
    )
    return manifest


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = build_share_mem_tree(args)
    if args.dry_run:
        print("share_mem dry run")
        print(f"Transcript dir: {result['transcript_dir']}")
        print(f"Output root: {result['output_root']}")
        print(f"Taxonomy: {result['taxonomy']}")
        print(f"Include legacy type: {result['include_legacy_type']}")
        for name in result["transcripts"]:
            print(f"  {name}")


if __name__ == "__main__":
    main()
