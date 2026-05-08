"""Explicit multi-agent orchestration for research-friendly L1 extraction."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .io_utils import utc_now_iso
from .multi_agent_agents import (
    MultiAgentLLMRunner,
    idea_unit_agent,
    idea_unit_repair_agent,
    l1_fallback_agent,
    l1_type_agent,
    plan_context_windows,
    segmentation_agent,
)
from .multi_agent_logger import ResearchLogger
from .multi_agent_reducer import reduce_l1_patch, resolve_cross_type_conflicts
from .multi_agent_state import (
    IdeaUnit,
    L1_MULTI_AGENT_TYPES,
    L1_MULTI_AGENT_V2_TYPES,
    SegmentProposal,
    TranscriptLine,
    WindowPlan,
    parse_transcript_lines,
)
from .multi_agent_tools import evidence_quote, jaccard
from .multi_agent_validators import (
    coarsen_segments_for_window,
    repair_idea_units_for_segment,
    repair_segment_coverage,
)
from .multi_agent_verifier import ground_candidates, verify_l1_candidates
from .taxonomy import normalize_taxonomy, type_order_for_taxonomy

CROSS_WINDOW_TOPIC_MERGE_THRESHOLD = 0.30
CROSS_WINDOW_BOUNDARY_MERGE_THRESHOLD = 0.20
CROSS_WINDOW_IDEA_UNIT_MERGE_THRESHOLD = 0.20
BOUNDARY_LINE_WINDOW = 6
BOUNDARY_REFINEMENT_CONTEXT_LINES = 16
TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH = 10
MAX_IDEA_UNITS_PER_EXTRACTION_BATCH = 14
EXTRACTION_BATCH_OVERLAP_UNITS = 2
MIN_SPLIT_REMAINDER_IDEA_UNITS = 3
PREVIOUS_CONTEXT_LOOKBACK_BATCHES = 2
PREVIOUS_CONTEXT_MAX_ITEMS_PER_TYPE = 2
PREVIOUS_CONTEXT_MAX_TOTAL_ITEMS = 8
PREVIOUS_CONTEXT_MAX_CONTENT_CHARS = 160
PREVIOUS_CONTEXT_MIN_CONFIDENCE = 0.75
SEGMENT_WINDOW_ID_RE = re.compile(r"^S-(\d+)-")
SEMANTIC_IDEA_REPAIR_ISSUES = {
    "empty_or_unusable_idea_units",
    "too_fat_line_span",
    "too_many_units",
    "uncovered_line_ranges",
}


@dataclass(frozen=True)
class MultiAgentPipelineResult:
    run_id: str
    run_dir: Path
    memory_objects: list[dict[str, Any]]
    final_patch: dict[str, Any]
    quality_index: dict[str, Any]
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

    unit_counts_by_segment: dict[str, int] = {}
    unit_ids_by_segment: dict[str, list[str]] = {}
    if idea_units:
        for unit in idea_units:
            unit_counts_by_segment[unit.segment_id] = (
                unit_counts_by_segment.get(unit.segment_id, 0) + 1
            )
            unit_ids_by_segment.setdefault(unit.segment_id, []).append(unit.unit_id)

    def group_unit_count(group: list[SegmentProposal]) -> int:
        if not unit_counts_by_segment:
            return 0
        return sum(unit_counts_by_segment.get(segment.segment_id, 0) for segment in group)

    unit_by_id = {unit.unit_id: unit for unit in idea_units or []}

    def batch_line_bounds(
        group: list[SegmentProposal],
        unit_ids: list[str] | None,
    ) -> tuple[int, int]:
        units = [unit_by_id[unit_id] for unit_id in unit_ids or [] if unit_id in unit_by_id]
        if units:
            return (
                min(unit.line_start for unit in units),
                max(unit.line_end for unit in units),
            )
        return (
            min(segment.line_start for segment in group),
            max(segment.line_end for segment in group),
        )

    def segments_for_unit_ids(
        parent_group: list[SegmentProposal],
        unit_ids: list[str],
    ) -> list[SegmentProposal]:
        segment_ids = {
            unit_by_id[unit_id].segment_id
            for unit_id in unit_ids
            if unit_id in unit_by_id
        }
        return [segment for segment in parent_group if segment.segment_id in segment_ids]

    def overlapping_unit_chunks(unit_ids: list[str]) -> list[list[str]]:
        if len(unit_ids) <= MAX_IDEA_UNITS_PER_EXTRACTION_BATCH:
            return [unit_ids]
        overlap = min(EXTRACTION_BATCH_OVERLAP_UNITS, MAX_IDEA_UNITS_PER_EXTRACTION_BATCH - 1)
        stride = max(1, MAX_IDEA_UNITS_PER_EXTRACTION_BATCH - overlap)
        chunk_count = max(2, (len(unit_ids) - overlap + stride - 1) // stride)
        target_chunk_size = min(
            MAX_IDEA_UNITS_PER_EXTRACTION_BATCH,
            (len(unit_ids) + overlap * (chunk_count - 1) + chunk_count - 1)
            // chunk_count,
        )
        chunks: list[list[str]] = []
        start = 0
        while start < len(unit_ids):
            end = min(len(unit_ids), start + target_chunk_size)
            if len(unit_ids) - end < MIN_SPLIT_REMAINDER_IDEA_UNITS:
                end = len(unit_ids)
            chunk = unit_ids[start:end]
            if chunk:
                chunks.append(chunk)
            if end >= len(unit_ids):
                break
            next_start = end - overlap
            start = next_start if next_start > start else end
        return chunks

    def append_batch(
        group: list[SegmentProposal],
        *,
        reason: str,
        unit_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not group:
            return
        batch_id = f"B-{len(batches) + 1:03d}"
        topic_labels: list[str] = []
        for segment in group:
            if segment.topic_label not in topic_labels:
                topic_labels.append(segment.topic_label)
        line_start, line_end = batch_line_bounds(group, unit_ids)
        batch = {
            "batch_id": batch_id,
            "segment_ids": [segment.segment_id for segment in group],
            "line_start": line_start,
            "line_end": line_end,
            "topic_label": " / ".join(topic_labels),
            "needs_more_context": any(segment.needs_more_context for segment in group),
            "reason": reason,
            "idea_unit_count": len(unit_ids) if unit_ids is not None else group_unit_count(group),
        }
        if unit_ids is not None:
            batch["unit_ids"] = unit_ids
        if metadata:
            batch.update(metadata)
        batches.append(batch)

    def append_split_family(
        group: list[SegmentProposal],
        *,
        reason: str,
        split_reason: str,
    ) -> None:
        parent_unit_ids: list[str] = []
        for segment in group:
            parent_unit_ids.extend(unit_ids_by_segment.get(segment.segment_id, []))
        chunks = overlapping_unit_chunks(parent_unit_ids)
        if len(chunks) <= 1:
            append_batch(group, reason=reason, unit_ids=parent_unit_ids or None)
            return
        parent_batch_id = f"PB-{len(batches) + 1:03d}"
        semantic_parent_segment_ids = [segment.segment_id for segment in group]
        tiny_remainder_avoided = (
            len(parent_unit_ids) % TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH
            in range(1, MIN_SPLIT_REMAINDER_IDEA_UNITS)
        )
        for index, chunk_ids in enumerate(chunks, start=1):
            previous_ids = set(chunks[index - 2]) if index > 1 else set()
            next_ids = set(chunks[index]) if index < len(chunks) else set()
            overlap_unit_ids = sorted(
                set(chunk_ids).intersection(previous_ids | next_ids),
                key=chunk_ids.index,
            )
            chunk_group = segments_for_unit_ids(group, chunk_ids) or group
            append_batch(
                chunk_group,
                reason=f"{reason}; {split_reason}",
                unit_ids=chunk_ids,
                metadata={
                    "parent_batch_id": parent_batch_id,
                    "split_index": index,
                    "split_count": len(chunks),
                    "split_reason": split_reason,
                    "overlap_unit_ids": overlap_unit_ids,
                    "semantic_parent_segment_ids": semantic_parent_segment_ids,
                    "tiny_remainder_avoided": tiny_remainder_avoided,
                },
            )
            decisions.append(
                {
                    "action": "split_large_batch",
                    "parent_batch_id": parent_batch_id,
                    "split_index": index,
                    "split_count": len(chunks),
                    "segment_ids": [segment.segment_id for segment in chunk_group],
                    "semantic_parent_segment_ids": semantic_parent_segment_ids,
                    "unit_ids": chunk_ids,
                    "overlap_unit_ids": overlap_unit_ids,
                    "reason": split_reason,
                }
            )

    def flush_group(group: list[SegmentProposal]) -> None:
        if not group:
            return
        base_reason = (
            "continuation merge batch"
            if len(group) > 1
            else "single segment extraction batch"
        )
        total_units = group_unit_count(group)
        if not unit_counts_by_segment or total_units <= MAX_IDEA_UNITS_PER_EXTRACTION_BATCH:
            metadata = {}
            if (
                total_units > TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH
                and total_units % TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH
                in range(1, MIN_SPLIT_REMAINDER_IDEA_UNITS)
            ):
                metadata["tiny_remainder_avoided"] = True
                metadata["split_reason"] = "over_target_within_max_soft_cap"
            append_batch(group, reason=base_reason, metadata=metadata)
            return

        split_reason = (
            f"single segment exceeded {MAX_IDEA_UNITS_PER_EXTRACTION_BATCH} idea units"
            if len(group) == 1
            else f"idea_unit_count exceeded {MAX_IDEA_UNITS_PER_EXTRACTION_BATCH}"
        )
        append_split_family(
            group,
            reason=(
                f"{base_reason}; split_large_segment_by_idea_unit_cap"
                if len(group) == 1
                else f"{base_reason}; split_by_idea_unit_cap"
            ),
            split_reason=split_reason,
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
    unit_ids = batch.get("unit_ids")
    if isinstance(unit_ids, list) and unit_ids:
        allowed_unit_ids = set(str(unit_id) for unit_id in unit_ids)
        return [unit for unit in idea_units if unit.unit_id in allowed_unit_ids]
    segment_ids = set(batch.get("segment_ids", []))
    return [unit for unit in idea_units if unit.segment_id in segment_ids]


def build_run_id(meeting_id: str) -> str:
    clean_time = utc_now_iso().replace(":", "").replace("-", "")
    return f"{clean_time}_{meeting_id}_multi_agent"


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _score_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": 0.0, "max": 0.0, "avg": 0.0}
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "avg": _avg(values),
    }


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _candidate_type(candidate: Any) -> str:
    if isinstance(candidate, dict):
        return str(candidate.get("type", "unknown") or "unknown")
    return str(getattr(candidate, "type", "unknown") or "unknown")


def _candidate_support_score(candidate: Any) -> float:
    if isinstance(candidate, dict):
        return float(candidate.get("support_score", 0.0) or 0.0)
    return float(getattr(candidate, "support_score", 0.0) or 0.0)


def _candidate_quality_warnings(candidate: Any) -> list[str]:
    if isinstance(candidate, dict):
        values = candidate.get("unit_quality_warnings", [])
    else:
        values = getattr(candidate, "unit_quality_warnings", [])
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value or "").strip()]


def _candidate_confidence(candidate: Any) -> float:
    if isinstance(candidate, dict):
        value = candidate.get("confidence", 0.0)
    else:
        value = getattr(candidate, "confidence", 0.0)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _candidate_content(candidate: Any) -> str:
    if isinstance(candidate, dict):
        return str(candidate.get("content", "") or "").strip()
    return str(getattr(candidate, "content", "") or "").strip()


def _candidate_scope(candidate: Any) -> str:
    if isinstance(candidate, dict):
        return str(candidate.get("extraction_scope", "") or "").strip()
    return str(getattr(candidate, "extraction_scope", "") or "").strip()


def _trim_previous_context_content(content: str) -> str:
    clean = " ".join(str(content or "").split())
    if len(clean) <= PREVIOUS_CONTEXT_MAX_CONTENT_CHARS:
        return clean
    return clean[: PREVIOUS_CONTEXT_MAX_CONTENT_CHARS - 3].rstrip() + "..."


def build_previous_batch_context(
    completed_batch_records: list[dict[str, Any]],
    *,
    current_batch_id: str,
    enabled: bool,
    lookback_batches: int = PREVIOUS_CONTEXT_LOOKBACK_BATCHES,
    max_items_per_type: int = PREVIOUS_CONTEXT_MAX_ITEMS_PER_TYPE,
    max_total_items: int = PREVIOUS_CONTEXT_MAX_TOTAL_ITEMS,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "enabled": bool(enabled),
        "current_batch_id": current_batch_id,
        "lookback_batches": lookback_batches,
        "source_batch_ids": [],
        "items": [],
    }
    if not enabled:
        return context

    if lookback_batches <= 0:
        return context
    recent_records = completed_batch_records[-lookback_batches:]
    source_batch_ids = [
        str(record.get("batch_id", "") or "")
        for record in recent_records
        if str(record.get("batch_id", "") or "").strip()
    ]
    context["source_batch_ids"] = source_batch_ids

    type_counts: Counter[str] = Counter()
    items: list[dict[str, Any]] = []
    for record in recent_records:
        source_batch_id = str(record.get("batch_id", "") or "")
        candidates = record.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if len(items) >= max_total_items:
                break
            if _candidate_confidence(candidate) < PREVIOUS_CONTEXT_MIN_CONFIDENCE:
                continue
            obj_type = _candidate_type(candidate)
            if obj_type not in (L1_MULTI_AGENT_TYPES | L1_MULTI_AGENT_V2_TYPES):
                continue
            if type_counts[obj_type] >= max_items_per_type:
                continue
            content = _trim_previous_context_content(_candidate_content(candidate))
            if not content:
                continue
            items.append(
                {
                    "type": obj_type,
                    "source_batch_id": source_batch_id or _candidate_scope(candidate),
                    "content": content,
                }
            )
            type_counts[obj_type] += 1
    context["items"] = items
    return context


def _previous_context_item_counts(
    previous_context_by_batch: dict[str, dict[str, Any]],
) -> list[float]:
    return [
        float(len(context.get("items", [])))
        for context in previous_context_by_batch.values()
        if context.get("enabled")
    ]


def _needs_semantic_idea_repair(report: dict[str, Any]) -> bool:
    for issue in report.get("issues", []):
        issue_name = str(issue.get("issue", "")).strip()
        if issue_name in SEMANTIC_IDEA_REPAIR_ISSUES:
            return True
    return False


def _deterministic_idea_fallback_count(repair_actions: Counter[str]) -> int:
    return sum(
        repair_actions.get(action, 0)
        for action in (
            "add_fallback_for_uncovered_lines",
            "fallback_for_empty_segment",
            "replace_with_line_chunks",
        )
    )


def _rejection_reason_counts(rejected_candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for candidate in rejected_candidates:
        for reason in candidate.get("verification_reasons", []):
            clean = str(reason or "").strip()
            if clean.startswith("duplicate_of:"):
                clean = "duplicate_of"
            if clean:
                counts[clean] += 1
    return _counter_dict(counts)


def _llm_stage_family(stage: str) -> str:
    if stage.startswith("segmentation_"):
        return "segmentation_agent"
    if stage.startswith("idea_unit_repair_agent_"):
        return "idea_unit_repair_agent"
    if stage.startswith("idea_units_"):
        return "idea_unit_agent"
    if stage.startswith("l1_fallback_agent_"):
        return "l1_fallback_agent"
    if stage.startswith("l1_") and "_agent_" in stage:
        return stage.split("_agent_", 1)[0] + "_agent"
    return stage.split("_", 1)[0] or "unknown"


def _char_token_proxy(char_count: int) -> int:
    return max(0, int((char_count + 3) // 4))


def _llm_metrics(call_records: list[dict[str, Any]] | None) -> dict[str, Any]:
    records = call_records or []
    latencies = [
        float(record.get("latency_sec", 0.0) or 0.0)
        for record in records
    ]
    prompt_chars = [int(record.get("prompt_chars", 0) or 0) for record in records]
    response_chars = [int(record.get("response_chars", 0) or 0) for record in records]
    stage_counts: Counter[str] = Counter()
    stage_latencies: dict[str, list[float]] = {}
    for record in records:
        family = _llm_stage_family(str(record.get("stage", "unknown") or "unknown"))
        stage_counts[family] += 1
        stage_latencies.setdefault(family, []).append(
            float(record.get("latency_sec", 0.0) or 0.0)
        )

    prompt_char_total = sum(prompt_chars)
    response_char_total = sum(response_chars)
    return {
        "call_count": len(records),
        "error_count": sum(1 for record in records if not record.get("success", True)),
        "calls_by_stage": _counter_dict(stage_counts),
        "latency_sec": _score_summary(latencies),
        "latency_sec_by_stage": {
            stage: _score_summary(values)
            for stage, values in sorted(stage_latencies.items())
        },
        "prompt_chars": _score_summary([float(value) for value in prompt_chars]),
        "response_chars": _score_summary([float(value) for value in response_chars]),
        "estimated_text_tokens": {
            "prompt": _char_token_proxy(prompt_char_total),
            "response": _char_token_proxy(response_char_total),
            "total": _char_token_proxy(prompt_char_total + response_char_total),
            "note": "rough chars/4 proxy for diagnostics, not provider billing",
        },
    }


def build_metrics_summary(
    *,
    line_count: int,
    window_plans: list[WindowPlan],
    initial_segments: list[SegmentProposal],
    final_segments: list[SegmentProposal],
    coverage_reports: list[dict[str, Any]],
    coarsening_reports: list[dict[str, Any]],
    boundary_refinement_reports: list[dict[str, Any]],
    idea_units: list[IdeaUnit],
    idea_unit_quality_reports: list[dict[str, Any]],
    extraction_batches: list[dict[str, Any]],
    continuation_decisions: list[dict[str, Any]],
    previous_context_by_batch: dict[str, dict[str, Any]],
    raw_candidates: list[Any],
    batch_fallback_reports: list[dict[str, Any]],
    grounded_candidates: list[Any],
    conflict_decisions: list[Any],
    verified_candidates: list[dict[str, Any]],
    rejected_candidates: list[dict[str, Any]],
    memory_objects: list[dict[str, Any]],
    viewpoint_recurrence: list[dict[str, Any]],
    llm_call_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize run-level quality signals without changing extraction behavior."""
    segment_coverage_rates = [
        float(report.get("coverage_rate", 0.0) or 0.0)
        for report in coverage_reports
    ]
    idea_unit_coverage_rates = [
        float(report.get("coverage_rate", 0.0) or 0.0)
        for report in idea_unit_quality_reports
    ]
    idea_repair_actions: Counter[str] = Counter()
    idea_issue_types: Counter[str] = Counter()
    semantic_repair_count = 0
    semantic_repair_success_count = 0
    semantic_repair_error_count = 0
    non_memory_context_range_count = 0
    non_memory_context_line_count = 0
    for report in idea_unit_quality_reports:
        semantic_repair = report.get("semantic_repair", {})
        if isinstance(semantic_repair, dict) and semantic_repair.get("attempted"):
            semantic_repair_count += 1
            if semantic_repair.get("used_semantic_output"):
                semantic_repair_success_count += 1
            if semantic_repair.get("error"):
                semantic_repair_error_count += 1
        non_memory_ranges = report.get("non_memory_context_ranges", [])
        if isinstance(non_memory_ranges, list):
            non_memory_context_range_count += len(non_memory_ranges)
            for row in non_memory_ranges:
                try:
                    start_line = int(row.get("start_line"))
                    end_line = int(row.get("end_line"))
                except (AttributeError, TypeError, ValueError):
                    continue
                if end_line >= start_line:
                    non_memory_context_line_count += end_line - start_line + 1
        for repair in report.get("repairs", []):
            action = str(repair.get("action", "")).strip()
            if action:
                idea_repair_actions[action] += 1
        for issue in report.get("issues", []):
            issue_name = str(issue.get("issue", "")).strip()
            if issue_name:
                idea_issue_types[issue_name] += 1

    warning_counts: Counter[str] = Counter()
    for candidate in verified_candidates:
        warning_counts.update(_candidate_quality_warnings(candidate))

    final_importance_values = [
        float(obj.get("importance", 0.0) or 0.0)
        for obj in memory_objects
    ]
    support_scores = [
        _candidate_support_score(candidate)
        for candidate in grounded_candidates
    ]
    batch_unit_counts = [
        len(idea_units_for_batch(idea_units, batch))
        for batch in extraction_batches
    ]
    split_family_ids = {
        str(batch.get("parent_batch_id", "") or "")
        for batch in extraction_batches
        if str(batch.get("parent_batch_id", "") or "").strip()
    }
    tiny_remainder_keys = {
        str(batch.get("parent_batch_id") or batch.get("batch_id", ""))
        for batch in extraction_batches
        if batch.get("tiny_remainder_avoided")
    }
    previous_context_by_batch = previous_context_by_batch or {}
    previous_context_item_counts = _previous_context_item_counts(previous_context_by_batch)

    return {
        "line_count": line_count,
        "windows": {
            "count": len(window_plans),
            "configured_primary_window_sizes": [
                plan.end_line - plan.start_line + 1 for plan in window_plans
            ],
        },
        "segments": {
            "initial_count": len(initial_segments),
            "final_count": len(final_segments),
            "coverage_rate": _score_summary(segment_coverage_rates),
            "coverage_repair_count": sum(
                len(report.get("repair_segment_ids", []))
                for report in coverage_reports
            ),
            "coarsened_group_count": sum(
                len(report.get("merged_groups", []))
                for report in coarsening_reports
            ),
            "boundary_refinement_actions": _counter_dict(
                Counter(
                    str(report.get("action", "unknown") or "unknown")
                    for report in boundary_refinement_reports
                )
            ),
        },
        "idea_units": {
            "count": len(idea_units),
            "coverage_rate": _score_summary(idea_unit_coverage_rates),
            "completeness_counts": _counter_dict(
                Counter(str(unit.completeness or "unknown") for unit in idea_units)
            ),
            "units_with_uncertainty_note": sum(
                1 for unit in idea_units if str(unit.uncertainty_note or "").strip()
            ),
            "quality_issue_counts": _counter_dict(idea_issue_types),
            "repair_action_counts": _counter_dict(idea_repair_actions),
            "semantic_repair_count": semantic_repair_count,
            "semantic_repair_success_count": semantic_repair_success_count,
            "semantic_repair_error_count": semantic_repair_error_count,
            "non_memory_context_ranges": non_memory_context_range_count,
            "non_memory_context_lines": non_memory_context_line_count,
            "deterministic_fallback_count": _deterministic_idea_fallback_count(
                idea_repair_actions
            ),
            "compaction_fallback_count": idea_repair_actions.get(
                "compact_overfragmented_units",
                0,
            ),
        },
        "extraction_batches": {
            "count": len(extraction_batches),
            "idea_units_per_batch": _score_summary(
                [float(count) for count in batch_unit_counts]
            ),
            "oversized_batch_count": sum(
                count > MAX_IDEA_UNITS_PER_EXTRACTION_BATCH
                for count in batch_unit_counts
            ),
            "target_idea_units_per_batch": TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH,
            "max_idea_units_per_batch": MAX_IDEA_UNITS_PER_EXTRACTION_BATCH,
            "overlap_units_per_split": EXTRACTION_BATCH_OVERLAP_UNITS,
            "batches_over_target_cap": sum(
                count > TARGET_IDEA_UNITS_PER_EXTRACTION_BATCH
                for count in batch_unit_counts
            ),
            "split_family_count": len(split_family_ids),
            "split_batch_count": sum(
                1
                for batch in extraction_batches
                if str(batch.get("parent_batch_id", "") or "").strip()
            ),
            "overlap_unit_count": sum(
                len(batch.get("overlap_unit_ids", []))
                for batch in extraction_batches
                if isinstance(batch.get("overlap_unit_ids", []), list)
            ),
            "tiny_remainder_avoided_count": len(tiny_remainder_keys),
            "continuation_actions": _counter_dict(
                Counter(
                    str(decision.get("action", "unknown") or "unknown")
                    for decision in continuation_decisions
                )
            ),
            "fallback_batch_count": len(batch_fallback_reports),
        },
        "previous_context": {
            "enabled": any(
                context.get("enabled") for context in previous_context_by_batch.values()
            ),
            "batch_count": len(previous_context_by_batch),
            "batches_with_items": sum(
                1
                for context in previous_context_by_batch.values()
                if context.get("enabled") and context.get("items")
            ),
            "items_per_batch": _score_summary(previous_context_item_counts),
        },
        "candidates": {
            "raw_count": len(raw_candidates),
            "raw_by_type": _counter_dict(
                Counter(_candidate_type(candidate) for candidate in raw_candidates)
            ),
            "grounded_count": len(grounded_candidates),
            "support_score": _score_summary(support_scores),
            "conflict_decision_count": len(conflict_decisions),
            "verified_count": len(verified_candidates),
            "rejected_count": len(rejected_candidates),
            "rejection_reasons": _rejection_reason_counts(rejected_candidates),
            "unit_quality_warning_counts": _counter_dict(warning_counts),
        },
        "final_l1": {
            "object_count": len(memory_objects),
            "object_count_by_type": _counter_dict(
                Counter(str(obj.get("type", "unknown")) for obj in memory_objects)
            ),
            "importance": _score_summary(final_importance_values),
            "viewpoint_recurrence_count": len(viewpoint_recurrence),
        },
        "llm": _llm_metrics(llm_call_records),
    }


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
    prior_context_pack: dict[str, Any] | None = None,
    research_log_dir: Path,
    window_size: int = 80,
    lookback_lines: int = 6,
    lookahead_lines: int = 6,
    previous_context_enabled: bool = False,
    taxonomy: str = "v1",
    include_legacy_type: bool = False,
) -> MultiAgentPipelineResult:
    taxonomy = normalize_taxonomy(taxonomy)
    agent_type_order = type_order_for_taxonomy(taxonomy)
    run_id = build_run_id(meeting_id)
    logger = ResearchLogger(research_log_dir, run_id)
    lines = parse_transcript_lines(transcript)
    max_line = lines[-1].line_id if lines else 0
    runner = MultiAgentLLMRunner(
        model_name=model_name,
        api_key=api_key,
        logger=logger,
    )
    started_at_utc = utc_now_iso()
    last_started_stage = "run_initialized"
    last_completed_stage = "run_initialized"
    pipeline_status = "running"

    window_plans: list[WindowPlan] = []
    all_segments: list[SegmentProposal] = []
    initial_segments: list[SegmentProposal] = []
    coverage_reports: list[dict[str, Any]] = []
    coarsening_reports: list[dict[str, Any]] = []
    boundary_refinement_reports: list[dict[str, Any]] = []
    all_idea_units: list[IdeaUnit] = []
    idea_unit_quality_reports: list[dict[str, Any]] = []
    extraction_batches: list[dict[str, Any]] = []
    continuation_decisions: list[dict[str, Any]] = []
    previous_context_by_batch: dict[str, dict[str, Any]] = {}
    raw_candidates: list[Any] = []
    batch_fallback_reports: list[dict[str, Any]] = []
    grounded_candidates: list[Any] = []
    conflict_decisions: list[Any] = []
    resolved_candidates: list[dict[str, Any]] = []
    verified_candidates: list[dict[str, Any]] = []
    rejected_candidates: list[dict[str, Any]] = []
    final_patch: dict[str, Any] = {}
    viewpoint_recurrence: list[dict[str, Any]] = []
    memory_objects: list[dict[str, Any]] = []
    final_meeting_node: dict[str, Any] = {}

    def current_metrics_summary() -> dict[str, Any]:
        return build_metrics_summary(
            line_count=len(lines),
            window_plans=window_plans,
            initial_segments=initial_segments,
            final_segments=all_segments,
            coverage_reports=coverage_reports,
            coarsening_reports=coarsening_reports,
            boundary_refinement_reports=boundary_refinement_reports,
            idea_units=all_idea_units,
            idea_unit_quality_reports=idea_unit_quality_reports,
            extraction_batches=extraction_batches,
            continuation_decisions=continuation_decisions,
            previous_context_by_batch=previous_context_by_batch,
            raw_candidates=raw_candidates,
            batch_fallback_reports=batch_fallback_reports,
            grounded_candidates=grounded_candidates,
            conflict_decisions=conflict_decisions,
            verified_candidates=verified_candidates,
            rejected_candidates=rejected_candidates,
            memory_objects=memory_objects,
            viewpoint_recurrence=viewpoint_recurrence,
            llm_call_records=runner.call_records,
        )

    def write_run_state(
        status: str,
        *,
        stage: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        metrics = current_metrics_summary()
        status_payload = {
            "run_id": run_id,
            "pipeline": "multi-agent-l1",
            "meeting_id": meeting_id,
            "status": status,
            "last_started_stage": last_started_stage,
            "last_completed_stage": stage or last_completed_stage,
            "updated_at_utc": utc_now_iso(),
            "started_at_utc": started_at_utc,
            "model": model_name,
            "taxonomy": taxonomy,
            "include_legacy_type": include_legacy_type,
            "source_file": source_file,
            "line_count": len(lines),
            "run_dir": str(logger.run_dir),
            "error": error,
            "progress": {
                "windows": len(window_plans),
                "segments": len(all_segments),
                "idea_units": len(all_idea_units),
                "extraction_batches": len(extraction_batches),
                "raw_candidates": len(raw_candidates),
                "grounded_candidates": len(grounded_candidates),
                "verified_candidates": len(verified_candidates),
                "rejected_candidates": len(rejected_candidates),
                "memory_objects": len(memory_objects),
                "llm_calls": metrics["llm"]["call_count"],
                "llm_errors": metrics["llm"]["error_count"],
            },
        }
        logger.write_json("status.json", status_payload)
        logger.write_json("run_summary.json", {**status_payload, "metrics": metrics})

    def mark_started(stage: str) -> None:
        nonlocal last_started_stage
        last_started_stage = stage
        write_run_state(pipeline_status)

    def mark_completed(stage: str) -> None:
        nonlocal last_completed_stage
        last_completed_stage = stage
        write_run_state(pipeline_status, stage=stage)

    write_run_state(pipeline_status)

    try:
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
                "taxonomy": taxonomy,
                "include_legacy_type": include_legacy_type,
                "line_count": len(lines),
                "implemented_l1_agent_types": list(agent_type_order),
                "deferred_l1_agent_types": [],
            },
        )
        logger.write_json("prior_context_pack.json", prior_context_pack or {})
        mark_completed("run_meta:written")
        mark_started("context_planner:start")
        logger.append_event("context_planner:start", {"line_count": len(lines)})

        window_plans = plan_context_windows(
            lines,
            window_size=window_size,
            lookback_lines=lookback_lines,
            lookahead_lines=lookahead_lines,
        )
        logger.write_json("window_plans.json", window_plans)
        logger.append_event("context_planner:done", {"windows": len(window_plans)})
        mark_completed("context_planner:done")

        all_segments = []
        coverage_reports = []
        coarsening_reports = []
        for plan in window_plans:
            mark_started(f"segmentation_agent:{plan.start_line}-{plan.end_line}")
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
            mark_completed(f"segmentation_agent:{plan.start_line}-{plan.end_line}:done")
        initial_segments = list(all_segments)
        boundary_refinement_reports: list[dict[str, Any]] = []

        def refine_boundary_span(
            left: SegmentProposal,
            right: SegmentProposal,
            plan: WindowPlan,
            reason: str,
        ) -> tuple[list[SegmentProposal], dict[str, Any]]:
            mark_started(f"boundary_refinement:{left.segment_id}+{right.segment_id}")
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
            mark_completed(f"boundary_refinement:{left.segment_id}+{right.segment_id}:done")
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
        mark_completed("boundary_refinement_artifacts:written")

        all_idea_units = []
        idea_unit_quality_reports = []
        for segment in all_segments:
            mark_started(f"idea_unit_agent:{segment.segment_id}")
            logger.append_event("idea_unit_agent:start", {"segment_id": segment.segment_id})
            units = idea_unit_agent(
                runner,
                segment=segment,
                transcript_lines=lines,
            )
            diagnostic_units, diagnostic_report = repair_idea_units_for_segment(
                segment=segment,
                units=units,
                transcript_lines=lines,
                deterministic_fallback=False,
            )
            semantic_repair = {
                "attempted": False,
                "used_semantic_output": False,
                "input_units": len(units),
                "output_units": 0,
                "non_memory_context_ranges": 0,
            }
            repair_source_units = units
            non_memory_ranges: list[dict[str, Any]] = []
            if _needs_semantic_idea_repair(diagnostic_report):
                semantic_repair["attempted"] = True
                mark_started(f"idea_unit_repair_agent:{segment.segment_id}")
                logger.append_event(
                    "idea_unit_repair_agent:start",
                    {
                        "segment_id": segment.segment_id,
                        "issues": len(diagnostic_report["issues"]),
                        "diagnostic_output_units": len(diagnostic_units),
                    },
                )
                try:
                    semantic_units, non_memory_ranges = idea_unit_repair_agent(
                        runner,
                        segment=segment,
                        transcript_lines=lines,
                        current_units=units,
                        validation_report=diagnostic_report,
                    )
                    if semantic_units or non_memory_ranges:
                        repair_source_units = semantic_units
                        semantic_repair["used_semantic_output"] = True
                    semantic_repair["output_units"] = len(semantic_units)
                    semantic_repair["non_memory_context_ranges"] = len(non_memory_ranges)
                    logger.append_event(
                        "idea_unit_repair_agent:done",
                        {
                            "segment_id": segment.segment_id,
                            "output_units": len(semantic_units),
                            "non_memory_context_ranges": len(non_memory_ranges),
                        },
                    )
                    mark_completed(f"idea_unit_repair_agent:{segment.segment_id}:done")
                except Exception as exc:
                    semantic_repair["error"] = str(exc)
                    logger.append_event(
                        "idea_unit_repair_agent:error",
                        {
                            "segment_id": segment.segment_id,
                            "error": str(exc),
                            "fallback": "deterministic_validator_repair",
                        },
                    )
                    mark_completed(
                        f"idea_unit_repair_agent:{segment.segment_id}:fallback_after_error"
                    )
            repaired_units, quality_report = repair_idea_units_for_segment(
                segment=segment,
                units=repair_source_units,
                transcript_lines=lines,
                non_memory_ranges=non_memory_ranges,
                deterministic_fallback=True,
            )
            if semantic_repair["attempted"]:
                semantic_repair["final_output_units"] = len(repaired_units)
                semantic_repair["deterministic_fallback_after_repair"] = any(
                    repair.get("action")
                    in {
                        "add_fallback_for_uncovered_lines",
                        "fallback_for_empty_segment",
                        "replace_with_line_chunks",
                        "compact_overfragmented_units",
                    }
                    for repair in quality_report.get("repairs", [])
                )
                quality_report["initial_validation_report"] = diagnostic_report
            quality_report["semantic_repair"] = semantic_repair
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
            mark_completed(f"idea_unit_agent:{segment.segment_id}:done")
        logger.write_json("idea_units.json", all_idea_units)
        logger.write_json("idea_unit_quality_validation.json", idea_unit_quality_reports)
        mark_completed("idea_unit_artifacts:written")

        extraction_batches, continuation_decisions = build_continuation_batches(
            all_segments,
            transcript_lines=lines,
            idea_units=all_idea_units,
        )
        logger.write_json("continuation_merges.json", continuation_decisions)
        logger.write_json("extraction_batches.json", extraction_batches)
        mark_completed("extraction_batches:written")

        raw_candidates = []
        batch_fallback_reports = []
        completed_batch_records: list[dict[str, Any]] = []
        for batch in extraction_batches:
            batch_units = idea_units_for_batch(all_idea_units, batch)
            if not batch_units:
                continue
            previous_context = build_previous_batch_context(
                completed_batch_records,
                current_batch_id=str(batch["batch_id"]),
                enabled=previous_context_enabled,
            )
            if previous_context_enabled:
                previous_context_by_batch[str(batch["batch_id"])] = previous_context
            batch_candidates = []
            for obj_type in agent_type_order:
                mark_started(f"l1_{obj_type}_agent:{batch['batch_id']}")
                logger.append_event(
                    f"l1_{obj_type}_agent:start",
                    {
                        "extraction_scope": batch["batch_id"],
                        "segment_ids": batch["segment_ids"],
                        "idea_units": len(batch_units),
                        "previous_context_items": len(previous_context.get("items", [])),
                    },
                )
                candidates = l1_type_agent(
                    runner,
                    obj_type=obj_type,
                    idea_units=batch_units,
                    existing_topics=existing_topics,
                    prior_context_pack=prior_context_pack,
                    previous_context=previous_context,
                    batch_metadata=batch,
                    extraction_scope=str(batch["batch_id"]),
                    segment_ids=list(batch["segment_ids"]),
                    taxonomy=taxonomy,
                    include_legacy_type=include_legacy_type,
                )
                batch_candidates.extend(candidates)
                logger.append_event(
                    f"l1_{obj_type}_agent:done",
                    {
                        "extraction_scope": batch["batch_id"],
                        "candidates": len(candidates),
                    },
                )
                mark_completed(f"l1_{obj_type}_agent:{batch['batch_id']}:done")
            if not batch_candidates:
                mark_started(f"l1_fallback_agent:{batch['batch_id']}")
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
                    prior_context_pack=prior_context_pack,
                    previous_context=previous_context,
                    batch_metadata=batch,
                    extraction_scope=str(batch["batch_id"]),
                    segment_ids=list(batch["segment_ids"]),
                    taxonomy=taxonomy,
                    include_legacy_type=include_legacy_type,
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
                mark_completed(f"l1_fallback_agent:{batch['batch_id']}:done")
            raw_candidates.extend(batch_candidates)
            completed_batch_records.append(
                {
                    "batch_id": str(batch["batch_id"]),
                    "segment_ids": list(batch["segment_ids"]),
                    "candidate_count": len(batch_candidates),
                    "candidates": [candidate.__dict__ for candidate in batch_candidates],
                }
            )
        logger.write_json("raw_candidates.json", raw_candidates)
        logger.write_json("batch_fallbacks.json", batch_fallback_reports)
        if previous_context_enabled:
            logger.write_json("previous_context_by_batch.json", previous_context_by_batch)
        mark_completed("raw_candidates:written")

        mark_started("evidence_grounding_agent:start")
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
        mark_completed("evidence_grounding_agent:done")

        mark_started("cross_type_conflict_resolver:start")
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
        mark_completed("cross_type_conflict_resolver:done")

        mark_started("verify_l1_candidates:start")
        logger.append_event("verify_l1_candidates:start", {"candidates": len(resolved_candidates)})
        verification = verify_l1_candidates(
            resolved_candidates,
            max_line=max_line,
            taxonomy=taxonomy,
        )
        verified_candidates = verification.verified_candidates
        rejected_candidates = verification.rejected_candidates
        logger.write_json("verified_candidates.json", verified_candidates)
        logger.write_json("rejected_candidates.json", rejected_candidates)
        logger.append_event(
            "verify_l1_candidates:done",
            {
                "verified": len(verified_candidates),
                "rejected": len(rejected_candidates),
            },
        )
        mark_completed("verify_l1_candidates:done")

        mark_started("reduce_l1_patch:start")
        logger.append_event(
            "reduce_l1_patch:start",
            {"verified": len(verified_candidates)},
        )
        final_patch, memory_objects, quality_index = reduce_l1_patch(
            verified_candidates,
            meeting_id=meeting_id,
            taxonomy=taxonomy,
            include_legacy_type=include_legacy_type,
        )
        logger.write_json("final_patch.json", final_patch)
        logger.write_json("l1_quality_index.json", quality_index)
        viewpoint_recurrence = final_patch.get("viewpoint_recurrence", [])
        logger.write_json("viewpoint_recurrence.json", viewpoint_recurrence)
        metrics_summary = build_metrics_summary(
            line_count=len(lines),
            window_plans=window_plans,
            initial_segments=initial_segments,
            final_segments=all_segments,
            coverage_reports=coverage_reports,
            coarsening_reports=coarsening_reports,
            boundary_refinement_reports=boundary_refinement_reports,
            idea_units=all_idea_units,
            idea_unit_quality_reports=idea_unit_quality_reports,
            extraction_batches=extraction_batches,
            continuation_decisions=continuation_decisions,
            previous_context_by_batch=previous_context_by_batch,
            raw_candidates=raw_candidates,
            batch_fallback_reports=batch_fallback_reports,
            grounded_candidates=grounded_candidates,
            conflict_decisions=conflict_decisions,
            verified_candidates=verified_candidates,
            rejected_candidates=rejected_candidates,
            memory_objects=memory_objects,
            viewpoint_recurrence=viewpoint_recurrence,
            llm_call_records=runner.call_records,
        )
        logger.write_json("metrics_summary.json", metrics_summary)
        logger.append_event(
            "reduce_l1_patch:done",
            {
                "memory_objects": len(memory_objects),
                "viewpoint_recurrence": len(viewpoint_recurrence),
            },
        )
        logger.append_event(
            "metrics_summary:done",
            {
                "final_l1_objects": metrics_summary["final_l1"]["object_count"],
                "verified_candidates": metrics_summary["candidates"]["verified_count"],
                "rejected_candidates": metrics_summary["candidates"]["rejected_count"],
            },
        )
        mark_completed("metrics_summary:done")

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
        pipeline_status = "succeeded"
        mark_completed("persist_l1:prepared")

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
            quality_index=quality_index,
            final_meeting_node=final_meeting_node,
            artifact_paths=artifact_paths,
        )
    except BaseException as exc:
        pipeline_status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        error_payload = {
            "type": type(exc).__name__,
            "message": str(exc),
            "last_started_stage": last_started_stage,
            "last_completed_stage": last_completed_stage,
        }
        logger.append_event("pipeline:error", error_payload)
        write_run_state(pipeline_status, error=error_payload)
        raise
    finally:
        if pipeline_status == "running":
            write_run_state(pipeline_status, stage=last_completed_stage)
