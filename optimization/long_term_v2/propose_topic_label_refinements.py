from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.text_utils import ngrams, slugify, tokens


GENERIC_LABEL_WORDS = {
    "label",
    "review",
    "representative",
    "evidence",
    "clearly",
    "concerns",
    "mostly",
    "about",
    "topic",
    "current",
    "source",
    "reviewer",
    "audience",
    "category",
    "design",
    "set",
    "the",
    "and",
    "may",
    "not",
    "valid",
    "but",
    "for",
    "retrieval",
    "clarified",
    "treated",
    "wrong",
}
TYPE_LIKE_LABELS = {
    "decision",
    "proposal",
    "argument",
    "finding",
    "open issue",
    "action item",
    "method change",
}


def _clean_reason_phrase(text: str, *, banned_tokens: set[str]) -> str:
    return " ".join(tokens((text or "").replace("/", " "), stopwords=GENERIC_LABEL_WORDS | banned_tokens))


def _reason_head_phrases(reason: str, *, banned_tokens: set[str]) -> list[str]:
    phrases: list[str] = []
    patterns = [
        r"mostly about (?P<phrase>[^,.]+)",
        r"about (?P<phrase>[^,.]+)",
        r"concerns (?P<phrase>[^,.]+?)(?: as | and |\.|,|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, reason or "", flags=re.IGNORECASE)
        if not match:
            continue
        raw = re.split(r"\band\b", match.group("phrase"), maxsplit=1, flags=re.IGNORECASE)[0]
        clean = _clean_reason_phrase(raw, banned_tokens=banned_tokens)
        if len(clean.split()) >= 2:
            phrases.append(clean)
    return phrases


def _negated_label_tokens(reason: str, current_label: str) -> set[str]:
    reason_lower = reason.lower()
    output: set[str] = set()
    for token in tokens(current_label):
        if f"not {token}" in reason_lower or f"misleading" in reason_lower:
            output.add(token)
    return output


def _decision_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in review.get("decisions", []) or []
        if isinstance(row, dict)
        and row.get("item_type") == "active_l2"
        and row.get("decision") == "needs_label_review"
    ]


def _event_text(node: dict[str, Any]) -> str:
    parts: list[str] = []
    for event in node.get("timeline_digest", []) or []:
        if isinstance(event, dict):
            parts.append(str(event.get("summary", "") or ""))
            parts.append(str(event.get("content", "") or ""))
    for row in node.get("top_semantic_terms", []) or []:
        if isinstance(row, dict):
            term = str(row.get("term", "") or "")
            count = int(row.get("object_count", 1) or 1)
            parts.extend([term] * min(count, 4))
    return " ".join(parts)


def _rank_phrases(text: str, *, current_tokens: set[str], banned_tokens: set[str], multiplier: int) -> Counter[str]:
    token_list = tokens(text, stopwords=GENERIC_LABEL_WORDS | banned_tokens)
    counts: Counter[str] = Counter()
    for gram in ngrams(token_list, min_n=2, max_n=4, generic_terms=GENERIC_LABEL_WORDS | banned_tokens):
        gram_tokens = set(gram.split())
        if not gram_tokens:
            continue
        if gram_tokens == current_tokens:
            continue
        if gram in TYPE_LIKE_LABELS:
            continue
        if current_tokens and gram_tokens.issubset(current_tokens):
            continue
        counts[gram] += multiplier * (1 + len(gram.split()))
    return counts


