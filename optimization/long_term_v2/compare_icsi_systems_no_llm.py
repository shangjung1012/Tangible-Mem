from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from memory_observatory.services.token_utils import estimate_tokens
from optimization.long_term_v2.effective_view import load_effective_topic_surface
from optimization.long_term_v2.evaluate_retrieval import _load_queries, _rank_l1
from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import load_profile
from share_mem.store import build_l1_index, load_share_tree


STRATEGIES = ["full_context_l1", "rag_l1_lexical", "optimization_v2_layered"]


def _load_profile_for_run(run_root: Path) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = load_json(manifest_path)
    profile_path = manifest.get("profile_path")
    if profile_path and Path(str(profile_path)).exists():
        return load_profile(str(profile_path))
    return {}


def _l1_context(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in rows:
        lines.extend(
            [
                f"- [{row.get('meeting_id', '')} | {row.get('obj_id', '')}] type={row.get('type', '')}",
                f"  content: {row.get('content', '')}",
                f"  evidence: {row.get('evidence', '')}",
            ]
        )
    return "\n".join(lines)


def _layered_context(
    *,
    selected_l1: list[dict[str, Any]],
    l1_index: dict[str, dict[str, Any]],
    l2_index: dict[str, dict[str, Any]],
    l3_index: dict[str, dict[str, Any]],
) -> str:
    lines = ["=== L1 Evidence Seeds ==="]
    for selected in selected_l1:
        row = l1_index.get(selected["obj_id"], {})
        lines.extend(
            [
                f"- [{row.get('meeting_id', '')} | {selected['obj_id']}] score={selected.get('score')}",
                f"  content: {row.get('content', '')}",
                f"  evidence: {row.get('evidence', '')}",
            ]
        )
    l2_labels = sorted(
        {
            str(l2_index[obj_id].get("l2_label", ""))
            for obj_id in [row["obj_id"] for row in selected_l1]
            if obj_id in l2_index and isinstance(l2_index[obj_id], dict)
        }
    )
    l3_labels = sorted(
        {
            str(l3_index[obj_id].get("parent_l3_label", ""))
            for obj_id in [row["obj_id"] for row in selected_l1]
            if obj_id in l3_index and isinstance(l3_index[obj_id], dict)
        }
    )
    lines.extend(["", "=== Topic Surface ==="])
    lines.append(f"L2 labels: {', '.join(label for label in l2_labels if label)}")
    lines.append(f"L3 labels: {', '.join(label for label in l3_labels if label)}")
    return "\n".join(lines)


def _recall(expected: set[str], selected: set[str]) -> float:
    if not expected:
        return 0.0
    return round(len(expected & selected) / len(expected), 4)


def _average(values: list[float]) -> float:
    return round(sum(values) / max(len(values), 1), 4)


def _strategy_metrics(rows: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    recalls = [float(row["strategies"][strategy]["expected_l1_recall"]) for row in rows]
    tokens = [float(row["strategies"][strategy]["context_tokens"]) for row in rows]
    selected_counts = [float(row["strategies"][strategy]["selected_l1_count"]) for row in rows]
    return {
        "expected_l1_recall": _average(recalls),
        "avg_context_tokens": _average(tokens),
        "avg_selected_l1_count": _average(selected_counts),
    }


def _format_md(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# ICSI No-LLM System Comparison",
        "",
        "This is a retrieval/evidence comparison only. It does not call Gemini/Vertex and does not score final generated answers.",
        "",
        "## Summary",
        "",
        "| Strategy | Expected L1 recall | Avg context tokens | Avg selected L1 |",
        "|---|---:|---:|---:|",
    ]
    for strategy in STRATEGIES:
        lines.append(
            f"| {strategy} | {summary['expected_l1_recall'][strategy]} | "
            f"{summary['avg_context_tokens'][strategy]} | {summary['avg_selected_l1_count'][strategy]} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `full_context_l1` is the upper-bound evidence condition: it includes every source-side L1 object.",
            "- `rag_l1_lexical` is a normal lexical top-k baseline over source-side L1 content/evidence.",
            "- `optimization_v2_layered` uses the same evidence-first L1 ranking plus the effective L2/L3 topic surface.",
            "- Use this report to validate retrieval coverage and context-size tradeoffs before any paid answer-quality run.",
            "",
            "## Per Query",
            "",
            "| Query | Full recall | RAG recall | V2 recall | Full tokens | RAG tokens | V2 tokens |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["queries"]:
        strategies = row["strategies"]
        lines.append(
            f"| {row['query_id']} | "
            f"{strategies['full_context_l1']['expected_l1_recall']} | "
            f"{strategies['rag_l1_lexical']['expected_l1_recall']} | "
            f"{strategies['optimization_v2_layered']['expected_l1_recall']} | "
            f"{strategies['full_context_l1']['context_tokens']} | "
            f"{strategies['rag_l1_lexical']['context_tokens']} | "
            f"{strategies['optimization_v2_layered']['context_tokens']} |"
        )
    return "\n".join(lines)


def compare_systems_no_llm(
    *,
    run_root: Path | str,
    share_mem_root: Path | str,
    queries_path: Path | str,
    out_dir: Path | str,
    rag_top_k: int = 20,
    layered_top_k_l1: int = 80,
) -> dict[str, Any]:
    root = Path(run_root)
    out = ensure_optimization_output(out_dir)
    queries = _load_queries(queries_path)
    l1_index = build_l1_index(load_share_tree(share_mem_root))
    profile = _load_profile_for_run(root)
    effective_surface = load_effective_topic_surface(root)
    l2_index = effective_surface["l2_index"]
    l3_index = effective_surface["l3_index"]
    all_l1_rows = [dict(row, obj_id=obj_id) for obj_id, row in sorted(l1_index.items())]
    full_context = _l1_context(all_l1_rows)
    full_context_tokens = estimate_tokens(full_context)

    query_rows: list[dict[str, Any]] = []
    for query_row in queries:
        query = str(query_row.get("query", "") or "")
        query_id = str(query_row.get("query_id", "") or f"q{len(query_rows) + 1:03d}")
        expected = set(query_row.get("expected_obj_ids", []) or [])
        full_selected = set(l1_index)
        rag_selected_l1 = _rank_l1(query, l1_index, top_k=rag_top_k, profile=profile)
        rag_ids = {row["obj_id"] for row in rag_selected_l1}
        layered_selected_l1 = _rank_l1(query, l1_index, top_k=layered_top_k_l1, profile=profile)
        layered_ids = {row["obj_id"] for row in layered_selected_l1}
        rag_context_rows = [dict(l1_index[row["obj_id"]], obj_id=row["obj_id"]) for row in rag_selected_l1 if row["obj_id"] in l1_index]
        layered_context = _layered_context(
            selected_l1=layered_selected_l1,
            l1_index=l1_index,
            l2_index=l2_index,
            l3_index=l3_index,
        )
        query_rows.append(
            {
                "query_id": query_id,
                "query": query,
                "expected_obj_ids": sorted(expected),
                "strategies": {
                    "full_context_l1": {
                        "selected_l1_count": len(full_selected),
                        "matched_expected_obj_ids": sorted(expected & full_selected),
                        "expected_l1_recall": _recall(expected, full_selected),
                        "context_tokens": full_context_tokens,
                    },
                    "rag_l1_lexical": {
                        "selected_l1_count": len(rag_ids),
                        "matched_expected_obj_ids": sorted(expected & rag_ids),
                        "expected_l1_recall": _recall(expected, rag_ids),
                        "context_tokens": estimate_tokens(_l1_context(rag_context_rows)),
                        "top_k_l1": rag_top_k,
                    },
                    "optimization_v2_layered": {
                        "selected_l1_count": len(layered_ids),
                        "matched_expected_obj_ids": sorted(expected & layered_ids),
                        "expected_l1_recall": _recall(expected, layered_ids),
                        "context_tokens": estimate_tokens(layered_context),
                        "top_k_l1": layered_top_k_l1,
                        "selected_l2_label_count": len(
                            {
                                str(l2_index[obj_id].get("l2_label", ""))
                                for obj_id in layered_ids
                                if obj_id in l2_index and isinstance(l2_index[obj_id], dict)
                            }
                        ),
                        "selected_l3_label_count": len(
                            {
                                str(l3_index[obj_id].get("parent_l3_label", ""))
                                for obj_id in layered_ids
                                if obj_id in l3_index and isinstance(l3_index[obj_id], dict)
                            }
                        ),
                    },
                },
            }
        )

    per_strategy = {strategy: _strategy_metrics(query_rows, strategy) for strategy in STRATEGIES}
    summary = {
        "query_count": len(query_rows),
        "strategies": STRATEGIES,
        "expected_l1_recall": {strategy: per_strategy[strategy]["expected_l1_recall"] for strategy in STRATEGIES},
        "avg_context_tokens": {strategy: per_strategy[strategy]["avg_context_tokens"] for strategy in STRATEGIES},
        "avg_selected_l1_count": {strategy: per_strategy[strategy]["avg_selected_l1_count"] for strategy in STRATEGIES},
        "rag_top_k": rag_top_k,
        "layered_top_k_l1": layered_top_k_l1,
        "no_llm": True,
    }
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "share_mem_root": str(Path(share_mem_root).resolve()),
        "queries_path": str(Path(queries_path).resolve()),
        "summary": summary,
        "queries": query_rows,
    }
    write_json(out / "system_comparison_summary.json", report)
    write_text(out / "system_comparison_summary.md", _format_md(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare ICSI retrieval systems without LLM calls.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--share-mem-root", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--rag-top-k", type=int, default=20)
    parser.add_argument("--layered-top-k-l1", type=int, default=80)
    args = parser.parse_args()
    report = compare_systems_no_llm(
        run_root=args.run_root,
        share_mem_root=args.share_mem_root,
        queries_path=args.queries,
        out_dir=args.out,
        rag_top_k=args.rag_top_k,
        layered_top_k_l1=args.layered_top_k_l1,
    )
    print(
        "[optimization:v2] no-LLM system comparison complete: "
        f"queries={report['summary']['query_count']}"
    )


if __name__ == "__main__":
    main()
