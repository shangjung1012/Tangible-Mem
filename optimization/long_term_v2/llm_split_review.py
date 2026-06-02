from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.llm_topic_refinement import _extract_json, _response_text, _usage_metadata
from optimization.long_term_v2.profiles import load_profile
from optimization.long_term_v2.validate_llm_proposals import _label_rejection


def _sample_timeline(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        selected = list(rows)
    else:
        selected = []
        for index in range(limit):
            source_index = round(index * (len(rows) - 1) / max(limit - 1, 1))
            selected.append(rows[source_index])
    return [
        {
            "obj_id": row.get("obj_id", ""),
            "meeting_id": row.get("meeting_id", ""),
            "meeting_date": row.get("meeting_date", ""),
            "summary": str(row.get("summary", "") or "")[:260],
        }
        for row in selected
    ]


def _split_review_source_ids(root: Path) -> set[str]:
    review_path = root / "l3" / "l2_merge_review.json"
    if not review_path.exists():
        return set()
    review = load_json(review_path)
    return {
        str(row.get("source_l2_id", "") or "")
        for row in review.get("merge_reviews", []) or []
        if row.get("action") == "needs_split_review" and row.get("source_l2_id")
    }


def _compact_split_source(node: dict[str, Any], *, sample_limit: int) -> dict[str, Any]:
    return {
        "source_l2_id": node.get("l2_id", ""),
        "label": node.get("label", ""),
        "event_count": len(node.get("linked_obj_ids", []) or []),
        "representative_l1_ids": node.get("representative_l1_ids", [])[:8],
        "top_semantic_terms": node.get("top_semantic_terms", [])[:18],
        "timeline_sample": _sample_timeline(node.get("timeline_digest", []) or [], limit=sample_limit),
    }


def _build_prompt(sources: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    payload = {
        "task": "For each oversized L2 that deterministic splitting could not safely materialize, propose evidence-backed child L2 labels or say review_only.",
        "constraints": [
            "Use only the provided source_l2_id, semantic terms, and timeline_sample evidence.",
            "Every split proposal must cite representative_l1_ids from the provided timeline_sample or representative_l1_ids.",
            "Every child must include assignment_criteria and representative_l1_ids that distinguish it from sibling children.",
            "For large sources, propose enough child candidates to avoid leaving one dominant residual bucket; if the evidence does not support separable coverage, use review_only.",
            "Do not split a source if most evidence would still belong to one child and the other children would be tiny edge cases.",
            "Do not invent project-specific taxonomy that is not supported by the evidence.",
            "Prefer review_only when the source L2 is a single repeated concept that cannot be split coherently.",
            "Return JSON only.",
        ],
        "profile": {
            "domain": profile.get("domain", ""),
            "topic_key_language": profile.get("topic_key_language", ""),
        },
        "sources": sources,
        "response_schema": {
            "split_candidates": [
                {
                    "source_l2_id": "existing id",
                    "child_candidates": [
                        {
                            "label": "short evidence-backed noun phrase",
                            "assignment_criteria": ["terms or evidence cues that assign L1 to this child"],
                            "representative_l1_ids": ["obj ids from this source L2 that clearly belong to this child"],
                        }
                    ],
                    "confidence": 0.0,
                    "rationale": "why these children are coherent and separable",
                }
            ],
            "review_only": [
                {
                    "source_l2_id": "existing id",
                    "reason": "why no reliable split should be materialized",
                    "representative_l1_ids": ["obj ids from this source L2"],
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalized_child_candidates(row: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
    children = row.get("child_candidates", []) or []
    normalized: list[dict[str, Any]] = []
    if children:
        for child in children:
            if not isinstance(child, dict):
                continue
            label = str(child.get("label", "") or "").strip().lower()
            if not label:
                continue
            reps = [
                str(value)
                for value in child.get("representative_l1_ids", []) or []
                if str(value) in allowed
            ]
            normalized.append(
                {
                    "label": label,
                    "assignment_criteria": [
                        str(value).strip().lower()
                        for value in child.get("assignment_criteria", []) or []
                        if str(value).strip()
                    ],
                    "representative_l1_ids": reps,
                }
            )
        return normalized
    for label in row.get("proposed_child_labels", []) or []:
        clean = str(label).strip().lower()
        if clean:
            normalized.append({"label": clean, "assignment_criteria": [clean], "representative_l1_ids": []})
    return normalized


def _validate_split_review(parsed: dict[str, Any], sources: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    by_id = {str(source.get("source_l2_id", "")): source for source in sources}
    allowed_ids = {
        source_id: {
            str(value)
            for value in (source.get("representative_l1_ids", []) or [])
            + [row.get("obj_id", "") for row in source.get("timeline_sample", []) or []]
            if str(value)
        }
        for source_id, source in by_id.items()
    }
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    review_only: list[dict[str, Any]] = []
    for row in parsed.get("split_candidates", []) or []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source_l2_id", "") or "")
        children = _normalized_child_candidates(row, allowed_ids.get(source, set()))
        labels = [child["label"] for child in children]
        reps = sorted(
            {
                str(value)
                for value in row.get("representative_l1_ids", []) or []
                if str(value) in allowed_ids.get(source, set())
            }
            | {
                rep
                for child in children
                for rep in child.get("representative_l1_ids", []) or []
            }
        )
        label_rejections = [_label_rejection(label, profile=profile) for label in labels]
        if source not in by_id:
            rejected.append({"proposal": row, "reason": "unknown_source_l2_id"})
        elif len(labels) < 2:
            rejected.append({"proposal": row, "reason": "insufficient_child_labels"})
        elif any(label_rejections):
            rejected.append({"proposal": row, "reason": "generic_or_type_like_label"})
        elif _safe_float(row.get("confidence")) < 0.5:
            rejected.append({"proposal": row, "reason": "low_confidence"})
        elif not reps:
            rejected.append({"proposal": row, "reason": "missing_valid_representative_l1_ids"})
        elif row.get("child_candidates") and any(not child.get("representative_l1_ids") for child in children):
            rejected.append({"proposal": row, "reason": "missing_valid_child_representative_l1_ids"})
        else:
            accepted.append(
                {
                    **row,
                    "proposed_child_labels": labels,
                    "child_candidates": children,
                    "representative_l1_ids": reps,
                }
            )
    for row in parsed.get("review_only", []) or []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source_l2_id", "") or "")
        reps = [str(value) for value in row.get("representative_l1_ids", []) or [] if str(value) in allowed_ids.get(source, set())]
        if source in by_id:
            review_only.append({**row, "representative_l1_ids": reps})
        else:
            rejected.append({"proposal": row, "reason": "unknown_review_only_source_l2_id"})
    return {"accepted_split_candidates": accepted, "review_only": review_only, "rejected": rejected}


def propose_focused_split_review(
    *,
    run_root: Path | str,
    profile: dict[str, Any],
    model: str = "",
    client: Any | None = None,
    source_l2_ids: list[str] | None = None,
    sample_limit: int = 12,
) -> dict[str, Any]:
    root = ensure_optimization_output(run_root)
    l2_view = load_json(root / "l2" / "l2_view.json")
    split_ids = set(source_l2_ids or []) or _split_review_source_ids(root)
    l2_by_id = {str(node.get("l2_id", "")): node for node in l2_view.get("l2_nodes", []) or []}
    sources = [
        _compact_split_source(l2_by_id[source_id], sample_limit=sample_limit)
        for source_id in sorted(split_ids)
        if source_id in l2_by_id
    ]
    selected_model = model or os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.5-pro"
    api_dir = root / "api_calls"
    api_dir.mkdir(parents=True, exist_ok=True)
    if not sources:
        report = {
            "schema_version": 1,
            "generated_at_utc": utc_now_iso(),
            "status": "no_split_review_sources",
            "model": selected_model,
            "source_l2_count": 0,
            "accepted_split_count": 0,
            "review_only_count": 0,
            "rejected_count": 0,
            "accepted_split_candidates": [],
            "review_only": [],
            "rejected": [],
        }
        write_json(root / "l2" / "llm_split_review_proposals.json", report)
        write_text(root / "l2" / "llm_split_review_proposals.md", _format_report_md(report))
        return report

    if client is None:
        from share_mem.l1.gemini_clients import create_gemini_client

        client = create_gemini_client()
    prompt = _build_prompt(sources, profile)
    start = time.perf_counter()
    raw_text = ""
    parsed: dict[str, Any] = {}
    usage_metadata: dict[str, Any] = {}
    error = ""
    try:
        response = client.models.generate_content(
            model=selected_model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        raw_text = _response_text(response)
        usage_metadata = _usage_metadata(response)
        parsed = _extract_json(raw_text)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        parsed = {}
    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    validation = _validate_split_review(parsed, sources, profile)
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": "llm_split_review_written" if not error else "llm_split_review_failed",
        "model": selected_model,
        "source_l2_count": len(sources),
        "latency_ms": latency_ms,
        "accepted_split_count": len(validation["accepted_split_candidates"]),
        "review_only_count": len(validation["review_only"]),
        "rejected_count": len(validation["rejected"]),
        "source_l2_ids": [source["source_l2_id"] for source in sources],
        **validation,
        "usage_metadata": usage_metadata,
        "error": error,
    }
    write_json(root / "l2" / "llm_split_review_proposals.json", report)
    write_text(root / "l2" / "llm_split_review_proposals.md", _format_report_md(report))
    write_json(
        api_dir / "0002_l2_focused_split_review.json",
        {
            "schema_version": 1,
            "created_at_utc": utc_now_iso(),
            "stage": "l2_focused_split_review",
            "model": selected_model,
            "prompt": prompt,
            "raw_response": raw_text,
            "parsed_json": parsed,
            "latency_ms": latency_ms,
            "usage_metadata": usage_metadata,
            "error": error,
        },
    )
    return report


def _format_report_md(report: dict[str, Any]) -> str:
    lines = [
        "# LLM Focused Split Review",
        "",
        f"- status: `{report.get('status')}`",
        f"- model: `{report.get('model')}`",
        f"- source L2 reviewed: {report.get('source_l2_count')}",
        f"- accepted split candidates: {report.get('accepted_split_count')}",
        f"- review-only recommendations: {report.get('review_only_count')}",
        f"- rejected proposals: {report.get('rejected_count')}",
        "",
        "## Accepted Split Candidates",
    ]
    for row in report.get("accepted_split_candidates", []) or []:
        lines.extend(
            [
                "",
                f"### {row.get('source_l2_id')}",
                f"- labels: {', '.join(row.get('proposed_child_labels', []) or [])}",
                f"- confidence: {row.get('confidence')}",
                f"- representative L1: {', '.join(row.get('representative_l1_ids', []) or [])}",
                f"- rationale: {row.get('rationale')}",
            ]
        )
    lines.extend(["", "## Review Only"])
    for row in report.get("review_only", []) or []:
        lines.extend(
            [
                "",
                f"### {row.get('source_l2_id')}",
                f"- representative L1: {', '.join(row.get('representative_l1_ids', []) or [])}",
                f"- reason: {row.get('reason')}",
            ]
        )
    if report.get("rejected"):
        lines.extend(["", "## Rejected"])
        for row in report.get("rejected", []) or []:
            lines.append(f"- {row.get('reason')}: {row.get('proposal')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create focused LLM split-review sidecar proposals for needs_split_review L2 topics.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--source-l2-id", action="append", default=[])
    parser.add_argument("--sample-limit", type=int, default=12)
    args = parser.parse_args()
    report = propose_focused_split_review(
        run_root=args.run_root,
        profile=load_profile(args.profile),
        model=args.model,
        source_l2_ids=args.source_l2_id,
        sample_limit=args.sample_limit,
    )
    print(
        "[optimization:v2] focused split review complete: "
        f"status={report['status']} sources={report['source_l2_count']} "
        f"splits={report['accepted_split_count']} review_only={report['review_only_count']} rejected={report['rejected_count']}"
    )


if __name__ == "__main__":
    main()
