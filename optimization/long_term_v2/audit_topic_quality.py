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
from optimization.long_term_v2.text_utils import jaccard, normalize_phrase, tokens


_AUDIT_STOPWORDS = {
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "because",
    "be",
    "before",
    "by",
    "can",
    "data",
    "discussed",
    "discussion",
    "do",
    "evidence",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "into",
    "meeting",
    "more",
    "need",
    "needed",
    "not",
    "of",
    "on",
    "or",
    "required",
    "source",
    "system",
    "that",
    "the",
    "their",
    "this",
    "to",
    "topic",
    "used",
    "was",
    "were",
    "which",
    "will",
    "with",
}

_BROAD_LABEL_TOKENS = {
    "collection",
    "corpus",
    "data",
    "management",
    "recording",
    "setup",
    "source",
}

_REVIEW_ONLY_MITIGATION_MAX_L1 = 10


def _issue(severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        **extra,
    }


def _topic_rows(node: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for event in node.get("timeline_digest", []) or []:
        if isinstance(event, dict):
            rows.append(str(event.get("summary", "") or ""))
    for term in node.get("top_semantic_terms", []) or []:
        if isinstance(term, dict):
            rows.append(str(term.get("term", "") or ""))
    return rows


def _signature(text: str) -> set[str]:
    return set(tokens(text, stopwords=_AUDIT_STOPWORDS))


def _cluster_signatures(signatures: list[set[str]]) -> list[set[str]]:
    clusters: list[set[str]] = []
    for signature in signatures:
        if not signature:
            continue
        best_index = -1
        best_score = 0.0
        for index, cluster in enumerate(clusters):
            score = jaccard(signature, cluster)
            if score > best_score:
                best_index = index
                best_score = score
        if best_index >= 0 and best_score >= 0.18:
            clusters[best_index] |= signature
        else:
            clusters.append(set(signature))
    return clusters


def _representative_keywords(signatures: list[set[str]], *, limit: int = 12) -> list[str]:
    counts: Counter[str] = Counter()
    for signature in signatures:
        counts.update(signature)
    return [term for term, _count in counts.most_common(limit)]


def _healthy_split_source_ids(l3_view: dict[str, Any]) -> set[str]:
    source_ids: set[str] = set()
    for parent in l3_view.get("l3_parents", []) or []:
        if not isinstance(parent, dict):
            continue
        source_l2_id = str(parent.get("source_l2_id", "") or "")
        children = [child for child in parent.get("child_l2_nodes", []) or [] if isinstance(child, dict)]
        if not source_l2_id or len(children) < 2:
            continue
        child_sizes = [len(child.get("linked_obj_ids", []) or []) for child in children]
        if child_sizes and min(child_sizes) >= 3 and max(child_sizes) <= 35:
            source_ids.add(source_l2_id)
    return source_ids


def _review_only_dispositions(run_root: Path) -> dict[str, dict[str, Any]]:
    path = run_root / "l2" / "llm_split_review_proposals.json"
    if not path.exists():
        return {}
    report = load_json(path)
    dispositions: dict[str, dict[str, Any]] = {}
    for row in report.get("review_only", []) or []:
        if not isinstance(row, dict):
            continue
        source_l2_id = str(row.get("source_l2_id", "") or "")
        reason = str(row.get("reason", "") or "").strip()
        representative_l1_ids = [
            str(obj_id)
            for obj_id in row.get("representative_l1_ids", []) or []
            if str(obj_id).strip()
        ]
        if source_l2_id and reason and len(representative_l1_ids) >= 2:
            dispositions[source_l2_id] = {
                "source": "llm_focused_split_review",
                "reason": reason,
                "representative_l1_ids": representative_l1_ids,
            }
    return dispositions


def _audit_l2_node(
    node: dict[str, Any],
    *,
    mitigated_source_ids: set[str] | None = None,
    review_only_dispositions: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mitigated_source_ids = mitigated_source_ids or set()
    review_only_dispositions = review_only_dispositions or {}
    label = str(node.get("label", "") or "")
    l2_id = str(node.get("l2_id", "") or "")
    obj_ids = [str(obj_id) for obj_id in node.get("linked_obj_ids", []) or []]
    rows = _topic_rows(node)
    signatures = [_signature(row) for row in rows]
    clusters = _cluster_signatures(signatures)
    keywords = _representative_keywords(signatures)
    label_tokens = set(normalize_phrase(label).split())
    broad_label_risk = bool(label_tokens & _BROAD_LABEL_TOKENS) and len(label_tokens) <= 2
    cluster_count = len(clusters)
    largest_cluster_share = 0.0
    if clusters:
        largest_cluster_share = max(len(cluster) for cluster in clusters) / max(
            1,
            sum(len(cluster) for cluster in clusters),
        )
    issues: list[dict[str, Any]] = []
    split_mitigation = "materialized_child_l2_context" if l2_id in mitigated_source_ids else "none"
    review_disposition_mitigation = "none"
    review_disposition = review_only_dispositions.get(l2_id)
    if review_disposition and len(obj_ids) <= _REVIEW_ONLY_MITIGATION_MAX_L1:
        review_disposition_mitigation = "llm_review_only_small_topic"
    if (
        split_mitigation == "none"
        and review_disposition_mitigation == "none"
        and len(obj_ids) >= 4
        and cluster_count >= 3
        and (broad_label_risk or largest_cluster_share < 0.70)
    ):
        issues.append(
            _issue(
                "warning",
                "broad_l2_mixed_signatures",
                "L2 appears to mix several weakly-overlapping semantic signatures.",
                l2_id=l2_id,
                label=label,
                linked_l1_count=len(obj_ids),
                cluster_count=cluster_count,
                representative_keywords=keywords,
            )
        )
        issues.append(
            _issue(
                "warning",
                "needs_topic_review",
                "Human or LLM-assisted topic review should inspect this L2 before larger promotion.",
                l2_id=l2_id,
                label=label,
            )
        )
    return issues, {
        "l2_id": l2_id,
        "label": label,
        "linked_l1_count": len(obj_ids),
        "cluster_count": cluster_count,
        "largest_cluster_share": round(largest_cluster_share, 3),
        "representative_keywords": keywords,
        "broad_label_risk": broad_label_risk,
        "split_mitigation": split_mitigation,
        "review_disposition_mitigation": review_disposition_mitigation,
        "review_disposition": review_disposition or {},
    }


def _audit_l3_view(l3_view: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for parent in l3_view.get("l3_parents", []) or []:
        if not isinstance(parent, dict):
            continue
        child_nodes = parent.get("child_l2_nodes", []) or []
        if len(child_nodes) < 2:
            issues.append(
                _issue(
                    "warning",
                    "weak_l3_child_count",
                    "L3 parent has fewer than two child L2 nodes.",
                    l3_id=parent.get("l3_id", ""),
                    label=parent.get("label", ""),
                )
            )
        for child in child_nodes:
            if not isinstance(child, dict):
                continue
            count = len(child.get("linked_obj_ids", []) or [])
            bucket = "ideal"
            if count < 3:
                bucket = "tiny_child_l2"
                issues.append(
                    _issue(
                        "warning",
                        "tiny_child_l2",
                        "Child L2 has fewer than 3 linked L1 objects.",
                        l3_id=parent.get("l3_id", ""),
                        child_l2_id=child.get("child_l2_id", child.get("l2_id", "")),
                        label=child.get("label", ""),
                        linked_l1_count=count,
                    )
                )
            elif count > 35:
                bucket = "oversized_child_l2"
                issues.append(
                    _issue(
                        "warning",
                        "oversized_child_l2",
                        "Child L2 remains oversized after promotion.",
                        l3_id=parent.get("l3_id", ""),
                        child_l2_id=child.get("child_l2_id", child.get("l2_id", "")),
                        label=child.get("label", ""),
                        linked_l1_count=count,
                    )
                )
            summaries.append(
                {
                    "l3_id": parent.get("l3_id", ""),
                    "child_l2_id": child.get("child_l2_id", child.get("l2_id", "")),
                    "label": child.get("label", ""),
                    "linked_l1_count": count,
                    "size_bucket": bucket,
                }
            )
    return issues, summaries


def audit_topic_quality(*, run_root: Path | str, out: Path | str | None = None) -> dict[str, Any]:
    root = Path(run_root)
    out_dir = Path(out) if out is not None else root / "topic_quality"
    l2_view = load_json(root / "l2" / "l2_view.json")
    l3_path = root / "l3" / "l3_view.json"
    l3_view = load_json(l3_path) if l3_path.exists() else {"l3_parents": []}
    mitigated_source_ids = _healthy_split_source_ids(l3_view)
    review_only_dispositions = _review_only_dispositions(root)

    issues: list[dict[str, Any]] = []
    topic_summaries: list[dict[str, Any]] = []
    for node in l2_view.get("l2_nodes", []) or []:
        if not isinstance(node, dict):
            continue
        node_issues, summary = _audit_l2_node(
            node,
            mitigated_source_ids=mitigated_source_ids,
            review_only_dispositions=review_only_dispositions,
        )
        issues.extend(node_issues)
        topic_summaries.append(summary)
    l3_issues, child_summaries = _audit_l3_view(l3_view)
    issues.extend(l3_issues)

    manual_queue = [
        issue
        for issue in issues
        if issue["code"] in {"broad_l2_mixed_signatures", "needs_topic_review", "oversized_child_l2", "tiny_child_l2"}
    ]
    severe_count = sum(1 for issue in issues if issue["severity"] == "severe")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "severe_count": severe_count,
        "warning_count": warning_count,
        "issue_count": len(issues),
        "issues": issues,
        "topic_summaries": topic_summaries,
        "child_l2_summaries": child_summaries,
        "manual_review_count": len(manual_queue),
    }
    write_json(out_dir / "topic_quality_report.json", report)
    write_json(out_dir / "manual_topic_review_queue.json", {"items": manual_queue})
    lines = [
        "# Topic Quality Audit",
        "",
        f"- severe issues: {severe_count}",
        f"- warnings: {warning_count}",
        f"- manual review items: {len(manual_queue)}",
        "",
        "## Review Items",
        "",
    ]
    for issue in manual_queue[:50]:
        lines.append(f"- `{issue['code']}` {issue.get('label', '')}: {issue['message']}")
    write_text(out_dir / "topic_quality_report.md", "\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit optimization v2 L2/L3 topic quality.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    report = audit_topic_quality(run_root=args.run_root, out=args.out or None)
    print(
        "[optimization:v2] topic audit complete: "
        f"severe={report['severe_count']} warnings={report['warning_count']} "
        f"manual={report['manual_review_count']}"
    )


if __name__ == "__main__":
    main()
