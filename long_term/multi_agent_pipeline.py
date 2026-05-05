"""Explicit multi-agent orchestration for research-friendly L1 extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from io_utils import utc_now_iso
from multi_agent_agents import (
    MultiAgentLLMRunner,
    idea_unit_agent,
    l1_fallback_agent,
    l1_type_agent,
    plan_context_windows,
    segmentation_agent,
)
from multi_agent_logger import ResearchLogger
from multi_agent_reducer import reduce_l1_patch, resolve_cross_type_conflicts
from multi_agent_state import (
    IdeaUnit,
    L1_MULTI_AGENT_TYPES,
    SegmentProposal,
    TranscriptLine,
    WindowPlan,
    parse_transcript_lines,
)
from multi_agent_tools import evidence_quote, jaccard
from multi_agent_validators import (
    coarsen_segments_for_window,
    repair_idea_units_for_segment,
    repair_segment_coverage,
)
from multi_agent_verifier import ground_candidates, verify_l1_candidates

CROSS_WINDOW_TOPIC_MERGE_THRESHOLD = 0.30
CROSS_WINDOW_BOUNDARY_MERGE_THRESHOLD = 0.20
CROSS_WINDOW_IDEA_UNIT_MERGE_THRESHOLD = 0.20
BOUNDARY_LINE_WINDOW = 6
BOUNDARY_REFINEMENT_CONTEXT_LINES = 16
SEGMENT_WINDOW_ID_RE = re.compile(r"^S-(\d+)-")


@dataclass(frozen=True)
class MultiAgentPipelineResult:
    run_id: str
    run_dir: Path
    memory_objects: list[dict[str, Any]]
    final_patch: dict[str, Any]
    final_meeting_node: dict[str, Any]
    artifact_paths: dict[str, str]


BoundaryRefiner = Callable[
    [SegmentProposal, SegmentProposal, WindowPlan, str],
    tuple[list[SegmentProposal], dict[str, Any]],
]


def segment_window_start(segment: SegmentProposal) -> int | None:
    match = SEGMENT_WINDOW_ID_RE.match(segment.segment_id)
    if not match:
        return None
    return int(match.group(1))


def is_cross_window_boundary(left: SegmentProposal, right: SegmentProposal) -> bool:
    left_window = segment_window_start(left)
    right_window = segment_window_start(right)
    return (
        left_window is not None
        and right_window is not None
        and left_window != right_window
    )


def boundary_transcript_similarity(
    left: SegmentProposal,
    right: SegmentProposal,
    transcript_lines: list[TranscriptLine] | None,
) -> float:
    if not transcript_lines:
        return 0.0
    left_start = max(left.line_start, left.line_end - BOUNDARY_LINE_WINDOW + 1)
    right_end = min(right.line_end, right.line_start + BOUNDARY_LINE_WINDOW - 1)
    left_text = evidence_quote(
        transcript_lines,
        list(range(left_start, left.line_end + 1)),
        max_chars=1200,
    )
    right_text = evidence_quote(
        transcript_lines,
        list(range(right.line_start, right_end + 1)),
        max_chars=1200,
    )
    return jaccard(left_text, right_text)


def boundary_idea_unit_similarity(
    left: SegmentProposal,
    right: SegmentProposal,
    idea_units: list[IdeaUnit] | None,
) -> float:
    if not idea_units:
        return 0.0
    left_units = sorted(
        [unit for unit in idea_units if unit.segment_id == left.segment_id],
        key=lambda unit: (unit.line_end, unit.line_start, unit.unit_id),
        reverse=True,
    )[:2]
    right_units = sorted(
        [unit for unit in idea_units if unit.segment_id == right.segment_id],
        key=lambda unit: (unit.line_start, unit.line_end, unit.unit_id),
    )[:2]
    left_text = " ".join(unit.text for unit in reversed(left_units))
    right_text = " ".join(unit.text for unit in right_units)
    return jaccard(left_text, right_text)


def should_refine_cross_window_boundary(
    left: SegmentProposal,
    right: SegmentProposal,
    *,
    transcript_lines: list[TranscriptLine] | None = None,
) -> tuple[bool, str]:
    if right.line_start > left.line_end + 1:
        return False, "non_adjacent_segments"
    if not is_cross_window_boundary(left, right):
        return False, "not_cross_window_boundary"
    topic_score = jaccard(left.topic_label, right.topic_label)
    boundary_score = boundary_transcript_similarity(left, right, transcript_lines)
    if (
        left.needs_more_context
        or right.needs_more_context
        or topic_score >= CROSS_WINDOW_TOPIC_MERGE_THRESHOLD
        or boundary_score >= CROSS_WINDOW_BOUNDARY_MERGE_THRESHOLD
    ):
        return True, (
            "cross_window_boundary_refinement; "
            f"topic_similarity={topic_score:.3f}; "
            f"boundary_similarity={boundary_score:.3f}"
        )
    return False, (
        "weak_cross_window_boundary_signal; "
        f"topic_similarity={topic_score:.3f}; "
        f"boundary_similarity={boundary_score:.3f}"
    )


def refine_cross_window_boundaries(
    segments: list[SegmentProposal],
    *,
    transcript_lines: list[TranscriptLine] | None,
    refine_span: BoundaryRefiner,
) -> tuple[list[SegmentProposal], list[dict[str, Any]]]:
    """Re-segment connected cross-window spans before idea-unit extraction."""
    sorted_segments = sorted(
        segments,
        key=lambda segment: (segment.line_start, segment.line_end, segment.segment_id),
    )
    refined_segments: list[SegmentProposal] = []
    reports: list[dict[str, Any]] = []
    index = 0
    while index < len(sorted_segments):
        left = sorted_segments[index]
        if index + 1 >= len(sorted_segments):
            refined_segments.append(left)
            break
        right = sorted_segments[index + 1]
        should_refine, reason = should_refine_cross_window_boundary(
            left,
            right,
            transcript_lines=transcript_lines,
        )
        if not should_refine:
            reports.append(
                {
                    "action": "keep_original",
                    "left_segment_id": left.segment_id,
                    "right_segment_id": right.segment_id,
                    "reason": reason,
                }
            )
            refined_segments.append(left)
            index += 1
            continue

        plan = WindowPlan(
            start_line=left.line_start,
            end_line=right.line_end,
            lookback_lines=BOUNDARY_REFINEMENT_CONTEXT_LINES,
            lookahead_lines=BOUNDARY_REFINEMENT_CONTEXT_LINES,
            reason=reason,
        )
        replacements, metadata = refine_span(left, right, plan, reason)
        valid_replacements = [
            segment
            for segment in replacements
            if (
                plan.start_line <= segment.line_start <= segment.line_end <= plan.end_line
            )
        ]
        if not valid_replacements:
            reports.append(
                {
                    "action": "keep_original",
                    "left_segment_id": left.segment_id,
                    "right_segment_id": right.segment_id,
                    "reason": "refinement_returned_no_valid_segments",
                    "refinement_reason": reason,
                    "metadata": metadata,
                }
            )
            refined_segments.append(left)
            index += 1
            continue
        valid_replacements = sorted(
            valid_replacements,
            key=lambda segment: (segment.line_start, segment.line_end, segment.segment_id),
        )
        reports.append(
            {
                "action": "refine",
                "source_segment_ids": [left.segment_id, right.segment_id],
                "output_segment_ids": [segment.segment_id for segment in valid_replacements],
                "line_start": plan.start_line,
                "line_end": plan.end_line,
                "reason": reason,
                "metadata": metadata,
            }
        )
        refined_segments.extend(valid_replacements)
        index += 2
    return refined_segments, reports


def build_continuation_batches(
    segments: list[SegmentProposal],
    *,
    transcript_lines: list[TranscriptLine] | None = None,
    idea_units: list[IdeaUnit] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge bounded segment continuations into extraction batches."""
    sorted_segments = sorted(
        segments,
        key=lambda segment: (segment.line_start, segment.line_end, segment.segment_id),
    )
    batches: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    current: list[SegmentProposal] = []

    def segment_window_start(segment: SegmentProposal) -> int | None:
        match = SEGMENT_WINDOW_ID_RE.match(segment.segment_id)
        if not match:
            return None
        return int(match.group(1))

    def is_cross_window_boundary(left: SegmentProposal, right: SegmentProposal) -> bool:
        left_window = segment_window_start(left)
        right_window = segment_window_start(right)
        return (
            left_window is not None
            and right_window is not None
            and left_window != right_window
        )

    def boundary_transcript_similarity(
        left: SegmentProposal,
        right: SegmentProposal,
    ) -> float:
        if not transcript_lines:
            return 0.0
        left_start = max(left.line_start, left.line_end - BOUNDARY_LINE_WINDOW + 1)
        right_end = min(right.line_end, right.line_start + BOUNDARY_LINE_WINDOW - 1)
        left_text = evidence_quote(
            transcript_lines,
            list(range(left_start, left.line_end + 1)),
            max_chars=1200,
        )
        right_text = evidence_quote(
            transcript_lines,
            list(range(right.line_start, right_end + 1)),
            max_chars=1200,
        )
        return jaccard(left_text, right_text)

    def boundary_idea_unit_similarity(
        left: SegmentProposal,
        right: SegmentProposal,
    ) -> float:
        if not idea_units:
            return 0.0
        left_units = sorted(
            [unit for unit in idea_units if unit.segment_id == left.segment_id],
            key=lambda unit: (unit.line_end, unit.line_start, unit.unit_id),
            reverse=True,
        )[:2]
        right_units = sorted(
            [unit for unit in idea_units if unit.segment_id == right.segment_id],
            key=lambda unit: (unit.line_start, unit.line_end, unit.unit_id),
        )[:2]
        left_text = " ".join(unit.text for unit in reversed(left_units))
        right_text = " ".join(unit.text for unit in right_units)
        return jaccard(left_text, right_text)

    def should_merge(left: SegmentProposal, right: SegmentProposal) -> tuple[bool, str]:
        adjacent = right.line_start <= left.line_end + 1
        if not adjacent:
            return False, "non_adjacent_segments"
        topic_score = jaccard(left.topic_label, right.topic_label)
        boundary_score = boundary_transcript_similarity(left, right)
        unit_score = boundary_idea_unit_similarity(left, right)
        if left.needs_more_context or right.needs_more_context:
            if (
                topic_score >= 0.18
                or boundary_score >= CROSS_WINDOW_BOUNDARY_MERGE_THRESHOLD
                or unit_score >= CROSS_WINDOW_IDEA_UNIT_MERGE_THRESHOLD
                or left.needs_more_context
            ):
                return True, (
                    "needs_more_context with adjacent segment; "
                    f"topic_similarity={topic_score:.3f}; "
                    f"boundary_similarity={boundary_score:.3f}; "
                    f"idea_unit_similarity={unit_score:.3f}"
                )
            return False, (
                f"weak_continuation_similarity; topic_similarity={topic_score:.3f}; "
                f"boundary_similarity={boundary_score:.3f}; "
                f"idea_unit_similarity={unit_score:.3f}"
            )
        if (
            is_cross_window_boundary(left, right)
            and (
                topic_score >= CROSS_WINDOW_TOPIC_MERGE_THRESHOLD
                or boundary_score >= CROSS_WINDOW_BOUNDARY_MERGE_THRESHOLD
                or unit_score >= CROSS_WINDOW_IDEA_UNIT_MERGE_THRESHOLD
            )
        ):
            return True, (
                "cross_window_topic_continuity without continuation flag; "
                f"topic_similarity={topic_score:.3f}; "
                f"boundary_similarity={boundary_score:.3f}; "
                f"idea_unit_similarity={unit_score:.3f}"
            )
        return False, (
            f"no_continuation_flag; topic_similarity={topic_score:.3f}; "
            f"boundary_similarity={boundary_score:.3f}; "
            f"idea_unit_similarity={unit_score:.3f}"
        )

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
    coverage_reports = []
    coarsening_reports = []
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
        repaired_segments, coverage_report = repair_segment_coverage(plan, segments)
        coarsened_segments, coarsening_report = coarsen_segments_for_window(
            plan,
            repaired_segments,
        )
        coverage_reports.append(coverage_report)
        coarsening_reports.append(coarsening_report)
        all_segments.extend(coarsened_segments)
        logger.append_event(
            "segmentation_agent:done",
            {
                "segments": len(segments),
                "output_segments": len(repaired_segments),
                "coarsened_segments": len(coarsened_segments),
                "coverage_rate": coverage_report["coverage_rate"],
                "repairs": len(coverage_report["repair_segment_ids"]),
            },
        )
    initial_segments = list(all_segments)
    boundary_refinement_reports: list[dict[str, Any]] = []

    def refine_boundary_span(
        left: SegmentProposal,
        right: SegmentProposal,
        plan: WindowPlan,
        reason: str,
    ) -> tuple[list[SegmentProposal], dict[str, Any]]:
        logger.append_event(
            "boundary_refinement:start",
            {
                "left_segment_id": left.segment_id,
                "right_segment_id": right.segment_id,
                "start_line": plan.start_line,
                "end_line": plan.end_line,
                "reason": reason,
            },
        )
        refined_raw = segmentation_agent(
            runner,
            meeting_id=meeting_id,
            plan=plan,
            transcript_lines=lines,
        )
        repaired_refined, refined_coverage = repair_segment_coverage(plan, refined_raw)
        coarsened_refined, refined_coarsening = coarsen_segments_for_window(
            plan,
            repaired_refined,
        )
        logger.append_event(
            "boundary_refinement:done",
            {
                "left_segment_id": left.segment_id,
                "right_segment_id": right.segment_id,
                "raw_segments": len(refined_raw),
                "output_segments": len(coarsened_refined),
                "coverage_rate": refined_coverage["coverage_rate"],
            },
        )
        return coarsened_refined, {
            "raw_segments": len(refined_raw),
            "coverage": refined_coverage,
            "coarsening": refined_coarsening,
        }

    all_segments, boundary_refinement_reports = refine_cross_window_boundaries(
        all_segments,
        transcript_lines=lines,
        refine_span=refine_boundary_span,
    )
    logger.write_json("initial_segments.json", initial_segments)
    logger.write_json("boundary_refinement.json", boundary_refinement_reports)
    logger.write_json("segments.json", all_segments)
    logger.write_json("segment_coverage_validation.json", coverage_reports)
    logger.write_json("segment_coarsening.json", coarsening_reports)

    all_idea_units = []
    idea_unit_quality_reports = []
    for segment in all_segments:
        logger.append_event("idea_unit_agent:start", {"segment_id": segment.segment_id})
        units = idea_unit_agent(
            runner,
            segment=segment,
            transcript_lines=lines,
        )
        repaired_units, quality_report = repair_idea_units_for_segment(
            segment=segment,
            units=units,
            transcript_lines=lines,
        )
        idea_unit_quality_reports.append(quality_report)
        all_idea_units.extend(repaired_units)
        logger.append_event(
            "idea_unit_agent:done",
            {
                "segment_id": segment.segment_id,
                "units": len(units),
                "output_units": len(repaired_units),
                "issues": len(quality_report["issues"]),
                "repairs": len(quality_report["repairs"]),
            },
        )
    logger.write_json("idea_units.json", all_idea_units)
    logger.write_json("idea_unit_quality_validation.json", idea_unit_quality_reports)

    extraction_batches, continuation_decisions = build_continuation_batches(
        all_segments,
        transcript_lines=lines,
        idea_units=all_idea_units,
    )
    logger.write_json("continuation_merges.json", continuation_decisions)
    logger.write_json("extraction_batches.json", extraction_batches)

    raw_candidates = []
    batch_fallback_reports = []
    for batch in extraction_batches:
        batch_units = idea_units_for_batch(all_idea_units, batch)
        if not batch_units:
            continue
        batch_candidates = []
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
            batch_candidates.extend(candidates)
            logger.append_event(
                f"l1_{obj_type}_agent:done",
                {
                    "extraction_scope": batch["batch_id"],
                    "candidates": len(candidates),
                },
            )
        if not batch_candidates:
            logger.append_event(
                "l1_fallback_agent:start",
                {
                    "extraction_scope": batch["batch_id"],
                    "segment_ids": batch["segment_ids"],
                    "idea_units": len(batch_units),
                },
            )
            fallback_candidates = l1_fallback_agent(
                runner,
                idea_units=batch_units,
                existing_topics=existing_topics,
                extraction_scope=str(batch["batch_id"]),
                segment_ids=list(batch["segment_ids"]),
            )
            batch_candidates.extend(fallback_candidates)
            batch_fallback_reports.append(
                {
                    "batch_id": batch["batch_id"],
                    "segment_ids": batch["segment_ids"],
                    "idea_units": len(batch_units),
                    "fallback_candidates": len(fallback_candidates),
                    "reason": "typed_l1_agents_returned_no_candidates",
                }
            )
            logger.append_event(
                "l1_fallback_agent:done",
                {
                    "extraction_scope": batch["batch_id"],
                    "candidates": len(fallback_candidates),
                },
            )
        raw_candidates.extend(batch_candidates)
    logger.write_json("raw_candidates.json", raw_candidates)
    logger.write_json("batch_fallbacks.json", batch_fallback_reports)

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
    viewpoint_recurrence = final_patch.get("viewpoint_recurrence", [])
    logger.write_json("viewpoint_recurrence.json", viewpoint_recurrence)
    logger.append_event(
        "reduce_l1_patch:done",
        {
            "memory_objects": len(memory_objects),
            "viewpoint_recurrence": len(viewpoint_recurrence),
        },
    )

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
