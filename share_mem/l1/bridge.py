"""Bridge multi-agent L1 extraction into a share_mem-style tree."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .dataset_profiles import dataset_profile_choices, resolve_dataset_profile
from .io_utils import load_api_keys, load_tree, print_json_safe, save_json, utc_now_iso
from .l1_quality import (
    load_l1_quality_index,
    merge_l1_quality_index,
    quality_index_default_path,
    remove_l1_quality_for_meeting,
)
from .memory_activity import (
    build_memory_activity_update,
    load_memory_activity_index,
    memory_activity_default_path,
    merge_memory_activity_index,
    remove_memory_activity_for_meeting,
)
from .memory_relations import (
    build_cross_meeting_relations,
    memory_relations_default_path,
    merge_memory_relations_index,
    remove_memory_relations_for_meeting,
)
from .multi_agent_pipeline import run_multi_agent_l1_pipeline
from .prior_context import build_prior_context_pack
from .schema import DEFAULT_MODEL_NAME
from .taxonomy import CONTENT_LANGUAGE_TRADITIONAL_ZH


def collect_existing_topics(tree: dict[str, Any]) -> list[str]:
    """Collect all known topic keywords from existing L1 memory objects."""
    topics: set[str] = set()
    for meeting in tree.get("meetings", []):
        for obj in meeting.get("memory_objects", []):
            for topic in obj.get("related_topics", []):
                topics.add(str(topic))
    return sorted(topics)


def insert_meeting_into_tree(
    *,
    tree: dict[str, Any],
    meeting_id: str,
    source_file: str,
    timestamp: str,
    memory_objects: list[dict[str, Any]],
    meeting_date: str = "",
) -> dict[str, Any]:
    """Insert or update an L1 meeting node in the tree."""
    meetings: list[dict[str, Any]] = tree.get("meetings", [])

    existing_idx: int | None = None
    for i, meeting in enumerate(meetings):
        if meeting.get("meeting_id") == meeting_id:
            existing_idx = i
            break

    meeting_node: dict[str, Any] = {
        "meeting_id": meeting_id,
        "timestamp": timestamp,
        "meeting_date": meeting_date,
        "source_file": source_file,
        "phase_id": "",
        "memory_objects": memory_objects,
    }

    if existing_idx is not None:
        meeting_node["phase_id"] = meetings[existing_idx].get("phase_id", "")
        if not meeting_date:
            meeting_node["meeting_date"] = meetings[existing_idx].get("meeting_date", "")
        meetings[existing_idx] = meeting_node
    else:
        meetings.append(meeting_node)

    meetings.sort(key=lambda meeting: meeting.get("meeting_id", ""))
    tree["meetings"] = meetings
    tree["tree_version"] = int(tree.get("tree_version", 0) or 0) + 1
    tree["last_updated_utc"] = utc_now_iso()
    return tree


def resolve_model_name(requested_model: str | None) -> str:
    """Resolve CLI model after .env has been loaded by credential setup."""
    clean = str(requested_model or "").strip()
    if clean:
        return clean
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL_NAME)


def resolve_dataset_guidance_for_l1(
    *,
    dataset_profile: Any,
    content_language: str,
    force: bool = False,
) -> str:
    """Keep canonical Grace prompts stable while enabling dataset-specific probes.

    Grace is the checked-in canonical L1 corpus. New dataset guidance is useful
    for ICSI-style pilots, but silently adding it to Grace would change the next
    Grace extraction prompts. Grace can still opt in with force=True.
    """
    prompt_hint = str(getattr(dataset_profile, "prompt_hint", "") or "").strip()
    if not prompt_hint:
        return ""
    if force:
        return prompt_hint
    if (
        str(getattr(dataset_profile, "name", "") or "").strip().lower() == "grace"
        and content_language == CONTENT_LANGUAGE_TRADITIONAL_ZH
    ):
        return ""
    return prompt_hint


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge: extract L1 memory objects into share_mem."
    )
    parser.add_argument(
        "--transcript", required=True, help="Path to meeting transcript file."
    )
    parser.add_argument(
        "--tree",
        default="share_mem/tree.json",
        help="Path to share_mem tree JSON.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="share_mem/snapshots",
        help="Directory for versioned tree snapshots.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Gemini model name. Defaults to GEMINI_MODEL from .env, "
            f"or {DEFAULT_MODEL_NAME} if unset."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["multi-agent"],
        default="multi-agent",
        help="share_mem L1 extraction only supports the canonical multi-agent mode.",
    )
    parser.add_argument(
        "--dataset-profile",
        choices=dataset_profile_choices(),
        default="grace",
        help="Transcript preset label retained for build command compatibility.",
    )
    parser.add_argument(
        "--taxonomy",
        choices=["v1", "v2-memory-roles"],
        default="v1",
        help="L1 taxonomy to use. v1 remains the default canonical schema.",
    )
    parser.add_argument(
        "--include-legacy-type",
        action="store_true",
        help="When using a v2 experiment, include legacy_type compatibility labels.",
    )
    parser.add_argument(
        "--content-language",
        choices=["traditional_zh", "english"],
        default="traditional_zh",
        help=(
            "Language for human-facing L1 content. Defaults to traditional_zh "
            "for canonical Grace share_mem output."
        ),
    )
    parser.add_argument(
        "--use-dataset-guidance",
        action="store_true",
        help=(
            "Opt in to profile-specific prompt guidance even for canonical Grace. "
            "Non-Grace profiles use guidance by default."
        ),
    )
    parser.add_argument(
        "--research-log-dir",
        default="share_mem/research_logs",
        help="Directory for multi-agent stage artifacts.",
    )
    parser.add_argument(
        "--multi-agent-window-size",
        type=int,
        default=80,
        help="Primary transcript lines per context-planner window in multi-agent mode.",
    )
    parser.add_argument(
        "--multi-agent-lookback-lines",
        type=int,
        default=6,
        help="Context lookback lines for segmentation prompts.",
    )
    parser.add_argument(
        "--multi-agent-lookahead-lines",
        type=int,
        default=6,
        help="Context lookahead lines for segmentation prompts.",
    )
    parser.add_argument(
        "--multi-agent-previous-context",
        action="store_true",
        help=(
            "Experimental: pass compact read-only summaries from previous "
            "extraction packets into typed L1 agents."
        ),
    )
    parser.add_argument(
        "--timestamp",
        default="",
        help="Meeting timestamp (ISO 8601). Auto-generated if empty.",
    )
    parser.add_argument(
        "--meeting-date",
        default="",
        help="Real meeting date (YYYY-MM-DD) for recency scoring.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without writing tree, snapshots, or sidecars.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    transcript_path = Path(args.transcript).resolve()
    tree_path = Path(args.tree).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve()

    if not transcript_path.exists():
        raise RuntimeError(f"Transcript not found: {transcript_path}")

    meeting_id = transcript_path.stem
    source_file = str(transcript_path)
    transcript = transcript_path.read_text(encoding="utf-8")
    timestamp = args.timestamp or utc_now_iso()
    meeting_date = args.meeting_date

    tree = load_tree(tree_path)
    api_keys = load_api_keys()
    model_name = resolve_model_name(args.model)
    existing_topics = collect_existing_topics(tree)
    quality_path = quality_index_default_path(tree_path)
    relations_path = memory_relations_default_path(tree_path)
    activity_path = memory_activity_default_path(tree_path)
    existing_quality_index = load_l1_quality_index(quality_path)
    existing_activity_index = load_memory_activity_index(activity_path)
    dataset_profile = resolve_dataset_profile(
        transcript_path,
        requested_profile=args.dataset_profile,
    )
    prior_context_pack = build_prior_context_pack(
        tree=tree,
        meeting_id=meeting_id,
        transcript=transcript,
        quality_index=existing_quality_index,
        activity_index=existing_activity_index,
    )

    multi_agent_result = run_multi_agent_l1_pipeline(
        model_name=model_name,
        api_key=api_keys,
        transcript=transcript,
        meeting_id=meeting_id,
        source_file=source_file,
        timestamp=timestamp,
        meeting_date=meeting_date,
        existing_topics=existing_topics,
        prior_context_pack=prior_context_pack,
        research_log_dir=Path(args.research_log_dir).resolve(),
        window_size=args.multi_agent_window_size,
        lookback_lines=args.multi_agent_lookback_lines,
        lookahead_lines=args.multi_agent_lookahead_lines,
        previous_context_enabled=args.multi_agent_previous_context,
        taxonomy=args.taxonomy,
        include_legacy_type=args.include_legacy_type,
        content_language=args.content_language,
        dataset_guidance=resolve_dataset_guidance_for_l1(
            dataset_profile=dataset_profile,
            content_language=args.content_language,
            force=args.use_dataset_guidance,
        ),
    )
    memory_objects = multi_agent_result.memory_objects

    insert_meeting_into_tree(
        tree=tree,
        meeting_id=meeting_id,
        source_file=source_file,
        timestamp=timestamp,
        memory_objects=memory_objects,
        meeting_date=meeting_date,
    )
    persisted_node = next(
        (
            meeting
            for meeting in tree.get("meetings", [])
            if meeting.get("meeting_id") == meeting_id
        ),
        multi_agent_result.final_meeting_node,
    )
    save_json(multi_agent_result.run_dir / "final_meeting_node.json", persisted_node)

    combined_quality_index = {
        **existing_quality_index,
        **multi_agent_result.quality_index,
    }
    relation_updates = build_cross_meeting_relations(
        tree=tree,
        source_meeting=persisted_node,
        quality_index=combined_quality_index,
    )
    activity_update = build_memory_activity_update(
        tree=tree,
        meeting_id=meeting_id,
        existing_index=existing_activity_index,
        relation_updates=relation_updates,
    )
    save_json(multi_agent_result.run_dir / "cross_meeting_relations.json", relation_updates)
    save_json(
        multi_agent_result.run_dir / "memory_activity_update.json",
        {
            obj_id: meta
            for obj_id, meta in activity_update.items()
            if meta.get("meeting_id") == meeting_id
            or meta.get("last_touched_meeting_id") == meeting_id
        },
    )

    if args.dry_run:
        print_json_safe(tree)
        return

    save_json(tree_path, tree)
    snapshot_name = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_bridge_{meeting_id}.json"
    )
    save_json(snapshot_dir / snapshot_name, tree)

    remove_l1_quality_for_meeting(quality_path, meeting_id)
    existing_relations_index = remove_memory_relations_for_meeting(
        relations_path,
        meeting_id,
    )
    remove_memory_activity_for_meeting(activity_path, meeting_id)
    if multi_agent_result.quality_index:
        merged_quality = merge_l1_quality_index(
            quality_path,
            multi_agent_result.quality_index,
        )
    else:
        quality_path = None
        merged_quality = {}
    merged_relations = merge_memory_relations_index(relations_path, relation_updates)
    if not relation_updates:
        merged_relations = existing_relations_index
    merged_activity = (
        merge_memory_activity_index(activity_path, activity_update)
        if activity_update
        else load_memory_activity_index(activity_path)
    )

    print(f"share_mem L1 bridge: inserted {len(memory_objects)} memory objects for {meeting_id}")
    print(f"Research log: {multi_agent_result.run_dir}")
    if quality_path is not None:
        print(
            "L1 quality index: "
            f"{quality_path} "
            f"({len(multi_agent_result.quality_index)} updated, "
            f"{len(merged_quality)} total)"
        )
    print(
        "Memory relations index: "
        f"{relations_path} "
        f"({sum(len(v) for v in relation_updates.values())} new, "
        f"{sum(len(v) for v in merged_relations.values() if isinstance(v, list))} total)"
    )
    print(
        "Memory activity index: "
        f"{activity_path} "
        f"({len(merged_activity)} objects tracked)"
    )
    print(f"Tree version: {tree['tree_version']}")
    print(f"Tree saved: {tree_path}")


if __name__ == "__main__":
    main()
