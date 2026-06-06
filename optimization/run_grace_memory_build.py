from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.output_roots import resolve_memory_run_root


def build_grace_commands(*, output_base: Path, run_id: str) -> list[list[str]]:
    run_root = resolve_memory_run_root(
        base_root=output_base,
        dataset="grace",
        run_kind="grace_full",
        run_id=run_id,
    )
    share_mem_root = run_root / "share_mem_raw"
    l2_l3_root = run_root / "l2_l3"
    return [
        [
            "uv",
            "run",
            "share_mem/build_tree.py",
            "--transcript-dir",
            "meeting_recording/transcript/grace",
            "--output-root",
            str(share_mem_root),
            "--mode",
            "multi-agent",
            "--dataset-profile",
            "grace",
            "--model",
            "gemini-2.5-pro",
            "--taxonomy",
            "v2-memory-roles",
            "--include-legacy-type",
            "--clean",
        ],
        [
            "uv",
            "run",
            "python",
            "optimization/long_term_v2/build_view.py",
            "--share-mem-root",
            str(share_mem_root),
            "--profile",
            "optimization/long_term_v2/profiles/mentor_mentee.yaml",
            "--out",
            str(l2_l3_root),
            "--mode",
            "deterministic",
            "--clean",
        ],
        [
            "uv",
            "run",
            "python",
            "optimization/long_term_v2/validate_view.py",
            "--run-root",
            str(l2_l3_root),
        ],
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate isolated Grace memory rebuild commands.")
    parser.add_argument("--output-base", default="memory_outputs")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    commands = build_grace_commands(output_base=Path(args.output_base), run_id=str(args.run_id))
    if not args.execute:
        print("DRY RUN: isolated Grace rebuild commands")
        for index, command in enumerate(commands, start=1):
            print(f"{index}. {' '.join(command)}")
        return
    for command in commands:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
