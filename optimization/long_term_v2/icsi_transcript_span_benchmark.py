from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_clean_dir, ensure_optimization_output, utc_now_iso, write_json, write_text


@dataclass(frozen=True)
class SeedTopic:
    topic_id: str
    label: str
    query_type: str
    query: str
    trigger_brief: str
    source_brief: str
    keywords: tuple[str, ...]


DEFAULT_SEED_TOPICS: tuple[SeedTopic, ...] = (
    SeedTopic(
        topic_id="close_microphones_beamforming",
        label="close microphones and beamforming",
        query_type="carryover_context",
        query=(
            "Before the later audio-processing discussion, what earlier context about "
            "close microphones and beamforming should the system remember?"
        ),
        trigger_brief="Later meeting revisits microphone choice, beamforming, or channel alignment.",
        source_brief="Past meeting discusses close microphones, beamforming, or related audio-channel rationale.",
        keywords=("close microphone", "close microphones", "beamforming", "delay-and-sum", "microphone", "channel"),
    ),
    SeedTopic(
        topic_id="annotation_tools_workflow",
        label="annotation tools and workflow",
        query_type="corpus_process",
        query=(
            "What earlier context about annotation tools and workflow should carry over "
            "when later meetings discuss transcript or annotation work?"
        ),
        trigger_brief="Later meeting revisits annotation tools, transcription workflow, or corpus annotation process.",
        source_brief="Past meeting discusses annotation tools, transcription workflow, or tool requirements.",
        keywords=("annotation", "annotate", "transcription", "xwaves", "alembic", "transcriber"),
    ),
    SeedTopic(
        topic_id="speaker_metadata",
        label="speaker metadata",
        query_type="evidence_lookup",
        query=(
            "What past evidence should the system retrieve about speaker metadata, "
            "regional information, or participant forms?"
        ),
        trigger_brief="Later meeting revisits speaker metadata, regions, dialect, or participant forms.",
        source_brief="Past meeting discusses speaker metadata, region, dialect, or forms.",
        keywords=("speaker metadata", "dialect", "region", "participant", "form", "accent"),
    ),
    SeedTopic(
        topic_id="training_data_and_digits",
        label="training data and digit-reading tasks",
        query_type="decision_rationale",
        query=(
            "What earlier decisions or rationale about training data and digit-reading "
            "tasks should be remembered for later BMR discussions?"
        ),
        trigger_brief="Later meeting revisits training data, acoustic models, or digit-reading tasks.",
        source_brief="Past meeting discusses training data, acoustic models, or digit-reading procedures.",
        keywords=("training data", "acoustic model", "digit", "digits", "read numbers", "numbers task"),
    ),
    SeedTopic(
        topic_id="recording_setup_quality",
        label="recording setup and data quality",
        query_type="next_meeting_carryover",
        query=(
            "What context about recording setup and data-quality issues should be carried "
            "into later BMR meetings?"
        ),
        trigger_brief="Later meeting revisits recording setup, data quality, broken equipment, or setup constraints.",
        source_brief="Past meeting discusses recording setup, data quality, equipment, or constraints.",
        keywords=("recording", "data quality", "setup", "broken", "equipment", "noise", "signal"),
    ),
)


def _meeting_number(meeting_id: str) -> int | None:
    match = re.search(r"(\d+)$", str(meeting_id))
    if not match:
        return None
    return int(match.group(1))


def _cutoff_number(meeting_id: str) -> int:
    value = _meeting_number(meeting_id)
    if value is None:
        raise ValueError(f"meeting id must end with digits: {meeting_id}")
    return value


def _line_matches(line: str, keywords: tuple[str, ...]) -> bool:
    text = line.lower()
    for keyword in keywords:
        clean = keyword.lower().strip()
        if not clean:
            continue
        if " " in clean:
            if clean in text:
                return True
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(clean)}(?![a-z0-9])", text):
            return True
    return False


def _load_transcript_lines(transcript_root: Path) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for path in sorted(transcript_root.glob("Bmr*.txt")):
        rows[path.stem] = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return rows


def _span_for_match(
    *,
    meeting_id: str,
    lines: list[str],
    line_index: int,
    source_file: str,
    brief: str,
    context_radius: int,
) -> dict[str, Any]:
    start = max(0, line_index - context_radius)
    end = min(len(lines), line_index + context_radius + 1)
    text = "\n".join(lines[start:end]).strip()
    return {
        "meeting_id": meeting_id,
        "source_file": source_file,
        "line_start": start + 1,
        "line_end": end,
        "brief": brief,
        "text_preview": text[:900],
        "annotation_status": "needs_human_review",
    }


