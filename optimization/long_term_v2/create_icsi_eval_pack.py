from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.effective_view import load_effective_topic_surface
from optimization.long_term_v2.io_utils import (
    ensure_clean_dir,
    ensure_optimization_output,
    load_json,
    utc_now_iso,
    write_json,
    write_text,
)
from optimization.long_term_v2.profiles import (
    load_profile,
    profile_generic_topic_labels,
    profile_rejected_topic_labels,
    profile_type_like_labels,
    profile_weak_child_terms,
    profile_weak_phrase_terms,
)
from optimization.long_term_v2.text_utils import tokens
from share_mem.store import build_l1_index, load_share_tree, normalize_share_tree, refresh_share_mem_outputs


DEFAULT_WEAK_TERMS = {
    "ahead",
    "bit",
    "backed",
    "decided",
    "did",
    "didn",
    "five",
    "go",
    "gonna",
    "guess",
    "hmm",
    "hub",
    "know",
    "little",
    "mm",
    "oh",
    "okay",
    "pretty",
    "probably",
    "team",
    "week",
    "so",
    "thing",
    "things",
    "uh",
    "um",
    "well",
}

DEFAULT_TYPE_TERMS = {
    "argument",
    "decision",
    "finding",
    "issue",
    "proposal",
    "question",
    "result",
    "todo",
}

QUERY_TYPE_TEMPLATES = {
    "evidence_lookup": "What concrete source-side evidence did the ICSI BMR meetings contain about {label}?",
    "topic_evolution": "Before the held-out meetings, how had {label} evolved across the ICSI BMR discussions?",
    "decision_rationale": "What decisions or rationale were established about {label} before the later BMR meetings revisited it?",
    "next_meeting_carryover": "What context about {label} should be carried into later BMR meetings?",
    "corpus_process": "What does the source-side BMR corpus reveal about the process or workflow around {label}?",
}


def _meeting_number(meeting_id: str) -> int | None:
    match = re.search(r"(\d+)$", str(meeting_id))
    if not match:
        return None
    return int(match.group(1))


def _source_cutoff_number(source_through_meeting_id: str) -> int:
    value = _meeting_number(source_through_meeting_id)
    if value is None:
        raise ValueError(f"source_through_meeting_id must end with digits: {source_through_meeting_id}")
    return value


def _load_profile_for_run(run_root: Path) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = load_json(manifest_path)
    profile_path = manifest.get("profile_path") if isinstance(manifest, dict) else ""
    if profile_path and Path(str(profile_path)).exists():
        return load_profile(str(profile_path))
    return {}


def _label_is_candidate(label: str, *, profile: dict[str, Any]) -> bool:
    raw = str(label).strip()
    clean = raw.lower().replace("_", " ")
    if not clean:
        return False
    label_tokens = set(tokens(clean))
    if len(label_tokens) < 2:
        return False
    type_like = profile_type_like_labels(profile) | DEFAULT_TYPE_TERMS
    generic = profile_generic_topic_labels(profile)
    rejected = profile_rejected_topic_labels(profile)
    weak = profile_weak_phrase_terms(profile) | profile_weak_child_terms(profile) | DEFAULT_WEAK_TERMS
    if clean in rejected or clean in type_like or clean in generic:
        return False
    if label_tokens & rejected or label_tokens & type_like or label_tokens & weak:
        return False
    if len(label_tokens - generic) < 2:
        return False
    return True


def _partition_obj_ids(
    obj_ids: list[str],
    *,
    l1_index: dict[str, dict[str, Any]],
    source_cutoff: int,
) -> tuple[list[str], list[str]]:
    source: list[str] = []
    heldout: list[str] = []
    for obj_id in obj_ids:
        row = l1_index.get(str(obj_id))
        if not row:
            continue
        meeting_number = _meeting_number(str(row.get("meeting_id", "") or ""))
        if meeting_number is None:
            continue
        if meeting_number <= source_cutoff:
            source.append(str(obj_id))
        else:
            heldout.append(str(obj_id))
    return source, heldout


