"""Reserved entrypoint for building the active long_term L2 view."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Build an L2 view from canonical share_mem L1 evidence."
    )
    parser.add_argument(
        "--share-mem-root",
        default=str(project_root / "share_mem"),
        help="Root containing share_mem tree.json and meetings/.",
    )
    parser.add_argument(
        "--output-root",
        default=str(project_root / "long_term" / "l2"),
        help="Output root for generated L2 view artifacts.",
    )
    parser.add_argument(
        "--mode",
        choices=["deterministic", "hybrid"],
        default="hybrid",
        help="Assignment mode for the future L2 builder.",
    )
    parser.add_argument("--model", default=None, help="Gemini model for hybrid mode.")
    parser.add_argument("--clean", action="store_true", help="Clean generated L2 outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without writing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    parse_args(argv)
    raise SystemExit(
        "long_term build-l2-view is reserved for the next L2 implementation. "
        "This archive cleanup only prepares the active CLI surface."
    )


if __name__ == "__main__":
    main()
