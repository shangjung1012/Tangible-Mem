"""Active CLI entrypoint for long-term L2 and recall workflows."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    module_path: str
    description: str


COMMANDS: dict[str, CommandSpec] = {
    "build-l2-view": CommandSpec(
        module_path="build_l2_view",
        description="Build the L2 view from canonical share_mem L1 evidence.",
    ),
    "validate-l2-view": CommandSpec(
        module_path="validate_l2_view",
        description="Validate the generated L2 view and linked L1 evidence.",
    ),
}

LEGACY_COMMANDS = {
    "bridge",
    "summarize",
    "build-tree",
    "rebuild-snapshots",
    "smoke-todo",
    "eval-injection",
}

ALIASES = {
    "build-l2": "build-l2-view",
    "validate-l2": "validate-l2-view",
}

LEGACY_NOTE = (
    "Legacy temporal L1/L2/L3 commands were archived under "
    "long_term/archive/legacy_temporal_l2_l3/. New L2 work should read "
    "canonical L1 evidence from share_mem/."
)


def _print_help() -> None:
    print("Long-term Memory CLI")
    print()
    print("Usage:")
    print("  uv run long_term/cli.py <command> [args...]")
    print()
    print("Active commands:")
    for name, spec in COMMANDS.items():
        print(f"  {name:<18} {spec.description}")
    print()
    print("Archived legacy commands:")
    print("  bridge, summarize, build-tree, rebuild-snapshots, smoke-todo, eval-injection")
    print()
    print(LEGACY_NOTE)


def _resolve_command(name: str) -> str:
    return ALIASES.get(name, name)


def _legacy_exit(command: str) -> None:
    print(f"Archived legacy command: {command}", file=sys.stderr)
    print(LEGACY_NOTE, file=sys.stderr)
    raise SystemExit(2)


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
        if command in LEGACY_COMMANDS:
            _legacy_exit(command)
        if command not in COMMANDS:
            print(f"Unknown command: {args[1]}", file=sys.stderr)
            raise SystemExit(2)
        _dispatch(command, ["--help"])
        return

    command = _resolve_command(args[0])
    if command in LEGACY_COMMANDS:
        _legacy_exit(command)
    if command not in COMMANDS:
        print(f"Unknown command: {args[0]}", file=sys.stderr)
        print(file=sys.stderr)
        _print_help()
        raise SystemExit(2)

    _dispatch(command, args[1:])


if __name__ == "__main__":
    main()