def _sorted_obj_ids(obj_ids: list[str], l1_index: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        dict.fromkeys(obj_ids),
        key=lambda obj_id: (
            str(l1_index.get(obj_id, {}).get("meeting_date", "") or ""),
            str(l1_index.get(obj_id, {}).get("meeting_id", "") or ""),
            obj_id,
        ),
    )


def _l3_expectations(
    obj_ids: list[str],
    *,
    l3_index: dict[str, Any],
) -> tuple[list[str], list[str]]:
    ids: set[str] = set()
    labels: set[str] = set()
    for obj_id in obj_ids:
        row = l3_index.get(obj_id)
        if not isinstance(row, dict):
            continue
        parent_id = str(row.get("parent_l3_id", "") or row.get("l3_id", "") or "")
        parent_label = str(row.get("parent_l3_label", "") or row.get("l3_label", "") or "")
        if parent_id:
            ids.add(parent_id)
        if parent_label:
            labels.add(parent_label)
    return sorted(ids), sorted(labels)


def _evidence_preview(obj_ids: list[str], *, l1_index: dict[str, dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for obj_id in obj_ids[:limit]:
        row = l1_index.get(obj_id, {})
        previews.append(
            {
                "obj_id": obj_id,
                "meeting_id": row.get("meeting_id", ""),
                "type": row.get("type", ""),
                "content": str(row.get("content", "") or "")[:420],
            }
        )
    return previews


def _candidate_nodes(
    *,
    surface: dict[str, Any],
    l1_index: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    source_cutoff: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for node in surface["l2_view"].get("l2_nodes", []) or []:
        if not isinstance(node, dict):
            continue
        label = str(node.get("label", "") or "").strip()
        l2_id = str(node.get("l2_id", "") or "").strip()
        if not label or not l2_id or not _label_is_candidate(label, profile=profile):
            continue
        linked_ids = [str(obj_id) for obj_id in node.get("linked_obj_ids", []) or [] if str(obj_id).strip()]
        source_ids, heldout_ids = _partition_obj_ids(linked_ids, l1_index=l1_index, source_cutoff=source_cutoff)
        source_ids = _sorted_obj_ids(source_ids, l1_index)
        heldout_ids = _sorted_obj_ids(heldout_ids, l1_index)
        if len(source_ids) < 2 or not heldout_ids:
            continue
        source_meetings = {str(l1_index[obj_id].get("meeting_id", "") or "") for obj_id in source_ids}
        heldout_meetings = {str(l1_index[obj_id].get("meeting_id", "") or "") for obj_id in heldout_ids}
        candidates.append(
            {
                "node": node,
                "l2_id": l2_id,
                "label": label,
                "source_ids": source_ids,
                "heldout_ids": heldout_ids,
                "source_meeting_count": len(source_meetings),
                "heldout_meeting_count": len(heldout_meetings),
                "source_event_count": len(source_ids),
                "heldout_event_count": len(heldout_ids),
            }
        )
    candidates.sort(
        key=lambda item: (
            -item["heldout_meeting_count"],
            -item["source_meeting_count"],
            -item["source_event_count"],
            item["label"],
        )
    )
    return candidates


def _query_row(
    *,
    query_id: str,
    query_type: str,
    candidate: dict[str, Any],
    l3_index: dict[str, Any],
    l1_index: dict[str, dict[str, Any]],
    source_through_meeting_id: str,
) -> dict[str, Any]:
    label = candidate["label"]
    source_ids = candidate["source_ids"][:4]
    heldout_ids = candidate["heldout_ids"][:4]
    expected_l3_ids, expected_l3_labels = _l3_expectations(source_ids, l3_index=l3_index)
    return {
        "schema_version": 1,
        "query_id": query_id,
        "benchmark_type": "heldout_future_meeting",
        "query_type": query_type,
        "query": QUERY_TYPE_TEMPLATES[query_type].format(label=label),
        "answer_boundary": f"Use only source-side meetings through {source_through_meeting_id}.",
        "answer_from_meetings": sorted(
            {str(l1_index[obj_id].get("meeting_id", "") or "") for obj_id in source_ids}
        ),
        "heldout_trigger_meetings": sorted(
            {str(l1_index[obj_id].get("meeting_id", "") or "") for obj_id in heldout_ids}
        ),
        "expected_obj_ids": source_ids,
        "expected_source_obj_ids": source_ids,
        "heldout_trigger_obj_ids": heldout_ids,
        "expected_l2_ids": [candidate["l2_id"]],
        "expected_l2_labels": [label],
        "expected_l3_ids": expected_l3_ids,
        "expected_l3_labels": expected_l3_labels,
        "source_evidence_preview": _evidence_preview(source_ids, l1_index=l1_index),
        "heldout_trigger_preview": _evidence_preview(heldout_ids, l1_index=l1_index),
        "scoring_rubric": {
            "factual_correctness": "Answer facts must be supported by source-side evidence.",
            "evidence_grounding": "Cite or paraphrase the expected source L1 objects.",
            "topic_evolution": "For evolution/rationale questions, explain change across source-side meetings.",
            "temporal_boundary": "Do not use held-out trigger evidence as answer evidence.",
            "hallucination_risk": "Do not invent decisions, motivations, or action items absent from source evidence.",
        },
        "provenance": {
            "source": "optimization_v2_heldout_future_meeting_pack",
            "source_through_meeting_id": source_through_meeting_id,
            "manual_review_required": True,
        },
        "status": "candidate_manual_review_required",
    }


def _write_source_share_mem(
    *,
    tree: dict[str, Any],
    out_dir: Path,
    source_cutoff: int,
) -> dict[str, Any]:
    source_meetings = []
    for meeting in normalize_share_tree(tree).get("meetings", []) or []:
        if not isinstance(meeting, dict):
            continue
        meeting_number = _meeting_number(str(meeting.get("meeting_id", "") or ""))
        if meeting_number is not None and meeting_number <= source_cutoff:
            source_meetings.append(meeting)
    source_tree = {**normalize_share_tree(tree), "meetings": source_meetings}
    return refresh_share_mem_outputs(root=out_dir / "source_share_mem", tree=source_tree)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _format_markdown(report: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# ICSI Held-Out Future-Meeting Eval Pack",
        "",
        f"- status: `{report['status']}`",
        f"- generated at: `{report['generated_at_utc']}`",
        f"- source boundary: `{report['source_through_meeting_id']}`",
        f"- query count: `{report['query_count']}`",
        f"- candidate topic count: `{report['candidate_topic_count']}`",
        "",
        "This pack is designed for manual review before professor-facing claims. Held-out BMR meetings are used only as future triggers; expected answers must come from the source-side share_mem snapshot.",
        "",
        "## Manual Review Checklist",
        "",
        "- Confirm the query is answerable from the source-side evidence only.",
        "- Confirm held-out trigger evidence is not used as expected answer evidence.",
        "- Confirm expected L2 labels are not filler, discourse markers, or generic buckets.",
        "- Confirm the scoring rubric matches the query type.",
        "",
        "## Candidate Questions",
        "",
    ]
    for row in rows:
        lines.append(f"### {row['query_id']} `{row['query_type']}`")
        lines.append("")
        lines.append(row["query"])
        lines.append("")
        lines.append(f"- expected L2: `{', '.join(row['expected_l2_labels'])}`")
        if row.get("expected_l3_labels"):
            lines.append(f"- expected L3: `{', '.join(row['expected_l3_labels'])}`")
        lines.append(f"- source meetings: `{', '.join(row['answer_from_meetings'])}`")
        lines.append(f"- held-out triggers: `{', '.join(row['heldout_trigger_meetings'])}`")
        lines.append("- source evidence:")
        for preview in row.get("source_evidence_preview", []) or []:
            lines.append(
                f"  - `{preview['obj_id']}` `{preview['meeting_id']}` {preview['content']}"
            )
        lines.append("- held-out trigger examples:")
        for preview in row.get("heldout_trigger_preview", []) or []:
            lines.append(
                f"  - `{preview['obj_id']}` `{preview['meeting_id']}` {preview['content']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def create_icsi_eval_pack(
    *,
    run_root: Path | str,
    share_mem_root: Path | str,
    out_dir: Path | str,
    source_through_meeting_id: str = "Bmr023",
    max_questions: int = 20,
    clean: bool = False,
) -> dict[str, Any]:
    run_path = Path(run_root)
    out_path = Path(out_dir)
    if clean and out_path.exists():
        ensure_clean_dir(out_path)
    else:
        ensure_optimization_output(out_path)

    tree = load_share_tree(share_mem_root)
    l1_index = build_l1_index(tree)
    source_cutoff = _source_cutoff_number(source_through_meeting_id)
    source_manifest = _write_source_share_mem(tree=tree, out_dir=out_path, source_cutoff=source_cutoff)

    surface = load_effective_topic_surface(run_path)
    profile = _load_profile_for_run(run_path)
    candidates = _candidate_nodes(
        surface=surface,
        l1_index=l1_index,
        profile=profile,
        source_cutoff=source_cutoff,
    )

    rows: list[dict[str, Any]] = []
    query_types = list(QUERY_TYPE_TEMPLATES)
    round_index = 0
    while len(rows) < max_questions and candidates:
        made_progress = False
        for candidate in candidates:
            if len(rows) >= max_questions:
                break
            if round_index > 0 and len(candidates) >= max_questions:
                break
            query_type = query_types[len(rows) % len(query_types)]
            rows.append(
                _query_row(
                    query_id=f"icsi-heldout-q{len(rows) + 1:03d}",
                    query_type=query_type,
                    candidate=candidate,
                    l3_index=surface["l3_index"],
                    l1_index=l1_index,
                    source_through_meeting_id=source_through_meeting_id,
                )
            )
            made_progress = True
        if not made_progress:
            break
        round_index += 1

    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": "candidate_manual_review_required",
        "run_root": str(run_path.resolve()),
        "share_mem_root": str(Path(share_mem_root).resolve()),
        "source_share_mem_root": str((out_path / "source_share_mem").resolve()),
        "source_through_meeting_id": source_through_meeting_id,
        "source_manifest": source_manifest,
        "effective_topic_surface": {
            "active_l2_count": surface["active_l2_count"],
            "suppressed_l2_count": surface["suppressed_l2_count"],
            "l3_surface_source": surface.get("l3_surface_source", "raw_l3"),
        },
        "candidate_topic_count": len(candidates),
        "query_count": len(rows),
        "query_type_counts": {query_type: sum(row["query_type"] == query_type for row in rows) for query_type in query_types},
        "queries": rows,
        "notes": [
            "Held-out meetings are triggers for question construction only.",
            "Expected answer evidence comes from source-side meetings only.",
            "Rows remain candidate_manual_review_required until a human approves them.",
        ],
    }

    _write_jsonl(out_path / "heldout_eval_queries.jsonl", rows)
    write_json(out_path / "heldout_eval_pack_report.json", report)
    write_text(out_path / "heldout_eval_pack.md", _format_markdown(report, rows))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an ICSI held-out future-meeting eval pack from optimization v2 outputs.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--share-mem-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-through-meeting-id", default="Bmr023")
    parser.add_argument("--max-questions", type=int, default=20)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    report = create_icsi_eval_pack(
        run_root=args.run_root,
        share_mem_root=args.share_mem_root,
        out_dir=args.out,
        source_through_meeting_id=args.source_through_meeting_id,
        max_questions=args.max_questions,
        clean=args.clean,
    )
    print(
        "[optimization:v2] ICSI held-out eval pack complete: "
        f"queries={report['query_count']} candidates={report['candidate_topic_count']} "
        f"source_meetings={report['source_manifest']['meeting_count']}"
    )


if __name__ == "__main__":
    main()
