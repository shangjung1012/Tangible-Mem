from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .store import DEFAULT_SHARE_MEM_ROOT, load_share_tree
    from .topic_view import (
        SUPPORTED_TOPIC_VIEW_MODES,
        TopicViewHashMismatchError,
        build_topic_view_outputs,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from store import DEFAULT_SHARE_MEM_ROOT, load_share_tree  # type: ignore
    from topic_view import (  # type: ignore
        SUPPORTED_TOPIC_VIEW_MODES,
        TopicViewHashMismatchError,
        build_topic_view_outputs,
    )

DEFAULT_MODEL = "gemini-2.5-pro"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build append-only topic-tree view from share_mem L1 evidence."
    )
    parser.add_argument(
        "--tree",
        default=str(DEFAULT_SHARE_MEM_ROOT / "tree.json"),
        help="Path to share_mem tree.json.",
    )
    parser.add_argument(
        "--output-root",
        default="",
        help="Output root for topic view files. Defaults to the tree parent.",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(SUPPORTED_TOPIC_VIEW_MODES),
        default="hybrid",
        help="Topic assignment/update mode.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Reserved Gemini model option for hybrid topic updates.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show meetings and files that would be written without writing outputs.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip per-meeting topic updates whose source hash still matches.",
    )
    parser.add_argument(
        "--clean-topic-view",
        action="store_true",
        help="Remove topic view outputs before rebuilding.",
    )
    parser.add_argument(
        "--force-meeting",
        action="append",
        default=[],
        help="Rebuild topic update for one meeting_id. Can be passed multiple times.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    tree_path = Path(args.tree).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else tree_path.parent
    tree = load_share_tree(output_root, tree_path=tree_path)
    try:
        result = build_topic_view_outputs(
            root=output_root,
            tree=tree,
            mode=str(args.mode),
            resume=bool(args.resume),
            clean_topic_view=bool(args.clean_topic_view),
            force_meetings={str(item) for item in args.force_meeting},
            dry_run=bool(args.dry_run),
            model=str(args.model),
        )
    except TopicViewHashMismatchError as exc:
        raise SystemExit(str(exc)) from exc

    if args.dry_run:
        print("share_mem topic-tree dry run")
        print(f"Tree: {tree_path}")
        print(f"Output root: {output_root}")
        for meeting_id in result["meeting_ids"]:
            print(f"  {meeting_id}")
        return

    print(
        "[share_mem] topic-tree refreshed: "
        f"{result['topic_count']} topics, "
        f"{result['topic_event_count']} topic events, "
        f"{result['processed_meeting_count']} processed, "
        f"{result['skipped_meeting_count']} skipped",
        flush=True,
    )
    print(f"Topic tree: {result['topic_tree_path']}")
    print(f"Topic index: {result['topic_index_path']}")


if __name__ == "__main__":
    main()
