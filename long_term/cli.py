"""Unified CLI entrypoint for long-term memory workflows."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    module_path: str
    description: str


COMMANDS: dict[str, CommandSpec] = {
    "bridge": CommandSpec(
        module_path="bridge",
        description="從單一逐字稿建立 / 更新 L1 記憶。",
    ),
    "summarize": CommandSpec(
        module_path="summarize",
        description="建立 L2 phase 或更新 L3 profile。",
    ),
    "build-tree": CommandSpec(
        module_path="build_tree",
        description="批次處理 Bmr 逐字稿，必要時自動補 L2 / L3。",
    ),
    "rebuild-snapshots": CommandSpec(
        module_path="rebuild_snapshots",
        description="用既有 tree.json 重建 L2 / L3 snapshots。",
    ),
    "smoke-todo": CommandSpec(
        module_path="scripts.smoke_todo_recall",
        description="快速檢查 todo recall filter 是否正常。",
    ),
    "eval-injection": CommandSpec(
        module_path="scripts.eval_prompt_injection",
        description="比較 recall prompt injection 的效果。",
    ),
}

ALIASES = {
    "build": "build-tree",
    "rebuild": "rebuild-snapshots",
}


def _print_help() -> None:
    print("Long-term Memory CLI")
    print()
    print("Usage:")
    print("  uv run long_term/cli.py <command> [args...]")
    print()
    print("Commands:")
    for name, spec in COMMANDS.items():
        print(f"  {name:<18} {spec.description}")
    print()
    print("Examples:")
    print(
        "  uv run long_term/cli.py bridge --transcript "
        "ICSI_original_transcripts/transcripts/Bmr001.mrt"
    )
    print(
        "  uv run long_term/cli.py summarize phase "
        "--phase-id P-007 --time-start Bmr027 --time-end Bmr030 "
        "--meetings Bmr027 Bmr028 Bmr029 Bmr030"
    )
    print("  uv run long_term/cli.py build-tree --resume --phase-size 4")
    print("  uv run long_term/cli.py rebuild-snapshots --dry-run")
    print("  uv run long_term/cli.py smoke-todo")
    print()
    print("Tips:")
    print("  uv run long_term/cli.py help <command>   # pass through to that command's --help")
    print("  build / rebuild are available as shorter aliases")


def _resolve_command(name: str) -> str:
    return ALIASES.get(name, name)


def _dispatch(command: str, argv: list[str]) -> None:
    spec = COMMANDS[command]
    module = importlib.import_module(spec.module_path)
    main = getattr(module, "main", None)
    if not callable(main):
        raise RuntimeError(f"{spec.module_path} does not expose a callable main().")

    original_argv = sys.argv[:]
    sys.argv = [f"long_term {command}", *argv]
    try:
        main()
    finally:
        sys.argv = original_argv


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return

    if args[0] == "help":
        if len(args) == 1:
            _print_help()
            return
        command = _resolve_command(args[1])
        if command not in COMMANDS:
            print(f"Unknown command: {args[1]}", file=sys.stderr)
            raise SystemExit(2)
        _dispatch(command, ["--help"])
        return

    command = _resolve_command(args[0])
    if command not in COMMANDS:
        print(f"Unknown command: {args[0]}", file=sys.stderr)
        print(file=sys.stderr)
        _print_help()
        raise SystemExit(2)

    _dispatch(command, args[1:])


if __name__ == "__main__":
    main()
