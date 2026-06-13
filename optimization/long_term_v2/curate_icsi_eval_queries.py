from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.effective_view import load_effective_topic_surface
from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import (
    load_profile,
    profile_generic_topic_labels,
    profile_rejected_topic_labels,
    profile_type_like_labels,
    profile_weak_phrase_terms,
)
from share_mem.store import build_l1_index, load_share_tree


DEFAULT_EVAL_WEAK_PHRASE_TERMS = {
    "bit",
    "little",
    "pretty",
    "go",
    "ahead",
    "know",
    "thing",
    "things",
}

DEFAULT_EVAL_TYPE_TERMS = {
    "argument",
    "decision",
    "finding",
    "issue",
    "proposal",
    "question",
    "result",
    "todo",
}


def _event_obj_ids(node: dict[str, Any]) -> list[str]:
    ids = [str(obj_id) for obj_id in node.get("linked_obj_ids", []) or [] if str(obj_id)]
    if ids:
        return ids
    return [
        str(event.get("obj_id", "") or "")
        for event in node.get("timeline_digest", []) or []
        if isinstance(event, dict) and str(event.get("obj_id", "") or "")
    ]


def _meeting_spread(node: dict[str, Any], l1_index: dict[str, dict[str, Any]]) -> int:
    meeting_ids: set[str] = set()
    for obj_id in _event_obj_ids(node):
        if obj_id in l1_index:
            meeting_ids.add(str(l1_index[obj_id].get("meeting_id", "") or ""))
    for event in node.get("timeline_digest", []) or []:
        if isinstance(event, dict):
            meeting_ids.add(str(event.get("meeting_id", "") or ""))
    return len({meeting_id for meeting_id in meeting_ids if meeting_id})


def _representative_obj_ids(node: dict[str, Any], l1_index: dict[str, dict[str, Any]], *, limit: int = 4) -> list[str]:
    output: list[str] = []
    for event in node.get("timeline_digest", []) or []:
        if not isinstance(event, dict):
            continue
        obj_id = str(event.get("obj_id", "") or "")
        if obj_id and obj_id in l1_index and obj_id not in output:
            output.append(obj_id)
        if len(output) >= limit:
            return output
    for obj_id in _event_obj_ids(node):
        if obj_id in l1_index and obj_id not in output:
            output.append(obj_id)
        if len(output) >= limit:
            break
    return output


def _question_for(label: str, *, query_type: str) -> str:
    if query_type == "evolution":
        return f"ICSI BMR meetings discussed {label}. How did that topic evolve across meetings?"
    if query_type == "evidence":
        return f"What concrete evidence do the ICSI BMR meetings contain about {label}?"
    return f"What did the ICSI BMR meetings discuss about {label}?"


def _is_eval_candidate_label(label: str, *, profile: dict[str, Any]) -> bool:
    clean = str(label).strip().lower().replace("_", " ")
    if not clean:
        return False
    terms = set(clean.split())
    type_like = profile_type_like_labels(profile) | DEFAULT_EVAL_TYPE_TERMS
    rejected = profile_rejected_topic_labels(profile)
    generic = profile_generic_topic_labels(profile)
    if clean in type_like or terms & type_like:
        return False
    if clean in rejected or terms & rejected:
        return False
    if clean in generic or terms & generic:
        return False
    if terms & (profile_weak_phrase_terms(profile) | DEFAULT_EVAL_WEAK_PHRASE_TERMS):
        return False
    return True


