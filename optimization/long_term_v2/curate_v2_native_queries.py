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


def _iter_l1(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
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


def _l2_nodes(run_root: Path) -> list[dict[str, Any]]:
    path = run_root / "l2" / "l2_view.json"
    if not path.exists():
        return []
    payload = load_json(path)
    return [node for node in payload.get("l2_nodes", []) or [] if isinstance(node, dict)]


def _needs_split_ids(run_root: Path) -> set[str]:
    path = run_root / "l3" / "l2_merge_review.json"
    if not path.exists():
        return set()
    payload = load_json(path)
    return {
        str(row.get("source_l2_id", "") or "")
        for row in payload.get("merge_reviews", []) or []
        if isinstance(row, dict) and row.get("action") == "needs_split_review" and row.get("source_l2_id")
    }


def _topic_nodes(run_root: Path, *, topic_source: str) -> list[dict[str, Any]]:
    nodes = _l2_nodes(run_root)
    if topic_source == "needs_split":
        needed = _needs_split_ids(run_root)
        nodes = [node for node in nodes if str(node.get("l2_id", "") or "") in needed]
    elif topic_source != "largest":
        raise ValueError("topic_source must be one of: largest, needs_split")
    nodes.sort(
        key=lambda node: (
            -len(node.get("linked_obj_ids", []) or []),
            str(node.get("label", "") or ""),
        )
    )
    return nodes


def _compact(text: str, *, max_words: int = 18) -> str:
    words = re.findall(r"[\w\-]+", text, flags=re.UNICODE)
    return " ".join(words[:max_words])


def _expected_obj_ids(node: dict[str, Any], l1_by_id: dict[str, dict[str, Any]], *, max_expected_obj_ids: int) -> list[str]:
    ids: list[str] = []
    for obj_id in (node.get("representative_l1_ids", []) or []) + (node.get("linked_obj_ids", []) or []):
        obj_id = str(obj_id)
        if obj_id in l1_by_id and obj_id not in ids:
            ids.append(obj_id)
        if len(ids) >= max_expected_obj_ids:
            break
    return ids


def _query_for_node(node: dict[str, Any], representative_rows: list[dict[str, Any]], *, style: str) -> str:
    label = str(node.get("label", "") or node.get("l2_id", "") or "this topic")
    definition = _compact(str(node.get("definition", "") or node.get("current_state", "") or ""), max_words=14)
    evidence_hint = _compact(
        " ".join(str(row.get("content", "") or row.get("evidence", "") or "") for row in representative_rows[:2]),
        max_words=20,
    )
    if style == "rationale":
        return f"Why did the discussion around {label} matter, and what rationale or open tensions did the evidence show? {definition} {evidence_hint}".strip()
    if style == "evolution":
        return f"How did {label} evolve across the meetings, based on the concrete L1 evidence? {definition} {evidence_hint}".strip()
    return f"What did the mentor and mentee decide or discuss about {label}? {definition} {evidence_hint}".strip()


def curate_v2_native_queries(
    *,
    run_root: Path | str,
    topic_source: str = "largest",
    max_queries: int = 12,
    max_expected_obj_ids: int = 6,
    out_path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(run_root)
    tree_path = root / "input_snapshot" / "tree.json"
    if not tree_path.exists():
        raise FileNotFoundError(f"Missing input snapshot tree: {tree_path}")
    l1_by_id = _iter_l1(load_json(tree_path))
    styles = ["rationale", "evolution", "decision"]
    queries: list[dict[str, Any]] = []
    for idx, node in enumerate(_topic_nodes(root, topic_source=topic_source)[:max_queries]):
        expected_obj_ids = _expected_obj_ids(node, l1_by_id, max_expected_obj_ids=max_expected_obj_ids)
        rows = [l1_by_id[obj_id] for obj_id in expected_obj_ids]
        style = styles[idx % len(styles)]
        label = str(node.get("label", "") or "")
        l2_id = str(node.get("l2_id", "") or "")
        queries.append(
            {
                "query": _query_for_node(node, rows, style=style),
                "expected_obj_ids": expected_obj_ids,
                "expected_l2_ids": [l2_id] if l2_id else [],
                "expected_l2_labels": [label] if label else [],
                "expected_l3_ids": [],
                "expected_l3_labels": [],
                "notes": f"v2-native {style} diagnostic query generated from {topic_source} L2 topics.",
            }
        )

    out = Path(out_path) if out_path else root / "retrieval_eval" / "v2_native_queries.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in queries),
        encoding="utf-8",
    )
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "topic_source": topic_source,
        "query_count": len(queries),
        "queries_path": str(out.resolve()),
        "queries": queries,
    }
    write_json(root / "retrieval_eval" / "v2_native_queries_report.json", report)
    write_text(
        root / "retrieval_eval" / "v2_native_queries_report.md",
        "\n".join(
            [
                "# Optimization v2 Native Queries",
                "",
                f"- topic source: `{topic_source}`",
                f"- generated queries: {len(queries)}",
                f"- output: `{out}`",
                "",
            ]
        ),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate v2-native retrieval diagnostic queries from L2 topics.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--topic-source", choices=["largest", "needs_split"], default="largest")
    parser.add_argument("--max-queries", type=int, default=12)
    parser.add_argument("--max-expected-obj-ids", type=int, default=6)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = curate_v2_native_queries(
        run_root=args.run_root,
        topic_source=args.topic_source,
        max_queries=args.max_queries,
        max_expected_obj_ids=args.max_expected_obj_ids,
        out_path=args.out,
    )
    print(
        "[optimization:v2] native query curation complete: "
        f"queries={report['query_count']} topic_source={report['topic_source']}"
    )


if __name__ == "__main__":
    main()