def _find_spans(
    *,
    transcripts: dict[str, list[str]],
    topic: SeedTopic,
    cutoff: int,
    want_future: bool,
    limit: int,
    context_radius: int,
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for meeting_id, lines in sorted(transcripts.items()):
        number = _meeting_number(meeting_id)
        if number is None:
            continue
        if want_future and number <= cutoff:
            continue
        if not want_future and number > cutoff:
            continue
        for index, line in enumerate(lines):
            if _line_matches(line, topic.keywords):
                spans.append(
                    _span_for_match(
                        meeting_id=meeting_id,
                        lines=lines,
                        line_index=index,
                        source_file=f"{meeting_id}.txt",
                        brief=topic.trigger_brief if want_future else topic.source_brief,
                        context_radius=context_radius,
                    )
                )
                break
        if len(spans) >= limit:
            break
    return spans


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _format_markdown(report: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# ICSI Transcript-Span Benchmark Seeds",
        "",
        f"- status: `{report['status']}`",
        f"- generated at: `{report['generated_at_utc']}`",
        f"- source boundary: `{report['source_through_meeting_id']}`",
        f"- query count: `{report['query_count']}`",
        "",
        "These rows are annotation-ready seeds, not completed gold labels. A human reviewer must confirm the trigger span, past gold spans, and evidence brief before paper-facing evaluation.",
        "",
        "## Fairness Boundary",
        "",
        "- Primary gold is original transcript span evidence.",
        "- Generated L1 ids are diagnostic alignment only.",
        "- L2/L3 labels are optional navigation diagnostics, not primary gold.",
        "",
        "## Seed Questions",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"### {row['query_id']} `{row['query_type']}`",
                "",
                row["query"],
                "",
                f"- held-out trigger: `{row['trigger_span']['meeting_id']}` lines {row['trigger_span']['line_start']}-{row['trigger_span']['line_end']}",
                "- source gold spans:",
            ]
        )
        for span in row.get("gold_transcript_spans", []) or []:
            lines.append(
                f"  - `{span['meeting_id']}` lines {span['line_start']}-{span['line_end']}: {span['brief']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_transcript_span_benchmark(
    *,
    transcript_root: Path | str,
    out_dir: Path | str,
    source_through_meeting_id: str = "Bmr023",
    max_questions: int = 12,
    clean: bool = False,
    context_radius: int = 1,
) -> dict[str, Any]:
    transcript_path = Path(transcript_root)
    out_path = Path(out_dir)
    if clean and out_path.exists():
        ensure_clean_dir(out_path)
    else:
        ensure_optimization_output(out_path)

    transcripts = _load_transcript_lines(transcript_path)
    cutoff = _cutoff_number(source_through_meeting_id)
    rows: list[dict[str, Any]] = []
    for topic in DEFAULT_SEED_TOPICS:
        if len(rows) >= max_questions:
            break
        trigger_spans = _find_spans(
            transcripts=transcripts,
            topic=topic,
            cutoff=cutoff,
            want_future=True,
            limit=1,
            context_radius=context_radius,
        )
        source_spans = _find_spans(
            transcripts=transcripts,
            topic=topic,
            cutoff=cutoff,
            want_future=False,
            limit=2,
            context_radius=context_radius,
        )
        if not trigger_spans or not source_spans:
            continue
        trigger = trigger_spans[0]
        rows.append(
            {
                "schema_version": 1,
                "query_id": f"icsi-span-q{len(rows) + 1:03d}",
                "benchmark_type": "heldout_future_transcript_span",
                "query_type": topic.query_type,
                "query": topic.query,
                "held_out_meeting_id": trigger["meeting_id"],
                "trigger_span": trigger,
                "gold_transcript_spans": source_spans,
                "primary_gold_source": "transcript_span",
                "l1_gold_policy": "diagnostic_alignment_only",
                "optional_alignment": {
                    "expected_l1_ids": [],
                    "expected_l2_labels": [topic.label],
                    "expected_l3_labels": [],
                },
                "annotation_status": "needs_human_review",
                "review_instructions": [
                    "Confirm the future trigger span describes a real carryover need.",
                    "Confirm the past transcript spans support the answer without using generated L1 as gold.",
                    "Optionally map spans to generated L1 ids only after transcript evidence is approved.",
                ],
            }
        )

    status = "annotation_ready_needs_human_review" if rows else "blocked_no_supported_transcript_spans"
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "transcript_root": str(transcript_path),
        "source_through_meeting_id": source_through_meeting_id,
        "meeting_count": len(transcripts),
        "query_count": len(rows),
        "primary_gold_source": "transcript_span",
        "l1_gold_policy": "diagnostic_alignment_only",
        "queries": rows,
        "notes": [
            "This builder creates annotation-ready seeds, not completed human gold.",
            "Generated L1 ids are intentionally absent from primary gold fields.",
            "Human review is required before using rows as public benchmark evidence.",
        ],
    }
    _write_jsonl(out_path / "transcript_span_queries.jsonl", rows)
    write_json(out_path / "transcript_span_benchmark_report.json", report)
    write_text(out_path / "transcript_span_benchmark.md", _format_markdown(report, rows))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Create annotation-ready ICSI transcript-span benchmark seeds.")
    parser.add_argument("--transcript-root", default=str(REPO_ROOT / "meeting_recording" / "transcript" / "ISCI"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-through-meeting-id", default="Bmr023")
    parser.add_argument("--max-questions", type=int, default=12)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    report = build_transcript_span_benchmark(
        transcript_root=args.transcript_root,
        out_dir=args.out,
        source_through_meeting_id=args.source_through_meeting_id,
        max_questions=args.max_questions,
        clean=args.clean,
    )
    print(
        f"wrote {report['query_count']} transcript-span seed question(s) "
        f"with status={report['status']}"
    )


if __name__ == "__main__":
    main()
