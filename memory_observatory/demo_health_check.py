from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_observatory.services.data_loader import REPO_ROOT
from memory_observatory.services.demo_health import build_demo_health


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Memory Observatory demo readiness.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Repository root to inspect.")
    parser.add_argument("--dataset", default="icsi", help="Dataset id to check. Defaults to icsi.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero for warnings as well as failures.",
    )
    args = parser.parse_args(argv)

    try:
        health = build_demo_health(Path(args.repo_root), dataset_id=args.dataset)
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(health, ensure_ascii=False, indent=2))
    if health.get("status") == "fail":
        return 1
    if args.strict and health.get("status") != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