def _query_rows(
    *,
    nodes: list[dict[str, Any]],
    l1_index: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    max_queries: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    query_types = ["overview", "evolution", "evidence"]
    for node in nodes:
        label = str(node.get("label", "") or "").strip()
        l2_id = str(node.get("l2_id", "") or "").strip()
        if not label or not l2_id:
            continue
        if not _is_eval_candidate_label(label, profile=profile):
            continue
        reps = _representative_obj_ids(node, l1_index)
        if not reps:
            continue
        query_type = query_types[len(rows) % len(query_types)]
        rows.append(
            {
                "query_id": f"icsi-q{len(rows) + 1:03d}",
                "query": _question_for(label, query_type=query_type),
                "query_type": query_type,
                "expected_obj_ids": reps,
                "expected_l2_ids": [l2_id],
                "expected_l2_labels": [label],
                "expected_l3_ids": [],
                "expected_l3_labels": [],
                "notes": (
                    "Auto-curated from optimization v2 active effective L2. "
                    "Use for retrieval trace review, not final answer-quality claims until manually approved."
                ),
            }
        )
        if len(rows) >= max_queries:
            break
    return rows


def _format_report(rows: list[dict[str, Any]], *, l1_index: dict[str, dict[str, Any]], report: dict[str, Any]) -> str:
    lines = [
        "# ICSI BMR Retrieval Query Review",
        "",
        f"- generated at: `{report['generated_at_utc']}`",
        f"- query count: `{report['query_count']}`",
        f"- active L2 count: `{report['active_l2_count']}`",
        f"- suppressed L2 count: `{report['suppressed_l2_count']}`",
        "",
        "These queries are generated from active effective L2 topics. They are for retrieval trace review, not final professor-facing scoring until manually approved.",
        "",
        "## Queries",
        "",
    ]
    for row in rows:
        labels = ", ".join(row.get("expected_l2_labels", []) or [])
        lines.append(f"### {row['query_id']}: {row['query']}")
        lines.append(f"- expected L2 labels: {labels}")
        lines.append("- representative L1:")
        for obj_id in row.get("expected_obj_ids", []) or []:
            obj = l1_index.get(str(obj_id), {})
            lines.append(
                f"  - `{obj_id}` {obj.get('meeting_id', '')}: "
                f"{str(obj.get('content', '') or '')[:220]}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def curate_icsi_eval_queries(
    *,
    run_root: Path | str,
    share_mem_root: Path | str,
    out: Path | str,
    report_out: Path | str | None = None,
    report_json_out: Path | str | None = None,
    max_queries: int = 12,
) -> dict[str, Any]:
    root = Path(run_root)
    l1_index = build_l1_index(load_share_tree(share_mem_root))
    surface = load_effective_topic_surface(root)
    manifest = load_json(root / "manifest.json") if (root / "manifest.json").exists() else {}
    profile: dict[str, Any] = {}
    profile_path = manifest.get("profile_path")
    if profile_path and Path(str(profile_path)).exists():
        profile = load_profile(str(profile_path))
    nodes = [
        node
        for node in surface["l2_view"].get("l2_nodes", []) or []
        if isinstance(node, dict)
    ]
    nodes.sort(
        key=lambda node: (
            -_meeting_spread(node, l1_index),
            -len(_event_obj_ids(node)),
            str(node.get("label", "") or ""),
        )
    )
    rows = _query_rows(nodes=nodes, l1_index=l1_index, profile=profile, max_queries=max_queries)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "share_mem_root": str(Path(share_mem_root).resolve()),
        "query_count": len(rows),
        "active_l2_count": surface["active_l2_count"],
        "suppressed_l2_count": surface["suppressed_l2_count"],
        "suppressed_l2_ids": surface["suppressed_l2_ids"],
        "query_ids": [row["query_id"] for row in rows],
    }
    if report_json_out:
        write_json(report_json_out, report)
    if report_out:
        write_text(report_out, _format_report(rows, l1_index=l1_index, report=report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate first-pass ICSI BMR retrieval queries from active effective L2 topics.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--share-mem-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report-out", default="")
    parser.add_argument("--report-json-out", default="")
    parser.add_argument("--max-queries", type=int, default=12)
    args = parser.parse_args()
    report = curate_icsi_eval_queries(
        run_root=args.run_root,
        share_mem_root=args.share_mem_root,
        out=args.out,
        report_out=args.report_out or None,
        report_json_out=args.report_json_out or None,
        max_queries=args.max_queries,
    )
    print(
        "[optimization:v2] ICSI eval query curation complete: "
        f"queries={report['query_count']} active_l2={report['active_l2_count']} "
        f"suppressed_l2={report['suppressed_l2_count']}"
    )


if __name__ == "__main__":
    main()
