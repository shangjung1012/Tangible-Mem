"""Rebuild L2/L3 snapshots from existing L1 data in tree.json.

For each meeting added incrementally (step 1..N), this script:
  - Generates L2 phase summary for the current phase (cumulative meetings in that phase)
  - Generates L3 project profile from all accumulated phases
  - Saves individual snapshot files

Output file structure:
  snapshots/L2/P-001__Bmr001.json   ← Phase 1, after meeting 1
  snapshots/L2/P-001__Bmr002.json   ← Phase 1, after meetings 1+2
  snapshots/L2/P-001__Bmr003.json   ← Phase 1, after meetings 1+2+3
  snapshots/L2/P-001__Bmr005.json   ← Phase 1, after meetings 1+2+3+4 (complete)
  snapshots/L2/P-002__Bmr006.json   ← Phase 2, after meeting 5 only
  ...
  snapshots/L3/Bmr001.json          ← L3 after meeting 1
  snapshots/L3/Bmr002.json          ← L3 after meetings 1+2
  ...
  snapshots/L3/Bmr031.json          ← L3 after all meetings

Usage:
    uv run rebuild_snapshots.py
    uv run rebuild_snapshots.py --phase-size 4   # default
    uv run rebuild_snapshots.py --dry-run        # show plan only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, TypeVar

from io_utils import load_api_keys, load_tree, save_json
from schema import DEFAULT_TREE
from summarize import summarize_phase, update_project_profile

T = TypeVar("T")


def _with_retry(fn: Callable[[], T], max_retries: int = 3, base_delay: float = 10.0) -> T:
    """Call fn(), retrying on 503 errors with exponential backoff."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            msg = str(exc)
            is_503 = "503" in msg or "UNAVAILABLE" in msg
            if is_503 and attempt < max_retries:
                wait = base_delay * (2 ** attempt)  # 10s, 20s, 40s
                print(f"\n    503 — retrying in {wait:.0f}s (attempt {attempt + 1}/{max_retries})...", end=" ", flush=True)
                time.sleep(wait)
            else:
                raise


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(
        description="Rebuild L2/L3 snapshots from existing L1 data."
    )
    p.add_argument(
        "--tree",
        default=str(project_root / "long_term" / "tree.json"),
        help="Path to tree.json with L1 data.",
    )
    p.add_argument(
        "--snapshot-dir",
        default=str(project_root / "long_term" / "snapshots"),
        help="Root snapshot directory.",
    )
    p.add_argument(
        "--phase-size",
        type=int,
        default=4,
        help="Number of meetings per L2 phase (default: 4).",
    )
    p.add_argument(
        "--model",
        default="gemini-2.5-flash",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show processing plan without calling LLM.",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip steps where both L2 and L3 snapshot files already exist.",
    )
    p.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries on 503 errors (default: 3).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    tree_path = Path(args.tree).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve()
    l2_snap_dir = snapshot_dir / "L2"
    l3_snap_dir = snapshot_dir / "L3"

    source_tree = load_tree(tree_path)
    all_meetings = sorted(
        source_tree.get("meetings", []),
        key=lambda m: m["meeting_id"],
    )

    if not all_meetings:
        print("No meetings found in tree.json. Run build_tree.py first.")
        sys.exit(1)

    total = len(all_meetings)
    phase_size = args.phase_size
    total_l2_calls = total
    total_l3_calls = total
    print(f"Found {total} meetings. Phase size: {phase_size}")
    print(
        f"Will generate {total_l2_calls} L2 + {total_l3_calls} L3 snapshots "
        f"({total_l2_calls + total_l3_calls} LLM calls total).\n"
    )

    if args.dry_run:
        for step in range(1, total + 1):
            meeting_id = all_meetings[step - 1]["meeting_id"]
            phase_index = (step - 1) // phase_size
            phase_id = f"P-{phase_index + 1:03d}"
            phase_meetings = [
                m["meeting_id"]
                for m in all_meetings[phase_index * phase_size : step]
            ]
            print(
                f"  Step {step:2d}: {meeting_id}"
                f"  L2={phase_id}[{', '.join(phase_meetings)}]"
                f" → {phase_id}__{meeting_id}.json"
                f"  L3 → {meeting_id}.json"
            )
        return

    api_key = load_api_keys()

    # running_tree accumulates phases across steps so L3 sees all prior phases
    running_tree = deepcopy(DEFAULT_TREE)

    for step in range(1, total + 1):
        meeting = all_meetings[step - 1]
        meeting_id = meeting["meeting_id"]
        running_tree["meetings"].append(deepcopy(meeting))

        phase_index = (step - 1) // phase_size
        phase_id = f"P-{phase_index + 1:03d}"
        # Meetings in this phase up to (and including) the current step
        phase_meeting_ids = [
            m["meeting_id"]
            for m in all_meetings[phase_index * phase_size : step]
        ]

        l2_snap_name = f"{phase_id}__{meeting_id}.json"
        l3_snap_name = f"{meeting_id}.json"
        l2_exists = (l2_snap_dir / l2_snap_name).exists()
        l3_exists = (l3_snap_dir / l3_snap_name).exists()

        if args.resume and l2_exists and l3_exists:
            print(f"[{step:2d}/{total}] {meeting_id}  (skipped — both snapshots exist)")
            # Still need to load existing phase into running_tree for L3 continuity
            existing_phase = json.loads((l2_snap_dir / l2_snap_name).read_text())
            existing_profile = json.loads((l3_snap_dir / l3_snap_name).read_text())
            phases = running_tree.get("phases", [])
            phases_by_id = {p["phase_id"]: i for i, p in enumerate(phases)}
            if phase_id in phases_by_id:
                phases[phases_by_id[phase_id]] = existing_phase
            else:
                phases.append(existing_phase)
            running_tree["phases"] = phases
            running_tree["project_profile"] = existing_profile
            continue

        print(
            f"\n[{step:2d}/{total}] {meeting_id}"
            f"  → L2 {phase_id}[{', '.join(phase_meeting_ids)}]...",
            end=" ",
            flush=True,
        )

        # ── L2: summarize current phase cumulative up to this step ─────────
        try:
            phase_node = _with_retry(
                lambda: summarize_phase(
                    model_name=args.model,
                    api_key=api_key,
                    tree=running_tree,
                    phase_id=phase_id,
                    time_start=phase_meeting_ids[0],
                    time_end=phase_meeting_ids[-1],
                    meeting_ids=phase_meeting_ids,
                ),
                max_retries=args.max_retries,
            )
            save_json(l2_snap_dir / l2_snap_name, phase_node)
            print(f"✓ → {l2_snap_name}", end="  ")
        except Exception as exc:
            print(f"✗ L2 ERROR: {exc}", end="  ")

        # ── L3: update profile from all accumulated phases ──────────────────
        print("→ L3...", end=" ", flush=True)
        try:
            profile = _with_retry(
                lambda: update_project_profile(
                    model_name=args.model,
                    api_key=api_key,
                    tree=running_tree,
                ),
                max_retries=args.max_retries,
            )
            save_json(l3_snap_dir / l3_snap_name, profile)
            print(f"✓ → {l3_snap_name}")
        except Exception as exc:
            print(f"✗ L3 ERROR: {exc}")

    save_json(tree_path, running_tree)

    print("\n" + "=" * 60)
    print("Done!")
    print(f"  Final tree → {tree_path}")
    print(f"  L2 snapshots ({total}) → {l2_snap_dir}/")
    print(f"  L3 snapshots ({total}) → {l3_snap_dir}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
