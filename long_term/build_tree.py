"""Batch bridge: process ALL Bmr*.mrt transcripts and save to tree.json.

Usage:
    uv run build_tree.py                    # process all, auto-update L2/L3 after each meeting
    uv run build_tree.py --dry-run          # print stats only
    uv run build_tree.py --resume           # skip meetings already in tree.json
    uv run build_tree.py --no-auto-summarize  # L1 only, skip L2/L3 generation
    uv run build_tree.py --phase-size 4     # meetings per phase (default: 4)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from copy import deepcopy

from bridge import (
    call_gemini_bridge,
    collect_existing_topics,
    insert_meeting_into_tree,
    normalize_memory_objects,
)
from io_utils import load_env, load_tree, save_json, utc_now_iso
from schema import DEFAULT_TREE
from summarize import summarize_phase, update_project_profile
from transcript_utils import infer_meeting_date, mrt_to_text


# ===================================================================
# CLI
# ===================================================================

def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description="Batch bridge all Bmr transcripts.")
    p.add_argument(
        "--transcript-dir",
        default=str(project_root / "ICSI_original_transcripts" / "transcripts"),
        help="Directory containing .mrt files.",
    )
    p.add_argument(
        "--tree",
        default=str(project_root / "long_term" / "tree.json"),
        help="Output tree JSON path.",
    )
    p.add_argument(
        "--snapshot-dir",
        default=str(project_root / "long_term" / "snapshots"),
        help="Snapshot directory.",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=15000,
        help="Max transcript chars per meeting (truncate to save tokens).",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip meetings already present in tree.json.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List files to process without calling LLM.",
    )
    p.add_argument(
        "--no-auto-summarize",
        action="store_true",
        help="Skip automatic L2/L3 generation after each meeting (L1 only).",
    )
    p.add_argument(
        "--phase-size",
        type=int,
        default=4,
        help="Number of meetings per L2 phase (default: 4).",
    )
    p.add_argument(
        "--meetings",
        nargs="+",
        metavar="ID",
        help=(
            "Specify which meetings to process. "
            "Accepts individual IDs (Bmr001 Bmr003), "
            "a range (Bmr001:Bmr010), or both mixed. "
            "Example: --meetings Bmr001:Bmr005 Bmr009"
        ),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    transcript_dir = Path(args.transcript_dir).resolve()
    tree_path = Path(args.tree).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve()

    mrt_files = sorted(transcript_dir.glob("Bmr*.mrt"))
    if not mrt_files:
        print(f"No Bmr*.mrt files found in {transcript_dir}")
        sys.exit(1)

    # ── --meetings filter ─────────────────────────────────────────────────
    if args.meetings:
        all_stems = [f.stem for f in mrt_files]
        wanted: set[str] = set()
        for token in args.meetings:
            if ":" in token:
                start_id, end_id = token.split(":", 1)
                in_range = False
                for stem in all_stems:
                    if stem == start_id:
                        in_range = True
                    if in_range:
                        wanted.add(stem)
                    if stem == end_id:
                        in_range = False
                        break
                if start_id not in all_stems:
                    print(f"Warning: range start '{start_id}' not found, skipping.")
                if end_id not in all_stems:
                    print(f"Warning: range end '{end_id}' not found.")
            else:
                if token not in all_stems:
                    print(f"Warning: meeting '{token}' not found, skipping.")
                else:
                    wanted.add(token)
        mrt_files = [f for f in mrt_files if f.stem in wanted]
        print(f"--meetings filter applied: {len(mrt_files)} meetings selected")

    print(f"Found {len(mrt_files)} Bmr transcripts to consider")

    if args.resume:
        tree = load_tree(tree_path)
        existing_ids = {m["meeting_id"] for m in tree.get("meetings", [])}
        print(f"Resume mode: {len(existing_ids)} meetings already in tree")
    else:
        tree = deepcopy(DEFAULT_TREE)
        existing_ids = set()

    to_process = [f for f in mrt_files if f.stem not in existing_ids]
    print(f"To process: {len(to_process)} meetings")

    if args.dry_run:
        for f in to_process:
            text = mrt_to_text(f)
            print(f"  {f.stem}: {len(text)} chars")
        return

    api_key = load_env()
    total_objects = 0
    failed: list[str] = []

    for i, mrt_path in enumerate(to_process, 1):
        meeting_id = mrt_path.stem
        transcript_text = mrt_to_text(mrt_path)
        if len(transcript_text) > args.max_chars:
            transcript_text = transcript_text[: args.max_chars] + "\n... (truncated)"

        print(
            f"\n[{i}/{len(to_process)}] {meeting_id} "
            f"({len(transcript_text)} chars)...",
            end=" ",
            flush=True,
        )

        try:
            existing_topics = collect_existing_topics(tree)
            llm_output = call_gemini_bridge(
                model_name="gemini-2.5-flash",
                api_key=api_key,
                transcript=transcript_text,
                meeting_id=meeting_id,
                existing_topics=existing_topics,
            )
            raw_objects = llm_output.get("memory_objects", [])
            memory_objects = normalize_memory_objects(raw_objects, meeting_id)
            meeting_date = infer_meeting_date(mrt_path)
            insert_meeting_into_tree(
                tree=tree,
                meeting_id=meeting_id,
                source_file=str(mrt_path),
                timestamp=utc_now_iso(),
                memory_objects=memory_objects,
                meeting_date=meeting_date,
            )
            total_objects += len(memory_objects)
            print(f"✓ {len(memory_objects)} objects")
        except Exception as exc:
            print(f"✗ ERROR: {exc}")
            failed.append(meeting_id)
            # Save after every attempt (crash-safe)
            save_json(tree_path, tree)
            continue

        # ── Auto L2 / L3 update ──────────────────────────────────────────
        if not args.no_auto_summarize:
            all_meeting_ids = [
                m["meeting_id"]
                for m in sorted(tree.get("meetings", []), key=lambda x: x["meeting_id"])
            ]
            n = len(all_meeting_ids)
            phase_size = args.phase_size
            phase_index = (n - 1) // phase_size          # 0-based phase index
            phase_number = phase_index + 1
            phase_id = f"P-{phase_number:03d}"
            # Only meetings accumulated so far within this phase
            phase_meeting_ids = all_meeting_ids[phase_index * phase_size : n]

            print(
                f"  → L2 {phase_id} "
                f"[{', '.join(phase_meeting_ids)}]...",
                end=" ",
                flush=True,
            )
            try:
                phase_node = summarize_phase(
                    model_name="gemini-2.5-flash",
                    api_key=api_key,
                    tree=tree,
                    phase_id=phase_id,
                    time_start=phase_meeting_ids[0],
                    time_end=phase_meeting_ids[-1],
                    meeting_ids=phase_meeting_ids,
                )
                l2_snap_name = f"{phase_id}__{meeting_id}.json"
                save_json(snapshot_dir / "L2" / l2_snap_name, phase_node)
                print(f"✓ → {l2_snap_name}", end="  ")
            except Exception as exc:
                print(f"✗ L2 ERROR: {exc}", end="  ")

            print("→ L3...", end=" ", flush=True)
            try:
                profile = update_project_profile(
                    model_name="gemini-2.5-flash",
                    api_key=api_key,
                    tree=tree,
                )
                l3_snap_name = f"{meeting_id}.json"
                save_json(snapshot_dir / "L3" / l3_snap_name, profile)
                print(f"✓ → {l3_snap_name}")
            except Exception as exc:
                print(f"✗ L3 ERROR: {exc}")

        # Save after every meeting (crash-safe, doubles as resume checkpoint)
        save_json(tree_path, tree)

    # Final snapshot
    snap_name = f"{time.strftime('%Y%m%d_%H%M%S')}_batch_all.json"
    save_json(snapshot_dir / snap_name, tree)

    print("\n" + "=" * 60)
    print(f"Done. {len(to_process) - len(failed)}/{len(to_process)} succeeded")
    print(f"Total memory objects: {total_objects}")
    print(f"Tree version: {tree['tree_version']}")
    print(f"Saved: {tree_path}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
