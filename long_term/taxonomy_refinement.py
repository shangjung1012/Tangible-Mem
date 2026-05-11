"""Reporting-only helpers for side-by-side L2/L3 taxonomy refinement."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from share_mem.store import build_l1_index, load_share_tree

TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
SLUG_RE = re.compile(r"[^a-z0-9]+", re.IGNORECASE)

STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "and",
    "are",
    "as",
    "at",
    "alone",
    "appears",
    "artifact",
    "artifacts",
    "be",
    "become",
    "before",
    "by",
    "can",
    "child",
    "children",
    "context",
    "could",
    "for",
    "from",
    "has",
    "have",
    "how",
    "in",
    "into",
    "is",
    "it",
    "l1",
    "l2",
    "l3",
    "label",
    "labels",
    "memory",
    "meeting",
    "needs",
    "new",
    "notes",
    "not",
    "of",
    "on",
    "or",
    "over",
    "rather",
    "should",
    "said",
    "several",
    "system",
    "team",
    "that",
    "than",
    "the",
    "this",
    "to",
    "topic",
    "use",
    "was",
    "were",
    "when",
    "with",
    "word",
    "words",
}

GENERIC_SPLIT_TERMS = {
    "agent",
    "baseline",
    "calling",
    "comparison",
    "cost",
    "demo",
    "editor",
    "evidence",
    "experiment",
    "experiments",
    "grouping",
    "importance",
    "latency",
    "line",
    "llm",
    "object",
    "objects",
    "promotion",
    "prompt",
    "query",
    "rag",
    "retrieval",
    "summary",
    "timeline",
    "validation",
}

DOMAIN_SINGLETON_TERMS = {
    "bmr",
    "locomo",
    "memo",
    "mem0",
    "whisperx",
}

BAD_SPLIT_PHRASES = {
    "180 llm",
    "long term",
    "rather than",
    "term integration",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _slug(text: str) -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")
    return slug or "topic"


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(text or "")
        if len(token) >= 3 and token.lower() not in STOPWORDS
    ]


def _term_rejection_reason(term: str) -> str:
    normalized = " ".join(_tokens(term))
    if not normalized:
        return "empty_or_stopword_only"
    tokens = normalized.split()
    if normalized in BAD_SPLIT_PHRASES:
        return "bad_phrase"
    if any(token.isdigit() for token in tokens):
        return "numeric_fragment"
    if len(tokens) == 1:
        token = tokens[0]
        if token in DOMAIN_SINGLETON_TERMS:
            return ""
        return "generic_single_token"
    if all(token in GENERIC_SPLIT_TERMS for token in tokens):
        return "all_generic_tokens"
    return ""


def _entry_text(entry: dict[str, Any]) -> str:
    return " ".join(
        str(entry.get(key, "") or "")
        for key in ("summary", "content", "evidence")
    )


def _obj_snapshot(obj_id: str, l1_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    obj = l1_index.get(obj_id, {})
    importance = 0.0
    try:
        importance = float(obj.get("importance", 0.0) or 0.0)
    except (TypeError, ValueError):
        importance = 0.0
    return {
        "obj_id": obj_id,
        "meeting_id": str(obj.get("meeting_id", "") or ""),
        "meeting_date": str(obj.get("meeting_date", "") or ""),
        "type": str(obj.get("type", "") or ""),
        "importance": round(importance, 3),
        "content": str(obj.get("content", "") or "")[:240],
        "topics": list(obj.get("topics", []) or []),
    }


def _index_assignment(row: dict[str, Any]) -> dict[str, str]:
    return {
        "l2_id": str(row.get("l2_id", "") or ""),
        "l2_label": str(row.get("l2_label", "") or ""),
    }


def compare_l2_assignment_runs(
    *,
    baseline_l2_root: Path | str,
    candidate_l2_root: Path | str,
    share_mem_root: Path | str | None = None,
    high_importance_threshold: float = 0.70,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Compare two generated L2 runs without mutating either run."""
    baseline_root = Path(baseline_l2_root)
    candidate_root = Path(candidate_l2_root)
    baseline_index = _load_json(baseline_root / "l2_index.json")
    candidate_index = _load_json(candidate_root / "l2_index.json")
    baseline_index = baseline_index if isinstance(baseline_index, dict) else {}
    candidate_index = candidate_index if isinstance(candidate_index, dict) else {}
    if share_mem_root is not None:
        l1_index = build_l1_index(load_share_tree(share_mem_root))
    else:
        l1_index = {}

    baseline_ids = set(baseline_index)
    candidate_ids = set(candidate_index)
    shared_ids = baseline_ids & candidate_ids
    changed: list[dict[str, Any]] = []
    for obj_id in sorted(shared_ids):
        old_assignment = _index_assignment(baseline_index[obj_id])
        new_assignment = _index_assignment(candidate_index[obj_id])
        if old_assignment != new_assignment:
            snapshot = _obj_snapshot(obj_id, l1_index)
            changed.append(
                {
                    "obj_id": obj_id,
                    "old_assignment": old_assignment,
                    "new_assignment": new_assignment,
                    "l1": snapshot,
                }
            )

    lost = [
        {
            "obj_id": obj_id,
            "old_assignment": _index_assignment(baseline_index[obj_id]),
            "l1": _obj_snapshot(obj_id, l1_index),
        }
        for obj_id in sorted(baseline_ids - candidate_ids)
    ]
    gained = [
        {
            "obj_id": obj_id,
            "new_assignment": _index_assignment(candidate_index[obj_id]),
            "l1": _obj_snapshot(obj_id, l1_index),
        }
        for obj_id in sorted(candidate_ids - baseline_ids)
    ]

    manual_review_queue: list[dict[str, Any]] = []
    for item in changed:
        importance = float(item.get("l1", {}).get("importance", 0.0) or 0.0)
        reason = (
            "high_importance_changed_assignment"
            if importance >= high_importance_threshold
            else "changed_assignment"
        )
        manual_review_queue.append({"reason_code": reason, **item})
    for item in lost:
        manual_review_queue.append({"reason_code": "lost_assignment", **item})

    old_labels = Counter(
        str(row.get("l2_label", "") or "")
        for row in baseline_index.values()
        if isinstance(row, dict)
    )
    new_labels = Counter(
        str(row.get("l2_label", "") or "")
        for row in candidate_index.values()
        if isinstance(row, dict)
    )

    return {
        "schema_version": 1,
        "generated_at_utc": generated_at_utc or _utc_now_iso(),
        "baseline_l2_root": str(baseline_root.resolve()),
        "candidate_l2_root": str(candidate_root.resolve()),
        "share_mem_root": str(Path(share_mem_root).resolve()) if share_mem_root else "",
        "baseline_linked_count": len(baseline_index),
        "candidate_linked_count": len(candidate_index),
        "shared_assignment_count": len(shared_ids),
        "changed_assignment_count": len(changed),
        "lost_assignment_count": len(lost),
        "gained_assignment_count": len(gained),
        "manual_review_count": len(manual_review_queue),
        "changed_assignments": changed,
        "lost_assignments": lost,
        "gained_assignments": gained,
        "manual_review_queue": manual_review_queue,
        "baseline_type_distribution": dict(sorted(old_labels.items())),
        "candidate_type_distribution": dict(sorted(new_labels.items())),
    }


