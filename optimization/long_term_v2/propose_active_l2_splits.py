from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import load_profile, profile_stopwords, profile_weak_child_terms
from optimization.long_term_v2.text_utils import jaccard, ngrams, slugify, tokens


BASE_STOPWORDS = {
    "about",
    "across",
    "another",
    "before",
    "between",
    "could",
    "current",
    "discuss",
    "evidence",
    "meeting",
    "should",
    "source",
    "team",
    "that",
    "their",
    "there",
    "these",
    "thing",
    "this",
    "topic",
    "using",
    "with",
    "would",
}
WEAK_TOPIC_WORDS = {
    "enable",
    "good",
    "look",
    "order",
    "pretty",
    "purchase",
    "second",
}


def _target_ids_from_review(review: dict[str, Any]) -> list[str]:
    return [
        str(row.get("item_id", "") or "")
        for row in review.get("decisions", []) or []
        if isinstance(row, dict)
        and row.get("item_type") == "active_l2"
        and row.get("decision") == "needs_l3_split"
        and str(row.get("item_id", "") or "")
    ]


def _node_events(node: dict[str, Any]) -> list[dict[str, Any]]:
    events = [event for event in node.get("timeline_digest", []) or [] if isinstance(event, dict)]
    if events:
        return events
    return [
        {"obj_id": obj_id, "summary": ""}
        for obj_id in node.get("linked_obj_ids", []) or []
        if str(obj_id)
    ]


def _usable_phrase(phrase: str, *, parent_tokens: set[str], stopwords: set[str]) -> bool:
    parts = phrase.split()
    if len(parts) < 2:
        return False
    term_set = set(parts)
    if term_set.issubset(parent_tokens):
        return False
    if term_set.issubset(stopwords):
        return False
    if any(part in {"know", "well", "people", "thing", "stuff", "gonna"} for part in parts):
        return False
    return True


def _candidate_labels(node: dict[str, Any], *, profile: dict[str, Any] | None = None, limit: int = 6) -> list[str]:
    profile = profile or {}
    stopwords = BASE_STOPWORDS | WEAK_TOPIC_WORDS | profile_stopwords(profile) | profile_weak_child_terms(profile)
    parent_tokens = set(tokens(str(node.get("label", "") or ""), stopwords=stopwords))
    counts: Counter[str] = Counter()
    for row in node.get("top_semantic_terms", []) or []:
        if not isinstance(row, dict):
            continue
        phrase = " ".join(tokens(str(row.get("term", "") or ""), stopwords=stopwords))
        if _usable_phrase(phrase, parent_tokens=parent_tokens, stopwords=stopwords):
            counts[phrase] += int(row.get("object_count", 1) or 1) * 5
    for event in _node_events(node):
        event_tokens = tokens(str(event.get("summary", "") or ""), stopwords=stopwords)
        for gram in ngrams(event_tokens, min_n=2, max_n=3, generic_terms=stopwords):
            if _usable_phrase(gram, parent_tokens=parent_tokens, stopwords=stopwords):
                counts[gram] += 1
    labels: list[str] = []
    for phrase, _ in sorted(counts.items(), key=lambda item: (-item[1], -len(item[0].split()), item[0])):
        phrase_tokens = set(phrase.split())
        if any(jaccard(phrase_tokens, set(label.split())) >= 0.65 for label in labels):
            continue
        labels.append(phrase)
        if len(labels) >= limit:
            break
    return labels


def _assign_events(events: list[dict[str, Any]], labels: list[str]) -> list[dict[str, Any]]:
    label_tokens = [set(tokens(label)) for label in labels]
    groups: list[list[dict[str, Any]]] = [[] for _ in labels]
    for index, event in enumerate(events):
        event_tokens = set(tokens(str(event.get("summary", "") or "")))
        scores = [(len(event_tokens & terms), label_index) for label_index, terms in enumerate(label_tokens)]
        score, label_index = max(scores, key=lambda item: (item[0], -item[1]))
        if score <= 0:
            label_index = index % len(labels)
        groups[label_index].append(event)
    children: list[dict[str, Any]] = []
    for label, rows in zip(labels, groups):
        representative = [str(row.get("obj_id", "") or "") for row in rows[:8] if str(row.get("obj_id", "") or "")]
        children.append(
            {
                "label": label,
                "assignment_criteria": [label],
                "representative_l1_ids": representative,
                "assigned_l1_count": len(rows),
            }
        )
    return children