def _candidate_phrases(*, decision: dict[str, Any], node: dict[str, Any]) -> list[str]:
    current_tokens = set(tokens(str(node.get("label", "") or ""), stopwords=GENERIC_LABEL_WORDS))
    banned_tokens = _negated_label_tokens(str(decision.get("reason", "") or ""), str(node.get("label", "") or ""))
    counts: Counter[str] = Counter()
    for phrase in _reason_head_phrases(str(decision.get("reason", "") or ""), banned_tokens=banned_tokens):
        counts[phrase] += 100
    counts.update(
        _rank_phrases(
            str(decision.get("reason", "") or ""),
            current_tokens=current_tokens,
            banned_tokens=banned_tokens,
            multiplier=8,
        )
    )
    counts.update(
        _rank_phrases(
            _event_text(node),
            current_tokens=current_tokens,
            banned_tokens=banned_tokens,
            multiplier=1,
        )
    )
    for row in node.get("top_semantic_terms", []) or []:
        if not isinstance(row, dict):
            continue
        term = " ".join(tokens(str(row.get("term", "") or ""), stopwords=GENERIC_LABEL_WORDS | banned_tokens))
        if len(term.split()) >= 2 and term not in TYPE_LIKE_LABELS and term != str(node.get("label", "")).lower():
            counts[term] += int(row.get("object_count", 1) or 1)
    return [
        phrase
        for phrase, _ in sorted(counts.items(), key=lambda item: (-item[1], -len(item[0].split()), item[0]))
        if set(phrase.split()) != current_tokens
    ]


def _representative_l1_ids(node: dict[str, Any]) -> list[str]:
    ids = [str(value) for value in node.get("representative_l1_ids", []) or [] if str(value)]
    if ids:
        return ids[:8]
    return [
        str(event.get("obj_id", "") or "")
        for event in node.get("timeline_digest", []) or []
        if isinstance(event, dict) and str(event.get("obj_id", "") or "")
    ][:8]


def propose_label_refinements(*, review: dict[str, Any], l2_nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    proposals: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for decision in _decision_rows(review):
        source_l2_id = str(decision.get("item_id", "") or "")
        node = l2_nodes.get(source_l2_id)
        if not node:
            rejected.append({"source_l2_id": source_l2_id, "reason": "source_l2_not_found"})
            continue
        reps = _representative_l1_ids(node)
        phrases = _candidate_phrases(decision=decision, node=node)
        proposed_label = phrases[0] if phrases else str(node.get("label", "") or "")
        if not reps or not proposed_label or proposed_label == str(node.get("label", "") or "").lower():
            rejected.append({"source_l2_id": source_l2_id, "reason": "insufficient_evidence_for_relabel"})
            continue
        proposals.append(
            {
                "proposal_id": f"LR-{len(proposals) + 1:04d}",
                "source_l2_id": source_l2_id,
                "current_label": str(node.get("label", "") or ""),
                "proposed_label": proposed_label,
                "proposed_l2_id": f"L2-{slugify(proposed_label)}",
                "representative_l1_ids": reps,
                "evidence_phrases": phrases[:8],
                "review_reason": str(decision.get("reason", "") or ""),
                "validation_status": "candidate_review_required",
                "application_policy": "sidecar_review_required",
            }
        )
    return {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "proposal_count": len(proposals),
        "rejected_count": len(rejected),
        "proposals": proposals,
        "rejected": rejected,
    }


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# Topic Label Refinement Candidates",
        "",
        f"- proposal count: `{report['proposal_count']}`",
        f"- rejected count: `{report['rejected_count']}`",
        "",
    ]
    for proposal in report["proposals"]:
        lines.append(f"## `{proposal['source_l2_id']}`")
        lines.append(f"- current label: `{proposal['current_label']}`")
        lines.append(f"- proposed label: `{proposal['proposed_label']}`")
        lines.append(f"- representative L1: {', '.join(proposal['representative_l1_ids'])}")
        lines.append(f"- reason: {proposal['review_reason']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose sidecar-only L2 label refinements from active L2 review decisions.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.run_root)
    l2_view = load_json(root / "l2" / "l2_view.json")
    l2_nodes = {str(node.get("l2_id", "") or ""): node for node in l2_view.get("l2_nodes", []) or [] if isinstance(node, dict)}
    report = propose_label_refinements(review=load_json(args.review), l2_nodes=l2_nodes)
    out_dir = Path(args.out)
    write_json(out_dir / "label_refinement_candidates.json", report)
    write_text(out_dir / "label_refinement_candidates.md", _format_md(report))
    print(f"[optimization:v2] label refinement candidates written: proposals={report['proposal_count']} rejected={report['rejected_count']}")


if __name__ == "__main__":
    main()
