"""Reserved entrypoint for validating the active long_term L2 view."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Validate a generated L2 view against canonical share_mem L1 evidence."
    )
    parser.add_argument(
        "--share-mem-root",
        default=str(project_root / "share_mem"),
        help="Root containing canonical share_mem L1 outputs.",
    )
    parser.add_argument(
        "--root",
        default=str(project_root / "long_term" / "l2"),
        help="Root containing generated L2 view artifacts.",
    )
    parser.add_argument(
        "--out",
        default=str(project_root / "long_term" / "l2" / "validation"),
        help="Validation output directory.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    parse_args(argv)
    raise SystemExit(
        "long_term validate-l2-view is reserved for the next L2 implementation. "
        "This archive cleanup only prepares the active CLI surface."
    )


if __name__ == "__main__":
    main()