def _can_materialize(children: list[dict[str, Any]], event_count: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    non_empty = [child for child in children if child["assigned_l1_count"] > 0]
    if len(non_empty) < 2:
        reasons.append("insufficient_non_empty_children")
    if any(child["assigned_l1_count"] == 0 for child in children):
        reasons.append("empty_candidate_child")
    if any(0 < child["assigned_l1_count"] < 3 for child in children):
        reasons.append("tiny_candidate_child")
    if children and max(child["assigned_l1_count"] for child in children) / max(event_count, 1) >= 0.82:
        reasons.append("dominant_residual_child")
    if any(set(tokens(str(child.get("label", "")))) & WEAK_TOPIC_WORDS for child in children):
        reasons.append("weak_candidate_child_label")
    return not reasons, reasons


def propose_active_l2_splits(
    l2_nodes: dict[str, dict[str, Any]],
    *,
    target_l2_ids: list[str],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    split_candidates: list[dict[str, Any]] = []
    review_only: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for source_l2_id in target_l2_ids:
        node = l2_nodes.get(source_l2_id)
        if not node:
            rejected.append({"source_l2_id": source_l2_id, "reason": "source_l2_not_found"})
            continue
        events = _node_events(node)
        labels = _candidate_labels(node, profile=profile)
        if len(labels) < 2:
            review_only.append(
                {
                    "source_l2_id": source_l2_id,
                    "review_disposition": "needs_manual_review",
                    "reason": "Not enough evidence-backed child labels were separable without hardcoded taxonomy.",
                    "representative_l1_ids": [str(event.get("obj_id", "") or "") for event in events[:8] if str(event.get("obj_id", "") or "")],
                }
            )
            continue
        children = _assign_events(events, labels)
        can_materialize, reasons = _can_materialize(children, len(events))
        if not can_materialize:
            review_only.append(
                {
                    "source_l2_id": source_l2_id,
                    "review_disposition": "needs_manual_review",
                    "reason": "Candidate child topics require human review before materialization.",
                    "reason_codes": reasons,
                    "candidate_child_preview": children,
                    "representative_l1_ids": [str(event.get("obj_id", "") or "") for event in events[:8] if str(event.get("obj_id", "") or "")],
                }
            )
            continue
        split_candidates.append(
            {
                "source_l2_id": source_l2_id,
                "source_label": str(node.get("label", "") or ""),
                "child_candidates": children,
                "confidence": 0.62,
                "rationale": "Generic lexical/semantic-term clustering found multiple evidence-backed child candidates.",
                "validation_status": "candidate_review_required",
                "application_policy": "sidecar_review_required",
            }
        )
    return {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "source_l2_count": len(target_l2_ids),
        "split_candidate_count": len(split_candidates),
        "review_only_count": len(review_only),
        "rejected_count": len(rejected),
        "split_candidates": split_candidates,
        "review_only": review_only,
        "rejected": rejected,
    }


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# Active L2 Split Candidates",
        "",
        f"- split candidates: `{report['split_candidate_count']}`",
        f"- review-only: `{report['review_only_count']}`",
        f"- rejected: `{report['rejected_count']}`",
        "",
    ]
    for candidate in report["split_candidates"]:
        lines.append(f"## `{candidate['source_l2_id']}` {candidate['source_label']}")
        for child in candidate["child_candidates"]:
            lines.append(f"- `{child['label']}`: {child['assigned_l1_count']} L1")
        lines.append("")
    if report["review_only"]:
        lines.append("## Review Only")
        for row in report["review_only"]:
            lines.append(f"- `{row['source_l2_id']}`: {row['reason']}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose sidecar-only focused split candidates for active L2 review warnings.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--profile", default="")
    args = parser.parse_args()
    root = Path(args.run_root)
    l2_view = load_json(root / "l2" / "l2_view.json")
    l2_nodes = {str(node.get("l2_id", "") or ""): node for node in l2_view.get("l2_nodes", []) or [] if isinstance(node, dict)}
    review = load_json(args.review)
    profile = load_profile(args.profile) if args.profile else {}
    report = propose_active_l2_splits(l2_nodes, target_l2_ids=_target_ids_from_review(review), profile=profile)
    out_dir = Path(args.out)
    write_json(out_dir / "active_l2_split_candidates.json", report)
    write_text(out_dir / "active_l2_split_candidates.md", _format_md(report))
    print(
        "[optimization:v2] active L2 split candidates written: "
        f"splits={report['split_candidate_count']} review_only={report['review_only_count']} rejected={report['rejected_count']}"
    )


if __name__ == "__main__":
    main()