def build_gold_topic_mapping_report(
    *,
    share_mem_root: Path | str,
    l2_root: Path | str,
    l3_root: Path | str,
    gold_path: Path | str,
    out: Path | str | None = None,
    purity_threshold: float = 0.80,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Compare synthetic gold topic labels against generated L2/L3 assignment sidecars.

    This is a validation/reporting helper only. It does not mutate raw L1, L2, or
    L3 artifacts; it only writes a side-by-side review report when `out` is set.
    """
    share_root = Path(share_mem_root)
    l2_root_path = Path(l2_root)
    l3_root_path = Path(l3_root)
    gold_file = Path(gold_path)
    gold_mapping = _load_json(gold_file)
    if not isinstance(gold_mapping, dict):
        raise RuntimeError(f"Gold mapping must be an obj_id -> topic JSON object: {gold_file}")
    l2_index = _load_json(l2_root_path / "l2_index.json")
    if not isinstance(l2_index, dict):
        l2_index = {}
    l3_index_path = l3_root_path / "l3_index.json"
    l3_index = _load_json(l3_index_path) if l3_index_path.exists() else {}
    if not isinstance(l3_index, dict):
        l3_index = {}
    l1_index = build_l1_index(load_share_tree(share_root))

    topic_to_obj_ids: dict[str, list[str]] = defaultdict(list)
    for obj_id, topic in gold_mapping.items():
        topic_to_obj_ids[str(topic or "unlabeled")].append(str(obj_id))

    topic_rows: list[dict[str, Any]] = []
    unlinked_gold_obj_ids: list[str] = []
    missing_gold_obj_ids: list[str] = []
    for topic, obj_ids in sorted(topic_to_obj_ids.items()):
        l2_counts: Counter[tuple[str, str]] = Counter()
        child_counts: Counter[tuple[str, str, str]] = Counter()
        linked_obj_ids: list[str] = []
        topic_unlinked: list[str] = []
        topic_missing: list[str] = []
        examples: list[dict[str, Any]] = []
        for obj_id in sorted(obj_ids):
            if obj_id not in l1_index:
                topic_missing.append(obj_id)
                missing_gold_obj_ids.append(obj_id)
            l2_row = l2_index.get(obj_id)
            if isinstance(l2_row, dict):
                linked_obj_ids.append(obj_id)
                l2_counts[
                    (
                        str(l2_row.get("l2_id", "") or ""),
                        str(l2_row.get("l2_label", "") or ""),
                    )
                ] += 1
            else:
                topic_unlinked.append(obj_id)
                unlinked_gold_obj_ids.append(obj_id)
            l3_row = l3_index.get(obj_id)
            if isinstance(l3_row, dict):
                child_counts[
                    (
                        str(l3_row.get("l3_id", "") or ""),
                        str(l3_row.get("child_l2_id", "") or ""),
                        str(l3_row.get("child_l2_label", "") or ""),
                    )
                ] += 1
            if len(examples) < 3:
                examples.append(_obj_snapshot(obj_id, l1_index))

        primary_l2 = l2_counts.most_common(1)[0] if l2_counts else (("", ""), 0)
        primary_l2_key, primary_l2_count = primary_l2
        linked_count = len(linked_obj_ids)
        purity = round(primary_l2_count / linked_count, 4) if linked_count else 0.0
        fully_linked = not topic_unlinked and not topic_missing
        topic_rows.append(
            {
                "gold_topic": topic,
                "gold_obj_count": len(obj_ids),
                "linked_obj_count": linked_count,
                "unlinked_obj_count": len(topic_unlinked),
                "missing_obj_count": len(topic_missing),
                "fully_linked": fully_linked,
                "primary_l2_id": primary_l2_key[0],
                "primary_l2_label": primary_l2_key[1],
                "primary_l2_count": primary_l2_count,
                "primary_l2_purity": purity,
                "low_purity": bool(linked_count and purity < purity_threshold),
                "l2_distribution": [
                    {"l2_id": key[0], "l2_label": key[1], "count": count}
                    for key, count in l2_counts.most_common()
                ],
                "child_l2_distribution": [
                    {
                        "l3_id": key[0],
                        "child_l2_id": key[1],
                        "child_l2_label": key[2],
                        "count": count,
                    }
                    for key, count in child_counts.most_common()
                ],
                "unlinked_obj_ids": topic_unlinked[:50],
                "missing_obj_ids": topic_missing[:50],
                "examples": examples,
            }
        )

    fully_linked_count = sum(1 for row in topic_rows if row["fully_linked"])
    low_purity_count = sum(1 for row in topic_rows if row["low_purity"])
    report = {
        "schema_version": 1,
        "generated_at_utc": generated_at_utc or _utc_now_iso(),
        "source": "long_term_gold_topic_mapping_validation",
        "share_mem_root": str(share_root.resolve()),
        "l2_root": str(l2_root_path.resolve()),
        "l3_root": str(l3_root_path.resolve()),
        "gold_path": str(gold_file.resolve()),
        "purity_threshold": purity_threshold,
        "gold_topic_count": len(topic_rows),
        "gold_obj_count": len(gold_mapping),
        "linked_gold_obj_count": len(gold_mapping) - len(unlinked_gold_obj_ids),
        "unlinked_gold_obj_count": len(unlinked_gold_obj_ids),
        "missing_gold_obj_count": len(missing_gold_obj_ids),
        "fully_linked_topic_count": fully_linked_count,
        "low_purity_topic_count": low_purity_count,
        "topic_rows": topic_rows,
        "manual_review_queue": [
            row
            for row in topic_rows
            if row["unlinked_obj_count"] or row["missing_obj_count"] or row["low_purity"]
        ],
        "notes": [
            "Gold topics are expected-topic validation labels, not canonical L2 labels.",
            "Low purity can be acceptable for intentionally cross-cutting topics, but should be reviewed.",
        ],
    }

    if out is not None:
        write_gold_topic_mapping_report(report, out)
    return report


def write_gold_topic_mapping_report(report: dict[str, Any], out: Path | str) -> None:
    out_root = Path(out)
    _write_json(out_root / "gold_topic_to_l2_l3_mapping.json", report)
    lines = [
        "# Gold Topic to L2/L3 Mapping",
        "",
        f"- Gold topics: {report.get('gold_topic_count', 0)}",
        f"- Gold objects: {report.get('gold_obj_count', 0)}",
        f"- Linked gold objects: {report.get('linked_gold_obj_count', 0)}",
        f"- Unlinked gold objects: {report.get('unlinked_gold_obj_count', 0)}",
        f"- Missing gold objects: {report.get('missing_gold_obj_count', 0)}",
        f"- Fully linked topics: {report.get('fully_linked_topic_count', 0)}",
        f"- Low-purity topics: {report.get('low_purity_topic_count', 0)}",
        "",
        "## Review Queue",
    ]
    queue = report.get("manual_review_queue", [])
    if not queue:
        lines.append("No review items.")
    for row in queue[:80]:
        lines.append(
            f"- `{row.get('gold_topic', '')}`: linked={row.get('linked_obj_count', 0)}/"
            f"{row.get('gold_obj_count', 0)}, primary=`{row.get('primary_l2_label', '')}`, "
            f"purity={row.get('primary_l2_purity', 0)}"
        )
    (out_root / "gold_topic_to_l2_l3_mapping.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _term_entry_counts(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    term_to_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        tokens = _tokens(_entry_text(entry))
        terms = set(tokens)
        terms.update(
            f"{tokens[index]} {tokens[index + 1]}"
            for index in range(len(tokens) - 1)
            if tokens[index] != tokens[index + 1]
        )
        for term in terms:
            term_to_entries[term].append(entry)
    rows: list[dict[str, Any]] = []
    for term, entries in term_to_entries.items():
        if len(entries) < 2:
            continue
        rows.append(
            {
                "term": term,
                "entry_count": len(entries),
                "representative_entries": entries[:5],
                "entry_ids": [
                    str(entry.get("obj_id", "") or "")
                    for entry in entries
                    if str(entry.get("obj_id", "") or "")
                ],
            }
        )
    rows.sort(
        key=lambda row: (
            -len(str(row["term"]).split()),
            -int(row["entry_count"]),
            -len(str(row["term"])),
            str(row["term"]),
        )
    )
    return rows


def _is_duplicate_cluster(candidate: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    candidate_ids = set(candidate.get("entry_ids", []) or [])
    candidate_terms = set(str(candidate.get("term", "") or "").split())
    if not candidate_ids or not candidate_terms:
        return False
    for row in selected:
        selected_ids = set(row.get("entry_ids", []) or [])
        selected_terms = set(str(row.get("term", "") or "").split())
        if not selected_ids or not selected_terms:
            continue
        entry_overlap = len(candidate_ids & selected_ids) / max(1, min(len(candidate_ids), len(selected_ids)))
        token_overlap = len(candidate_terms & selected_terms) / max(1, min(len(candidate_terms), len(selected_terms)))
        nested_terms = candidate_terms <= selected_terms or selected_terms <= candidate_terms
        if entry_overlap >= 0.8:
            return True
        if entry_overlap >= 0.6 and (token_overlap > 0 or nested_terms):
            return True
    return False


def _select_diverse_term_rows(
    rows: list[dict[str, Any]],
    *,
    max_child_proposals: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        term = str(row.get("term", "") or "")
        rejection_reason = _term_rejection_reason(term)
        if rejection_reason:
            rejected.append({"term": term, "reason": rejection_reason})
            continue
        if _is_duplicate_cluster(row, selected):
            rejected.append({"term": term, "reason": "duplicate_cluster"})
            continue
        selected.append(row)
        if len(selected) >= max_child_proposals:
            break
    return selected, rejected


def _source_l2_lookup(l2_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node.get("l2_id", "") or ""): node
        for node in l2_view.get("l2_nodes", [])
        if isinstance(node, dict) and str(node.get("l2_id", "") or "")
    }


def build_unknown_large_l2_split_proposal_sidecar(
    l2_view: dict[str, Any],
    l3_promotions: dict[str, Any],
    *,
    generated_at_utc: str | None = None,
    min_event_count: int = 24,
    max_child_proposals: int = 6,
) -> dict[str, Any]:
    """Build review-only split proposals for large L2 topics lacking child L2s."""
    l2_lookup = _source_l2_lookup(l2_view)
    proposals: list[dict[str, Any]] = []

    for promotion in l3_promotions.get("promotions", []) if isinstance(l3_promotions, dict) else []:
        if not isinstance(promotion, dict):
            continue
        if promotion.get("status") != "needs_split_review":
            continue
        source_l2_id = str(promotion.get("source_l2_id", "") or "")
        if promotion.get("child_l2_candidates"):
            continue
        source_node = l2_lookup.get(source_l2_id)
        if not source_node:
            continue
        event_count = int(
            source_node.get("event_count")
            or len(source_node.get("linked_obj_ids", []) if isinstance(source_node.get("linked_obj_ids"), list) else [])
        )
        metric_count = int(promotion.get("metrics", {}).get("linked_l1_count", event_count) or event_count)
        source_event_count = max(event_count, metric_count)
        if source_event_count < min_event_count:
            continue
        timeline = [
            entry
            for entry in source_node.get("timeline_digest", [])
            if isinstance(entry, dict)
        ]
        terms = _term_entry_counts(timeline)
        selected_terms, rejected_terms = _select_diverse_term_rows(
            terms,
            max_child_proposals=max_child_proposals,
        )
        children: list[dict[str, Any]] = []
        seen_slugs: set[str] = set()
        for term_row in selected_terms:
            term = str(term_row["term"])
            slug = _slug(term)
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            representative_obj_ids = [
                str(entry.get("obj_id", "") or "")
                for entry in term_row["representative_entries"]
                if str(entry.get("obj_id", "") or "")
            ]
            child_id = f"{source_l2_id}-{slug}"
            children.append(
                {
                    "candidate_child_l2_id": child_id,
                    "label": term,
                    "assignment_criteria": [term],
                    "estimated_event_count": int(term_row["entry_count"]),
                    "representative_obj_ids": representative_obj_ids,
                    "confidence": round(min(0.95, 0.35 + term_row["entry_count"] / max(source_event_count, 1)), 3),
                    "proposal_reason": "repeated_keyword_cluster",
                }
            )
            if len(children) >= max_child_proposals:
                break

        diagnostics_reason_codes = list(promotion.get("reason_codes", []) or [])
        if len(children) < 2:
            diagnostics_reason_codes.append("insufficient_distinct_keyword_clusters")

        if not children and timeline:
            children.append(
                {
                    "candidate_child_l2_id": f"{source_l2_id}-general",
                    "label": "general continuation",
                    "assignment_criteria": [str(source_node.get("label", "") or "")],
                    "estimated_event_count": source_event_count,
                    "representative_obj_ids": [
                        str(entry.get("obj_id", "") or "")
                        for entry in timeline[:5]
                        if str(entry.get("obj_id", "") or "")
                    ],
                    "confidence": 0.25,
                    "proposal_reason": "fallback_general_bucket",
                }
            )

        proposals.append(
            {
                "source_l2_id": source_l2_id,
                "source_l2_label": str(promotion.get("source_l2_label") or source_node.get("label") or ""),
                "source_event_count": source_event_count,
                "proposal_mode": "deterministic_keyword_clusters",
                "manual_review_required": True,
                "candidate_child_l2": children,
                "diagnostics": {
                    "candidate_term_count": len(terms),
                    "selected_term_count": len(selected_terms),
                    "rejected_term_count": len(rejected_terms),
                    "rejected_term_samples": rejected_terms[:10],
                    "timeline_digest_count": len(timeline),
                    "reason_codes": diagnostics_reason_codes,
                    "split_readiness": "reviewable" if len(children) >= 2 else "low",
                },
            }
        )

    return {
        "schema_version": 1,
        "generated_at_utc": generated_at_utc or _utc_now_iso(),
        "source": "long_term_l2_split_proposal_review",
        "proposal_count": len(proposals),
        "source_l2_ids": [proposal["source_l2_id"] for proposal in proposals],
        "split_proposals": proposals,
        "notes": [
            "This is a review sidecar. It does not mutate raw L1, active L2, or materialized L3.",
            "Candidate child L2 labels come from deterministic repeated keyword clusters and require manual review before promotion.",
        ],
    }


def write_l2_assignment_comparison(report: dict[str, Any], out: Path | str) -> None:
    out_root = Path(out)
    _write_json(out_root / "l2_assignment_comparison_report.json", report)
    _write_json(out_root / "changed_assignments.json", report.get("changed_assignments", []))
    _write_json(out_root / "manual_review_queue.json", report.get("manual_review_queue", []))
    lines = [
        "# L2 Assignment Comparison",
        "",
        f"- Baseline linked L1: {report.get('baseline_linked_count', 0)}",
        f"- Candidate linked L1: {report.get('candidate_linked_count', 0)}",
        f"- Changed assignments: {report.get('changed_assignment_count', 0)}",
        f"- Lost assignments: {report.get('lost_assignment_count', 0)}",
        f"- Gained assignments: {report.get('gained_assignment_count', 0)}",
        f"- Manual review items: {report.get('manual_review_count', 0)}",
        "",
    ]
    if report.get("manual_review_queue"):
        lines.append("## Manual Review")
        for item in report["manual_review_queue"][:50]:
            l1 = item.get("l1", {})
            lines.append(
                f"- `{item.get('reason_code')}` `{item.get('obj_id')}` "
                f"importance={l1.get('importance', 0)}"
            )
    else:
        lines.append("No manual review items.")
    (out_root / "l2_assignment_comparison_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_split_proposal_sidecar(sidecar: dict[str, Any], out: Path | str) -> None:
    out_root = Path(out)
    _write_json(out_root / "l2_split_proposals.json", sidecar)
    lines = [
        "# L2 Split Proposals",
        "",
        f"- Proposal count: {sidecar.get('proposal_count', 0)}",
        "",
    ]
    for proposal in sidecar.get("split_proposals", []):
        lines.append(
            f"## {proposal.get('source_l2_label', proposal.get('source_l2_id', ''))}"
        )
        lines.append(f"- Source L2: `{proposal.get('source_l2_id', '')}`")
        lines.append(f"- Source event count: {proposal.get('source_event_count', 0)}")
        for child in proposal.get("candidate_child_l2", []):
            lines.append(
                f"- `{child.get('candidate_child_l2_id', '')}`: "
                f"{child.get('label', '')} "
                f"(estimated {child.get('estimated_event_count', 0)})"
            )
        lines.append("")
    (out_root / "l2_split_proposals.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Side-by-side L2 taxonomy refinement reports.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser("compare-assignments")
    compare.add_argument("--baseline-l2-root", required=True)
    compare.add_argument("--candidate-l2-root", required=True)
    compare.add_argument("--share-mem-root", default=str(REPO_ROOT / "share_mem"))
    compare.add_argument("--out", required=True)

    split = subparsers.add_parser("propose-splits")
    split.add_argument("--l2-root", required=True)
    split.add_argument("--l3-root", required=True)
    split.add_argument("--out", required=True)
    split.add_argument("--min-event-count", type=int, default=24)
    split.add_argument("--max-child-proposals", type=int, default=6)

    gold = subparsers.add_parser("gold-topic-mapping")
    gold.add_argument("--share-mem-root", required=True)
    gold.add_argument("--l2-root", required=True)
    gold.add_argument("--l3-root", required=True)
    gold.add_argument("--gold-path", required=True)
    gold.add_argument("--out", required=True)
    gold.add_argument("--purity-threshold", type=float, default=0.80)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "compare-assignments":
        report = compare_l2_assignment_runs(
            baseline_l2_root=args.baseline_l2_root,
            candidate_l2_root=args.candidate_l2_root,
            share_mem_root=args.share_mem_root,
        )
        write_l2_assignment_comparison(report, args.out)
        print(
            "[long_term] L2 assignment comparison complete: "
            f"{report['changed_assignment_count']} changed, "
            f"{report['lost_assignment_count']} lost, "
            f"{report['gained_assignment_count']} gained"
        )
        return

    if args.command == "gold-topic-mapping":
        report = build_gold_topic_mapping_report(
            share_mem_root=args.share_mem_root,
            l2_root=args.l2_root,
            l3_root=args.l3_root,
            gold_path=args.gold_path,
            out=args.out,
            purity_threshold=args.purity_threshold,
        )
        print(
            "[long_term] Gold topic mapping complete: "
            f"{report['gold_topic_count']} topics, "
            f"{report['unlinked_gold_obj_count']} unlinked gold objects, "
            f"{report['low_purity_topic_count']} low-purity topics"
        )
        return

    l2_root = Path(args.l2_root)
    l3_root = Path(args.l3_root)
    sidecar = build_unknown_large_l2_split_proposal_sidecar(
        _load_json(l2_root / "l2_view.json"),
        _load_json(l3_root / "l3_promotions.json"),
        min_event_count=args.min_event_count,
        max_child_proposals=args.max_child_proposals,
    )
    write_split_proposal_sidecar(sidecar, args.out)
    print(f"[long_term] L2 split proposals complete: {sidecar['proposal_count']} proposals")


if __name__ == "__main__":
    main()
