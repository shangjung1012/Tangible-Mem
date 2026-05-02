"""Explicit multi-agent orchestration for research-friendly L1 extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from io_utils import utc_now_iso
from multi_agent_agents import (
    MultiAgentLLMRunner,
    idea_unit_agent,
    l1_type_agent,
    plan_context_windows,
    segmentation_agent,
)
from multi_agent_logger import ResearchLogger
from multi_agent_reducer import reduce_l1_patch, resolve_cross_type_conflicts
from multi_agent_state import IdeaUnit, L1_MULTI_AGENT_TYPES, SegmentProposal, parse_transcript_lines
from multi_agent_tools import jaccard
from multi_agent_verifier import ground_candidates, verify_l1_candidates


@dataclass(frozen=True)
class MultiAgentPipelineResult:
    run_id: str
    run_dir: Path
    memory_objects: list[dict[str, Any]]
    final_patch: dict[str, Any]
    final_meeting_node: dict[str, Any]
    artifact_paths: dict[str, str]


def build_continuation_batches(
    segments: list[SegmentProposal],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge adjacent needs_more_context segments into bounded extraction batches."""
    sorted_segments = sorted(
        segments,
        key=lambda segment: (segment.line_start, segment.line_end, segment.segment_id),
    )
    batches: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    current: list[SegmentProposal] = []

    def should_merge(left: SegmentProposal, right: SegmentProposal) -> tuple[bool, str]:
        adjacent = right.line_start <= left.line_end + 1
        if not adjacent:
            return False, "non_adjacent_segments"
        if not (left.needs_more_context or right.needs_more_context):
            return False, "no_continuation_flag"
        topic_score = jaccard(left.topic_label, right.topic_label)
        if topic_score >= 0.18 or left.needs_more_context:
            return True, (
                "needs_more_context with adjacent segment; "
                f"topic_similarity={topic_score:.3f}"
            )
        return False, f"weak_topic_similarity={topic_score:.3f}"

    def flush_group(group: list[SegmentProposal]) -> None:
        if not group:
            return
        batch_id = f"B-{len(batches) + 1:03d}"
        topic_labels: list[str] = []
        for segment in group:
            if segment.topic_label not in topic_labels:
                topic_labels.append(segment.topic_label)
        batches.append(
            {
                "batch_id": batch_id,
                "segment_ids": [segment.segment_id for segment in group],
                "line_start": min(segment.line_start for segment in group),
                "line_end": max(segment.line_end for segment in group),
                "topic_label": " / ".join(topic_labels),
                "needs_more_context": any(segment.needs_more_context for segment in group),
                "reason": (
                    "continuation merge batch"
                    if len(group) > 1
                    else "single segment extraction batch"
                ),
            }
        )

    for segment in sorted_segments:
        if not current:
            current = [segment]
            continue
        merge, reason = should_merge(current[-1], segment)
        if merge:
            decisions.append(
                {
                    "action": "merge",
                    "left_segment_id": current[-1].segment_id,
                    "right_segment_id": segment.segment_id,
                    "reason": reason,
                }
            )
            current.append(segment)
            continue
        decisions.append(
            {
                "action": "keep_separate",
                "left_segment_id": current[-1].segment_id,
                "right_segment_id": segment.segment_id,
                "reason": reason,
            }
        )
        flush_group(current)
        current = [segment]
    flush_group(current)
    return batches, decisions


def idea_units_for_batch(
    idea_units: list[IdeaUnit],
    batch: dict[str, Any],
) -> list[IdeaUnit]:
    segment_ids = set(batch.get("segment_ids", []))
    return [unit for unit in idea_units if unit.segment_id in segment_ids]


def build_run_id(meeting_id: str) -> str:
    clean_time = utc_now_iso().replace(":", "").replace("-", "")
    return f"{clean_time}_{meeting_id}_multi_agent"


