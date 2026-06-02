from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text


def _needs_split_sources(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "l3" / "l2_merge_review.json"
    if not path.exists():
        return {}
    data = load_json(path)
    output: dict[str, dict[str, Any]] = {}
    for row in data.get("merge_reviews", []) or []:
        if row.get("action") != "needs_split_review" or not row.get("source_l2_id"):
            continue
        output[str(row["source_l2_id"])] = row
    return output


def _l2_lookup(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "l2" / "l2_view.json"
    if not path.exists():
        return {}
    data = load_json(path)
    return {str(node.get("l2_id", "")): node for node in data.get("l2_nodes", []) or []}


def _retrieval_queries(root: Path, subdir: str) -> list[dict[str, Any]]:
    path = root / subdir / "retrieval_eval_report.json"
    if not path.exists():
        return []
    return load_json(path).get("queries", []) or []


def build_retrieval_split_pressure_report(
    *,
    run_root: Path | str,
    retrieval_subdir: str = "retrieval_eval",
) -> dict[str, Any]:
    root = Path(run_root)
    ensure_optimization_output(root / "reports")
    needs = _needs_split_sources(root)
    l2_by_id = _l2_lookup(root)
    queries = _retrieval_queries(root, retrieval_subdir)
    query_hits: dict[str, list[str]] = defaultdict(list)
    for query in queries:
        query_id = str(query.get("query_id", "") or query.get("query", "") or "")
        for l2_id in query.get("selected_l2_ids", []) or []:
            if str(l2_id) in needs:
                query_hits[str(l2_id)].append(query_id)
    topics: list[dict[str, Any]] = []
    for l2_id, review in needs.items():
        node = l2_by_id.get(l2_id, {})
        linked_count = len(node.get("linked_obj_ids", []) or [])
        retrieval_count = len(set(query_hits.get(l2_id, [])))
        pressure_score = round(retrieval_count * 1000 + linked_count, 4)
        topics.append(
            {
                "l2_id": l2_id,
                "label": node.get("label") or review.get("source_l2_label", ""),
                "event_count": linked_count or review.get("source_event_count", 0),
                "retrieval_query_count": retrieval_count,
                "retrieval_query_ids": sorted(set(query_hits.get(l2_id, []))),
                "max_child_event_count": review.get("max_child_event_count"),
                "non_empty_child_count": review.get("non_empty_child_count"),
                "pressure_score": pressure_score,
            }
        )
    topics.sort(key=lambda row: (-row["retrieval_query_count"], -int(row.get("event_count", 0) or 0), row["l2_id"]))
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "retrieval_subdir": retrieval_subdir,
        "needs_split_topic_count": len(needs),
        "query_count": len(queries),
        "topics_with_retrieval_pressure_count": sum(1 for row in topics if row["retrieval_query_count"] > 0),
        "topics": topics,
    }
    out = root / "reports"
    write_json(out / "retrieval_split_pressure.json", report)
    lines = [
        "# Retrieval Split Pressure",
        "",
        f"- run root: `{report['run_root']}`",
        f"- retrieval queries: {report['query_count']}",
        f"- needs-split topics: {report['needs_split_topic_count']}",
        f"- topics with retrieval pressure: {report['topics_with_retrieval_pressure_count']}",
        "",
        "| L2 | events | retrieval queries | max child | non-empty children |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in topics:
        lines.append(
            f"| `{row['l2_id']}` {row['label']} | {row['event_count']} | {row['retrieval_query_count']} | "
            f"{row.get('max_child_event_count') or ''} | {row.get('non_empty_child_count') or ''} |"
        )
    write_text(out / "retrieval_split_pressure.md", "\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank needs_split_review L2 topics by actual retrieval pressure.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--retrieval-subdir", default="retrieval_eval")
    args = parser.parse_args()
    report = build_retrieval_split_pressure_report(
        run_root=args.run_root,
        retrieval_subdir=args.retrieval_subdir,
    )
    print(
        "[optimization:v2] retrieval split pressure complete: "
        f"needs_split={report['needs_split_topic_count']} pressure_topics={report['topics_with_retrieval_pressure_count']}"
    )


if __name__ == "__main__":
    main()
