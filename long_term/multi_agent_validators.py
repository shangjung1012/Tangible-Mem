"""Deterministic upstream validators and repairs for multi-agent L1 extraction."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from multi_agent_state import IdeaUnit, SegmentProposal, TranscriptLine, WindowPlan
from multi_agent_tools import evidence_quote, jaccard, tokenize

MAX_IDEA_UNIT_LINE_SPAN = 8
MAX_IDEA_UNIT_TEXT_CHARS = 420
MIN_IDEA_UNIT_TEXT_CHARS = 6
MAX_IDEA_UNITS_PER_SEGMENT = 12
DUPLICATE_IDEA_UNIT_THRESHOLD = 0.82
MIN_DURABLE_SEGMENT_LINES = 8
MAX_DURABLE_SEGMENT_LINES = 24


def compact_ranges(line_ids: list[int]) -> list[dict[str, int]]:
    if not line_ids:
        return []
    sorted_ids = sorted(set(line_ids))
    ranges: list[dict[str, int]] = []
    start = previous = sorted_ids[0]
    for line_id in sorted_ids[1:]:
        if line_id == previous + 1:
            previous = line_id
            continue
        ranges.append({"start_line": start, "end_line": previous})
        start = previous = line_id
    ranges.append({"start_line": start, "end_line": previous})
    return ranges


def _window_line_ids(plan: WindowPlan) -> set[int]:
    return set(range(plan.start_line, plan.end_line + 1))


def _covered_lines(start_line: int, end_line: int, rows: list[Any]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for row in rows:
        row_start = max(start_line, int(row.line_start))
        row_end = min(end_line, int(row.line_end))
        if row_end < row_start:
            continue
        for line_id in range(row_start, row_end + 1):
            counts[line_id] = counts.get(line_id, 0) + 1
    return counts


def repair_segment_coverage(
    plan: WindowPlan,
    segments: list[SegmentProposal],
) -> tuple[list[SegmentProposal], dict[str, Any]]:
    """Patch segmentation gaps so downstream stages can still see every line."""
    expected_lines = _window_line_ids(plan)
    coverage_counts = _covered_lines(plan.start_line, plan.end_line, segments)
    uncovered_lines = sorted(expected_lines - set(coverage_counts))
    overlapped_lines = sorted(
        line_id
        for line_id, count in coverage_counts.items()
        if count > 1 and line_id in expected_lines
    )
    window_line_count = max(1, len(expected_lines))
    coverage_rate = (window_line_count - len(uncovered_lines)) / window_line_count
    uncovered_ranges = compact_ranges(uncovered_lines)
    overlap_ranges = compact_ranges(overlapped_lines)

    repaired_segments = list(segments)
    repair_ids: list[str] = []
    for index, missing_range in enumerate(uncovered_ranges, start=1):
        previous_segment = max(
            (
                segment
                for segment in segments
                if segment.line_end < missing_range["start_line"]
            ),
            key=lambda segment: segment.line_end,
            default=None,
        )
        next_segment = min(
            (
                segment
                for segment in segments
                if segment.line_start > missing_range["end_line"]
            ),
            key=lambda segment: segment.line_start,
            default=None,
        )
        neighbor_topics = [
            segment.topic_label
            for segment in [previous_segment, next_segment]
            if segment is not None and segment.topic_label
        ]
        topic_label = (
            "coverage repair near " + " / ".join(dict.fromkeys(neighbor_topics))
            if neighbor_topics
            else (
                "coverage repair "
                f"lines {missing_range['start_line']}-{missing_range['end_line']}"
            )
        )
        repair_segment = SegmentProposal(
            segment_id=f"S-{plan.start_line:04d}-R{index:02d}",
            line_start=missing_range["start_line"],
            line_end=missing_range["end_line"],
            topic_label=topic_label,
            needs_more_context=True,
        )
        repaired_segments.append(repair_segment)
        repair_ids.append(repair_segment.segment_id)

    report = {
        "window_start": plan.start_line,
        "window_end": plan.end_line,
        "input_segments": len(segments),
        "output_segments": len(repaired_segments),
        "coverage_rate": round(coverage_rate, 3),
        "uncovered_ranges": uncovered_ranges,
        "overlap_ranges": overlap_ranges,
        "repair_segment_ids": repair_ids,
    }
    return repaired_segments, report


def _line_span(start_line: int, end_line: int) -> int:
    return max(0, int(end_line) - int(start_line) + 1)


def _merge_segment_group(
    group: list[SegmentProposal],
    *,
    plan: WindowPlan,
    index: int,
) -> SegmentProposal:
    if len(group) == 1:
        return group[0]
    topic_labels = list(dict.fromkeys(segment.topic_label for segment in group if segment.topic_label))
    return SegmentProposal(
        segment_id=f"S-{plan.start_line:04d}-C{index:02d}",
        line_start=min(segment.line_start for segment in group),
        line_end=max(segment.line_end for segment in group),
        topic_label=" / ".join(topic_labels) or "coarsened discussion segment",
        needs_more_context=any(segment.needs_more_context for segment in group),
    )


def coarsen_segments_for_window(
    plan: WindowPlan,
    segments: list[SegmentProposal],
) -> tuple[list[SegmentProposal], dict[str, Any]]:
    """Merge over-fragmented adjacent segments into durable extraction spans."""
    sorted_segments = sorted(
        segments,
        key=lambda segment: (segment.line_start, segment.line_end, segment.segment_id),
    )
    groups: list[list[SegmentProposal]] = []
    current: list[SegmentProposal] = []

    for segment in sorted_segments:
        if not current:
            current = [segment]
            continue
        current_start = min(row.line_start for row in current)
        proposed_span = _line_span(current_start, segment.line_end)
        current_span = _line_span(current_start, max(row.line_end for row in current))
        adjacent = segment.line_start <= max(row.line_end for row in current) + 1
        if adjacent and (current_span < MIN_DURABLE_SEGMENT_LINES or proposed_span <= MAX_DURABLE_SEGMENT_LINES):
            current.append(segment)
            continue
        groups.append(current)
        current = [segment]

    if current:
        groups.append(current)

    coarsened = [
        _merge_segment_group(group, plan=plan, index=index)
        for index, group in enumerate(groups, start=1)
    ]
    merged_groups = [
        {
            "output_segment_id": coarsened[index].segment_id,
            "source_segment_ids": [segment.segment_id for segment in group],
            "line_start": coarsened[index].line_start,
            "line_end": coarsened[index].line_end,
        }
        for index, group in enumerate(groups)
        if len(group) > 1
    ]
    report = {
        "window_start": plan.start_line,
        "window_end": plan.end_line,
        "input_segments": len(segments),
        "output_segments": len(coarsened),
        "merged_groups": merged_groups,
    }
    return coarsened, report


def _idea_unit_tokens(unit: IdeaUnit) -> set[str]:
    return tokenize(unit.text)


def _line_count(start_line: int, end_line: int) -> int:
    return max(0, int(end_line) - int(start_line) + 1)


def _trim_text(text: str, *, max_chars: int = MAX_IDEA_UNIT_TEXT_CHARS) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "..."


def _fallback_units_for_span(
    *,
    segment: SegmentProposal,
    transcript_lines: list[TranscriptLine],
    start_line: int,
    end_line: int,
    reason: str,
    start_index: int,
) -> list[IdeaUnit]:
    units: list[IdeaUnit] = []
    current = max(segment.line_start, start_line)
    final = min(segment.line_end, end_line)
    index = start_index
    while current <= final:
        chunk_end = min(final, current + MAX_IDEA_UNIT_LINE_SPAN - 1)
        quote = evidence_quote(
            transcript_lines,
            list(range(current, chunk_end + 1)),
            max_chars=MAX_IDEA_UNIT_TEXT_CHARS,
        )
        text = quote or f"Transcript lines {current}-{chunk_end}"
        units.append(
            IdeaUnit(
                unit_id=f"U-{segment.segment_id}-R{index:02d}",
                segment_id=segment.segment_id,
                line_start=current,
                line_end=chunk_end,
                text=text,
                completeness="fallback",
                uncertainty_note=reason,
            )
        )
        index += 1
        current = chunk_end + 1
    return units


def _compact_unit_groups(sorted_units: list[IdeaUnit]) -> list[list[IdeaUnit]]:
    groups: list[list[IdeaUnit]] = []
    current: list[IdeaUnit] = []
    for unit in sorted_units:
        if not current:
            current = [unit]
            continue
        proposed_start = min(row.line_start for row in current)
        proposed_end = max(max(row.line_end for row in current), unit.line_end)
        if _line_count(proposed_start, proposed_end) > MAX_IDEA_UNIT_LINE_SPAN:
            groups.append(current)
            current = [unit]
            continue
        current.append(unit)
    if current:
        groups.append(current)
    if len(groups) <= MAX_IDEA_UNITS_PER_SEGMENT:
        return groups
    chunk_size = max(
        1,
        (len(sorted_units) + MAX_IDEA_UNITS_PER_SEGMENT - 1) // MAX_IDEA_UNITS_PER_SEGMENT,
    )
    return [
        sorted_units[index : index + chunk_size]
        for index in range(0, len(sorted_units), chunk_size)
    ]


def repair_idea_units_for_segment(
    *,
    segment: SegmentProposal,
    units: list[IdeaUnit],
    transcript_lines: list[TranscriptLine],
) -> tuple[list[IdeaUnit], dict[str, Any]]:
    """Validate and lightly repair idea units before typed L1 agents consume them."""
    issues: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    repaired: list[IdeaUnit] = []
    repair_index = 1

    for unit in units:
        text = str(unit.text or "").strip()
        if not text:
            issues.append({"unit_id": unit.unit_id, "issue": "empty_text"})
            repairs.append({"unit_id": unit.unit_id, "action": "drop_empty"})
            continue

        clean_unit = unit
        if unit.line_start < segment.line_start or unit.line_end > segment.line_end:
            clean_unit = replace(
                unit,
                line_start=max(segment.line_start, unit.line_start),
                line_end=min(segment.line_end, unit.line_end),
            )
            issues.append({"unit_id": unit.unit_id, "issue": "out_of_segment_bounds"})
            repairs.append({"unit_id": unit.unit_id, "action": "clamp_to_segment"})
        if clean_unit.line_end < clean_unit.line_start:
            issues.append({"unit_id": unit.unit_id, "issue": "invalid_line_range"})
            repairs.append({"unit_id": unit.unit_id, "action": "drop_invalid_range"})
            continue

        line_span = _line_count(clean_unit.line_start, clean_unit.line_end)
        if line_span > MAX_IDEA_UNIT_LINE_SPAN:
            issues.append(
                {
                    "unit_id": unit.unit_id,
                    "issue": "too_fat_line_span",
                    "line_span": line_span,
                }
            )
            fallback_units = _fallback_units_for_span(
                segment=segment,
                transcript_lines=transcript_lines,
                start_line=clean_unit.line_start,
                end_line=clean_unit.line_end,
                reason=f"validator split fat unit {unit.unit_id}",
                start_index=repair_index,
            )
            repaired.extend(fallback_units)
            repair_index += len(fallback_units)
            repairs.append(
                {
                    "unit_id": unit.unit_id,
                    "action": "replace_with_line_chunks",
                    "replacement_unit_ids": [fallback.unit_id for fallback in fallback_units],
                }
            )
            continue

        if len(text) < MIN_IDEA_UNIT_TEXT_CHARS:
            issues.append(
                {
                    "unit_id": unit.unit_id,
                    "issue": "too_short_text",
                    "text_chars": len(text),
                }
            )

        if len(text) > MAX_IDEA_UNIT_TEXT_CHARS:
            issues.append(
                {
                    "unit_id": unit.unit_id,
                    "issue": "too_long_text",
                    "text_chars": len(text),
                }
            )

        duplicate_of = ""
        clean_tokens = _idea_unit_tokens(clean_unit)
        for existing in repaired:
            if not (set(range(clean_unit.line_start, clean_unit.line_end + 1)) & set(
                range(existing.line_start, existing.line_end + 1)
            )):
                continue
            if jaccard(clean_unit.text, existing.text) >= DUPLICATE_IDEA_UNIT_THRESHOLD:
                duplicate_of = existing.unit_id
                break
            if clean_tokens and clean_tokens == _idea_unit_tokens(existing):
                duplicate_of = existing.unit_id
                break
        if duplicate_of:
            issues.append(
                {
                    "unit_id": unit.unit_id,
                    "issue": "duplicate_or_high_overlap",
                    "duplicate_of": duplicate_of,
                }
            )
            repairs.append(
                {
                    "unit_id": unit.unit_id,
                    "action": "drop_duplicate",
                    "duplicate_of": duplicate_of,
                }
            )
            continue

        repaired.append(clean_unit)

    if not repaired:
        fallback_units = _fallback_units_for_span(
            segment=segment,
            transcript_lines=transcript_lines,
            start_line=segment.line_start,
            end_line=segment.line_end,
            reason="validator fallback for empty or unusable idea-unit output",
            start_index=repair_index,
        )
        repaired.extend(fallback_units)
        repairs.append(
            {
                "action": "fallback_for_empty_segment",
                "replacement_unit_ids": [fallback.unit_id for fallback in fallback_units],
            }
        )

    coverage_counts = _covered_lines(segment.line_start, segment.line_end, repaired)
    uncovered_lines = sorted(
        set(range(segment.line_start, segment.line_end + 1)) - set(coverage_counts)
    )
    uncovered_ranges = compact_ranges(uncovered_lines)
    if uncovered_ranges:
        added_ids: list[str] = []
        for missing_range in uncovered_ranges:
            fallback_units = _fallback_units_for_span(
                segment=segment,
                transcript_lines=transcript_lines,
                start_line=missing_range["start_line"],
                end_line=missing_range["end_line"],
                reason="validator fallback for idea-unit coverage gap",
                start_index=repair_index,
            )
            repaired.extend(fallback_units)
            repair_index += len(fallback_units)
            added_ids.extend(fallback.unit_id for fallback in fallback_units)
        issues.append(
            {
                "issue": "uncovered_line_ranges",
                "uncovered_ranges": uncovered_ranges,
            }
        )
        repairs.append(
            {
                "action": "add_fallback_for_uncovered_lines",
                "replacement_unit_ids": added_ids,
            }
        )

    if len(repaired) > MAX_IDEA_UNITS_PER_SEGMENT:
        sorted_units = sorted(
            repaired,
            key=lambda unit: (unit.line_start, unit.line_end, unit.unit_id),
        )
        compacted: list[IdeaUnit] = []
        groups = _compact_unit_groups(sorted_units)
        for group in groups:
            group_index = len(compacted) + 1
            line_start = min(unit.line_start for unit in group)
            line_end = max(unit.line_end for unit in group)
            text = _trim_text("; ".join(dict.fromkeys(unit.text for unit in group if unit.text)))
            compacted.append(
                IdeaUnit(
                    unit_id=f"U-{segment.segment_id}-C{group_index:02d}",
                    segment_id=segment.segment_id,
                    line_start=line_start,
                    line_end=line_end,
                    text=text,
                    completeness="compacted",
                    uncertainty_note=(
                        "validator compacted over-fragmented idea units "
                        f"from {len(group)} source units"
                    ),
                )
            )
        issues.append(
            {
                "issue": "too_many_units",
                "input_units": len(repaired),
                "max_units": MAX_IDEA_UNITS_PER_SEGMENT,
            }
        )
        repairs.append(
            {
                "action": "compact_overfragmented_units",
                "input_units": len(repaired),
                "replacement_unit_ids": [unit.unit_id for unit in compacted],
            }
        )
        repaired = compacted

    repaired = sorted(
        repaired,
        key=lambda unit: (unit.line_start, unit.line_end, unit.unit_id),
    )
    segment_lines = set(range(segment.line_start, segment.line_end + 1))
    coverage_counts = _covered_lines(segment.line_start, segment.line_end, repaired)
    uncovered_lines = sorted(segment_lines - set(coverage_counts))
    overlapped_lines = sorted(
        line_id
        for line_id, count in coverage_counts.items()
        if count > 1 and line_id in segment_lines
    )
    coverage_rate = (len(segment_lines) - len(uncovered_lines)) / max(1, len(segment_lines))

    report = {
        "segment_id": segment.segment_id,
        "line_start": segment.line_start,
        "line_end": segment.line_end,
        "input_units": len(units),
        "output_units": len(repaired),
        "coverage_rate": round(coverage_rate, 3),
        "uncovered_ranges": compact_ranges(uncovered_lines),
        "overlap_ranges": compact_ranges(overlapped_lines),
        "issues": issues,
        "repairs": repairs,
    }
    return repaired, report