def run_multi_agent_l1_pipeline(
    *,
    model_name: str,
    api_key: str | list[str],
    transcript: str,
    meeting_id: str,
    source_file: str,
    timestamp: str,
    meeting_date: str,
    existing_topics: list[str],
    research_log_dir: Path,
    window_size: int = 80,
    lookback_lines: int = 6,
    lookahead_lines: int = 6,
) -> MultiAgentPipelineResult:
    run_id = build_run_id(meeting_id)
    logger = ResearchLogger(research_log_dir, run_id)
    lines = parse_transcript_lines(transcript)
    max_line = lines[-1].line_id if lines else 0
    runner = MultiAgentLLMRunner(
        model_name=model_name,
        api_key=api_key,
        logger=logger,
    )

    logger.write_json(
        "run_meta.json",
        {
            "run_id": run_id,
            "pipeline": "multi-agent-l1",
            "meeting_id": meeting_id,
            "source_file": source_file,
            "timestamp": timestamp,
            "meeting_date": meeting_date,
            "model": model_name,
            "line_count": len(lines),
            "implemented_l1_agent_types": sorted(L1_MULTI_AGENT_TYPES),
            "deferred_l1_agent_types": ["argument", "open_question"],
        },
    )
    logger.append_event("context_planner:start", {"line_count": len(lines)})

    window_plans = plan_context_windows(
        lines,
        window_size=window_size,
        lookback_lines=lookback_lines,
        lookahead_lines=lookahead_lines,
    )
    logger.write_json("window_plans.json", window_plans)
    logger.append_event("context_planner:done", {"windows": len(window_plans)})

    all_segments = []
    for plan in window_plans:
        logger.append_event(
            "segmentation_agent:start",
            {"start_line": plan.start_line, "end_line": plan.end_line},
        )
        segments = segmentation_agent(
            runner,
            meeting_id=meeting_id,
            plan=plan,
            transcript_lines=lines,
        )
        all_segments.extend(segments)
        logger.append_event("segmentation_agent:done", {"segments": len(segments)})
    logger.write_json("segments.json", all_segments)

    extraction_batches, continuation_decisions = build_continuation_batches(all_segments)
    logger.write_json("continuation_merges.json", continuation_decisions)
    logger.write_json("extraction_batches.json", extraction_batches)

    all_idea_units = []
    for segment in all_segments:
        logger.append_event("idea_unit_agent:start", {"segment_id": segment.segment_id})
        units = idea_unit_agent(
            runner,
            segment=segment,
            transcript_lines=lines,
        )
        all_idea_units.extend(units)
        logger.append_event("idea_unit_agent:done", {"units": len(units)})
    logger.write_json("idea_units.json", all_idea_units)

    raw_candidates = []
    for batch in extraction_batches:
        batch_units = idea_units_for_batch(all_idea_units, batch)
        if not batch_units:
            continue
        for obj_type in ["decision", "todo", "method_change", "result"]:
            logger.append_event(
                f"l1_{obj_type}_agent:start",
                {
                    "extraction_scope": batch["batch_id"],
                    "segment_ids": batch["segment_ids"],
                    "idea_units": len(batch_units),
                },
            )
            candidates = l1_type_agent(
                runner,
                obj_type=obj_type,
                idea_units=batch_units,
                existing_topics=existing_topics,
                extraction_scope=str(batch["batch_id"]),
                segment_ids=list(batch["segment_ids"]),
            )
            raw_candidates.extend(candidates)
            logger.append_event(
                f"l1_{obj_type}_agent:done",
                {
                    "extraction_scope": batch["batch_id"],
                    "candidates": len(candidates),
                },
            )
    logger.write_json("raw_candidates.json", raw_candidates)

    logger.append_event("evidence_grounding_agent:start", {"candidates": len(raw_candidates)})
    grounded_candidates = ground_candidates(
        raw_candidates,
        idea_units=all_idea_units,
        transcript_lines=lines,
    )
    logger.write_json("grounded_candidates.json", grounded_candidates)
    logger.append_event(
        "evidence_grounding_agent:done",
        {"grounded_candidates": len(grounded_candidates)},
    )

    logger.append_event(
        "cross_type_conflict_resolver:start",
        {"grounded_candidates": len(grounded_candidates)},
    )
    resolved_candidates, conflict_decisions = resolve_cross_type_conflicts(grounded_candidates)
    logger.write_json("conflict_resolution.json", conflict_decisions)
    logger.append_event(
        "cross_type_conflict_resolver:done",
        {"resolved_candidates": len(resolved_candidates), "decisions": len(conflict_decisions)},
    )

    logger.append_event("verify_l1_candidates:start", {"candidates": len(resolved_candidates)})
    verification = verify_l1_candidates(resolved_candidates, max_line=max_line)
    logger.write_json("verified_candidates.json", verification.verified_candidates)
    logger.write_json("rejected_candidates.json", verification.rejected_candidates)
    logger.append_event(
        "verify_l1_candidates:done",
        {
            "verified": len(verification.verified_candidates),
            "rejected": len(verification.rejected_candidates),
        },
    )

    logger.append_event(
        "reduce_l1_patch:start",
        {"verified": len(verification.verified_candidates)},
    )
    final_patch, memory_objects = reduce_l1_patch(
        verification.verified_candidates,
        meeting_id=meeting_id,
    )
    logger.write_json("final_patch.json", final_patch)
    logger.append_event("reduce_l1_patch:done", {"memory_objects": len(memory_objects)})

    final_meeting_node = {
        "meeting_id": meeting_id,
        "timestamp": timestamp,
        "meeting_date": meeting_date,
        "source_file": source_file,
        "phase_id": "",
        "memory_objects": memory_objects,
    }
    logger.write_json("final_meeting_node.json", final_meeting_node)
    logger.write_json(
        "l2_l3_wiring.json",
        {
            "phase_summarizer": {
                "status": "compatible_with_existing_summarize_phase",
                "command": (
                    "uv run long_term/cli.py summarize phase --phase-id <phase> "
                    "--time-start <start> --time-end <end> --meetings "
                    f"{meeting_id}"
                ),
            },
            "profile_updater": {
                "status": "compatible_with_existing_summarize_profile",
                "command": "uv run long_term/cli.py summarize profile",
            },
        },
    )
    logger.append_event("persist_l1:prepared", {"meeting_id": meeting_id})

    artifact_paths = {
        path.name: str(path)
        for path in logger.run_dir.iterdir()
        if path.is_file()
    }
    return MultiAgentPipelineResult(
        run_id=run_id,
        run_dir=logger.run_dir,
        memory_objects=memory_objects,
        final_patch=final_patch,
        final_meeting_node=final_meeting_node,
        artifact_paths=artifact_paths,
    )
