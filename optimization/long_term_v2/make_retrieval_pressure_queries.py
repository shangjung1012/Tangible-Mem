from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text


def _memory_objects_by_id(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for meeting in tree.get("meetings", []) or []:
        if not isinstance(meeting, dict):
            continue
        meeting_id = str(meeting.get("meeting_id", "") or "")
        meeting_date = str(meeting.get("meeting_date", "") or "")
        for obj in meeting.get("memory_objects", []) or []:
            if not isinstance(obj, dict):
                continue
            obj_id = str(obj.get("obj_id", "") or "")
            if not obj_id:
                continue
            row = dict(obj)
            row.setdefault("meeting_id", meeting_id)
            row.setdefault("meeting_date", meeting_date)
            rows[obj_id] = row
    return rows


def _load_needs_split_reviews(run_root: Path) -> list[dict[str, Any]]:
    path = run_root / "l3" / "l2_merge_review.json"
    if not path.exists():
        return []
    payload = load_json(path)
    reviews = payload.get("merge_reviews", []) if isinstance(payload, dict) else []
    return [
        row
        for row in reviews
        if isinstance(row, dict) and row.get("action") == "needs_split_review"
    ]


def _l2_nodes_by_id(run_root: Path) -> dict[str, dict[str, Any]]:
    path = run_root / "l2" / "l2_view.json"
    if not path.exists():
        return {}
    payload = load_json(path)
    nodes = payload.get("l2_nodes", []) if isinstance(payload, dict) else []
    return {
        str(node.get("l2_id", "") or ""): node
        for node in nodes
        if isinstance(node, dict) and node.get("l2_id")
    }


def _clean_preview(text: str, *, max_words: int = 12) -> str:
    words = re.findall(r"[\w\-]+", text, flags=re.UNICODE)
    return " ".join(words[:max_words])


def _build_query(label: str, representative_rows: list[dict[str, Any]]) -> str:
    previews = [
        _clean_preview(str(row.get("content", "") or row.get("evidence", "") or ""), max_words=8)
        for row in representative_rows[:2]
    ]
    previews = [preview for preview in previews if preview]
    if previews:
        return f"What decisions, rationale, and unresolved tensions are connected to {label}? Evidence focus: {'; '.join(previews)}"
    return f"What decisions, rationale, and unresolved tensions are connected to {label}?"


def build_retrieval_pressure_queries(
    *,
    run_root: Path | str,
    max_topics: int = 8,
    max_expected_obj_ids: int = 6,
    out_path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(run_root)
    tree_path = root / "input_snapshot" / "tree.json"
    if not tree_path.exists():
        raise FileNotFoundError(f"Missing optimization input snapshot: {tree_path}")
    l1_by_id = _memory_objects_by_id(load_json(tree_path))
    l2_by_id = _l2_nodes_by_id(root)
    reviews = _load_needs_split_reviews(root)
    reviews.sort(
        key=lambda row: (
            -int(row.get("source_event_count", 0) or 0),
            str(row.get("source_l2_id", "") or ""),
        )
    )

    queries: list[dict[str, Any]] = []
    for review in reviews[:max_topics]:
        source_l2_id = str(review.get("source_l2_id", "") or "")
        node = l2_by_id.get(source_l2_id, {})
        label = str(review.get("source_l2_label") or node.get("label") or source_l2_id)
        linked_obj_ids = [
            str(obj_id)
            for obj_id in (node.get("linked_obj_ids", []) or [])
            if str(obj_id) in l1_by_id
        ]
        expected_obj_ids = linked_obj_ids[:max_expected_obj_ids]
        representative_rows = [l1_by_id[obj_id] for obj_id in expected_obj_ids]
        queries.append(
            {
                "query": _build_query(label, representative_rows),
                "expected_obj_ids": expected_obj_ids,
                "expected_l2_ids": [source_l2_id] if source_l2_id else [],
                "expected_l2_labels": [label] if label else [],
                "expected_l3_ids": [],
                "expected_l3_labels": [],
                "notes": "Generated from optimization v2 needs_split_review for retrieval pressure diagnostics.",
            }
        )

    out = Path(out_path) if out_path else root / "retrieval_eval" / "pressure_queries.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in queries),
        encoding="utf-8",
    )
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "query_count": len(queries),
        "source_needs_split_count": len(reviews),
        "queries_path": str(out.resolve()),
        "queries": queries,
    }
    write_json(root / "retrieval_eval" / "pressure_queries_report.json", report)
    write_text(
        root / "retrieval_eval" / "pressure_queries_report.md",
        "\n".join(
            [
                "# Retrieval Pressure Diagnostic Queries",
                "",
                f"- needs split topics: {len(reviews)}",
                f"- generated queries: {len(queries)}",
                f"- output: `{out}`",
                "",
            ]
        ),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate v2-native retrieval queries from needs_split_review L2 topics.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--max-topics", type=int, default=8)
    parser.add_argument("--max-expected-obj-ids", type=int, default=6)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = build_retrieval_pressure_queries(
        run_root=args.run_root,
        max_topics=args.max_topics,
        max_expected_obj_ids=args.max_expected_obj_ids,
        out_path=args.out,
    )
    print(
        "[optimization:v2] retrieval pressure queries complete: "
        f"queries={report['query_count']} needs_split={report['source_needs_split_count']}"
    )


if __name__ == "__main__":
    main()
