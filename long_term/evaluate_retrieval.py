"""Lightweight parameter evaluation for long-term layered retrieval."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from recall import format_recall_for_prompt, recall
from recall_planner import plan_recall
from embedder import EmbedCache
from share_mem.store import load_share_tree

DEFAULT_QUERIES_PATH = Path(__file__).resolve().parent / "eval" / "long_term_retrieval_queries.jsonl"
DEFAULT_OUT = Path(__file__).resolve().parent / "eval"


def _load_queries(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if isinstance(data, dict) and str(data.get("query", "")).strip():
            rows.append(data)
    return rows


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ids(rows: list[dict[str, Any]], key: str) -> set[str]:
    return {str(row.get(key, "") or "") for row in rows if str(row.get(key, "") or "").strip()}


def _parse_csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in str(value).split(",") if item.strip()]


def _parse_csv_floats(value: str) -> list[float]:
    return [float(item.strip()) for item in str(value).split(",") if item.strip()]


def _parse_csv_bools(value: str) -> list[bool]:
    mapping = {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}
    output: list[bool] = []
    for item in str(value).split(","):
        key = item.strip().lower()
        if key:
            output.append(mapping[key])
    return output


def _default_api_key() -> str | list[str]:
    try:
        from share_mem.l1.io_utils import load_api_keys

        return load_api_keys()
    except Exception:
        return os.getenv("GEMINI_API_KEY", "")


def _heuristic_plan(query: str) -> dict[str, Any]:
    tokens = [
        token
        for token in re_split_query(query)
        if len(token) >= 2
    ]
    return {
        "complexity": "simple",
        "reasoning": "offline deterministic retrieval evaluation plan",
        "search_targets": ["long_term_l1", "long_term_l2", "long_term_l3"],
        "keywords": tokens[:12],
        "time_range_hint": "",
    }


def re_split_query(query: str) -> list[str]:
    import re

    pieces = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*|[\u4e00-\u9fff]{2,}", str(query or ""))
    return [piece.lower().replace("_", "-") for piece in pieces if piece.strip()]


def run_retrieval_once(
    *,
    query: str,
    tree: dict[str, Any],
    api_key: str | list[str],
    model_name: str,
    params: dict[str, Any],
    planner_model_name: str | None = None,
    embed_cache: EmbedCache | None = None,
    use_llm_planner: bool = True,
    retrieval_mode: str = "semantic",
) -> dict[str, Any]:
    effective_planner_model = planner_model_name or os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash")
    plan = (
        plan_recall(query=query, api_key=api_key, model_name=effective_planner_model)
        if use_llm_planner
        else _heuristic_plan(query)
    )
    plan["search_targets"] = ["long_term_l1", "long_term_l2", "long_term_l3"]
    recall_params = dict(params)
    recall_params.setdefault(
        "max_relevant_l2_summaries",
        int(recall_params.get("max_expanded_l2_topics", 2) or 2),
    )
    return recall(
        query=query,
        plan=plan,
        tree=tree,
        api_key=api_key,
        model_name=model_name,
        include_retrieval_debug=True,
        embed_cache=embed_cache,
        retrieval_mode=retrieval_mode,
        **recall_params,
    )


def _score_query_result(query_row: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    strict_obj_ids = {
        str(x)
        for x in _as_list(query_row.get("strict_gold_obj_ids", query_row.get("expected_obj_ids")))
    }
    acceptable_obj_ids = {str(x) for x in _as_list(query_row.get("acceptable_obj_ids"))}
    expected_obj_ids = {str(x) for x in _as_list(query_row.get("expected_obj_ids"))}
    scoring_obj_ids = expected_obj_ids | acceptable_obj_ids
    if not scoring_obj_ids:
        scoring_obj_ids = strict_obj_ids
    expected_l2_ids = {str(x) for x in _as_list(query_row.get("expected_l2_ids"))}
    expected_l3_ids = {str(x) for x in _as_list(query_row.get("expected_l3_ids"))}
    l1_ids = _ids(_as_list(result.get("long_term_l1")), "obj_id")
    l2_rows = _as_list(result.get("long_term_l2"))
    l2_ids = _ids(l2_rows, "l2_id") | _ids(l2_rows, "promoted_from_l2_id")
    l3_ids = _ids(_as_list(result.get("long_term_l3")), "l3_id")
    debug = result.get("retrieval_debug", {}) if isinstance(result.get("retrieval_debug"), dict) else {}
    prompt = format_recall_for_prompt(result, include_debug=False)
    obj_recall = (
        len(scoring_obj_ids & l1_ids) / len(scoring_obj_ids)
        if scoring_obj_ids
        else 1.0
    )
    strict_recall = (
        len(strict_obj_ids & l1_ids) / len(strict_obj_ids)
        if strict_obj_ids
        else 1.0
    )
    acceptable_recall = (
        len(acceptable_obj_ids & l1_ids) / len(acceptable_obj_ids)
        if acceptable_obj_ids
        else obj_recall
    )
    return {
        "query": query_row.get("query", ""),
        "expected_obj_recall_at_context": round(obj_recall, 4),
        "strict_obj_recall_at_context": round(strict_recall, 4),
        "acceptable_obj_recall_at_context": round(acceptable_recall, 4),
        "expected_l2_hit": not expected_l2_ids or bool(expected_l2_ids & l2_ids),
        "expected_l3_hit": not expected_l3_ids or bool(expected_l3_ids & l3_ids),
        "selected_obj_ids": sorted(l1_ids),
        "selected_l2_ids": sorted(l2_ids),
        "selected_l3_ids": sorted(l3_ids),
        "context_char_count": len(prompt),
        "selected_l1_count": int(debug.get("selected_l1_count", len(l1_ids)) or 0),
        "selected_l2_count": int(debug.get("selected_l2_count", 0) or 0),
        "selected_child_l2_count": int(debug.get("selected_child_l2_count", 0) or 0),
        "omitted_event_count": int(debug.get("omitted_event_count", 0) or 0),
        "noise_l2_count": len(l2_ids - expected_l2_ids) if expected_l2_ids else 0,
        "whether_large_l2_was_expanded_without_child_split": bool(
            debug.get("large_l2_expanded_without_child_split", False)
        ),
        "prompt_budget_pass": len(prompt) <= 4000,
        "notes": query_row.get("notes", ""),
    }


def _grid_rows(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(grid)
    return [
        dict(zip(keys, values, strict=True))
        for values in itertools.product(*(grid[key] for key in keys))
    ]


def evaluate_retrieval_grid(
    *,
    queries_path: Path | str = DEFAULT_QUERIES_PATH,
    out: Path | str = DEFAULT_OUT,
    api_key: str | list[str] | None = None,
    model_name: str = "gemini-2.5-pro",
    planner_model_name: str | None = None,
    share_mem_root: Path | str = REPO_ROOT / "share_mem",
    grid: dict[str, list[Any]] | None = None,
    use_llm_planner: bool = True,
    retrieval_mode: str = "semantic",
) -> dict[str, Any]:
    query_rows = _load_queries(Path(queries_path))
    tree = load_share_tree(Path(share_mem_root))
    api_key = api_key if api_key is not None else _default_api_key()
    grid = grid or {
        "top_k_raw": [20, 30],
        "max_l1_seeds_for_prompt": [5, 8],
        "max_events_per_l2": [2],
        "max_events_per_child_l2": [2, 4],
        "max_expanded_l2_topics": [1, 2],
        "max_global_topic_map_chars": [300],
        "max_event_chars": [100],
        "topic_size_penalty": [0.05, 0.10],
        "prefer_materialized_l3": [True],
    }
    runs: list[dict[str, Any]] = []
    embed_cache = EmbedCache()
    for params in _grid_rows(grid):
        per_query: list[dict[str, Any]] = []
        for query_row in query_rows:
            result = run_retrieval_once(
                query=str(query_row["query"]),
                tree=tree,
                api_key=api_key or "",
                model_name=model_name,
                planner_model_name=planner_model_name,
                params=params,
                embed_cache=embed_cache,
                use_llm_planner=use_llm_planner,
                retrieval_mode=retrieval_mode,
            )
            per_query.append(_score_query_result(query_row, result))
        runs.append(
            {
                "params": params,
                "expected_obj_recall_at_context": round(
                    sum(row["expected_obj_recall_at_context"] for row in per_query)
                    / max(1, len(per_query)),
                    4,
                ),
                "strict_obj_recall_at_context": round(
                    sum(row["strict_obj_recall_at_context"] for row in per_query)
                    / max(1, len(per_query)),
                    4,
                ),
                "acceptable_obj_recall_at_context": round(
                    sum(row["acceptable_obj_recall_at_context"] for row in per_query)
                    / max(1, len(per_query)),
                    4,
                ),
                "expected_l2_hit_rate": round(
                    sum(1 for row in per_query if row["expected_l2_hit"]) / max(1, len(per_query)),
                    4,
                ),
                "expected_l3_hit_rate": round(
                    sum(1 for row in per_query if row["expected_l3_hit"]) / max(1, len(per_query)),
                    4,
                ),
                "avg_context_char_count": round(
                    sum(row["context_char_count"] for row in per_query) / max(1, len(per_query)),
                    2,
                ),
                "prompt_budget_pass_rate": round(
                    sum(1 for row in per_query if row["prompt_budget_pass"]) / max(1, len(per_query)),
                    4,
                ),
                "queries": per_query,
            }
        )
    embed_cache.save()
    runs.sort(
        key=lambda row: (
            -float(row["expected_obj_recall_at_context"]),
            -float(row["prompt_budget_pass_rate"]),
            -float(row["expected_l2_hit_rate"]),
            -float(row["expected_l3_hit_rate"]),
            float(row["avg_context_char_count"]),
        )
    )
    report = {
        "schema_version": 1,
        "query_count": len(query_rows),
        "run_count": len(runs),
        "retrieval_mode": retrieval_mode,
        "use_llm_planner": use_llm_planner,
        "model": model_name,
        "planner_model": planner_model_name or os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash"),
        "runs": runs,
        "best_params": runs[0]["params"] if runs else {},
    }
    out_path = Path(out)
    _write_json(out_path / "retrieval_eval_report.json", report)
    (out_path / "retrieval_eval_report.md").write_text(_markdown_report(report), encoding="utf-8")
    return report


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Long-Term Retrieval Eval Report",
        "",
        f"- Query count: {report['query_count']}",
        f"- Run count: {report['run_count']}",
        f"- Best params: `{json.dumps(report.get('best_params', {}), ensure_ascii=False)}`",
        "",
        "## Top Runs",
    ]
    for run in report.get("runs", [])[:10]:
        lines.append(
            "- "
            f"obj_recall={run['expected_obj_recall_at_context']} "
            f"strict_obj={run.get('strict_obj_recall_at_context', 0)} "
            f"acceptable_obj={run.get('acceptable_obj_recall_at_context', 0)} "
            f"l2_hit={run['expected_l2_hit_rate']} "
            f"l3_hit={run['expected_l3_hit_rate']} "
            f"avg_chars={run['avg_context_char_count']} "
            f"budget={run['prompt_budget_pass_rate']} "
            f"params=`{json.dumps(run['params'], ensure_ascii=False)}`"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate long-term retrieval parameters.")
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--share-mem-root", default=str(REPO_ROOT / "share_mem"))
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-2.5-pro"))
    parser.add_argument(
        "--planner-model",
        default=os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash"),
        help="Model used only for LLM recall planning. Recall scoring still uses --model.",
    )
    parser.add_argument("--top-k-raw", default="20,30")
    parser.add_argument("--max-l1-seeds-for-prompt", default="5,8")
    parser.add_argument("--max-events-per-l2", default="2")
    parser.add_argument("--max-events-per-child-l2", default="2,4")
    parser.add_argument("--max-expanded-l2-topics", default="1,2")
    parser.add_argument("--max-global-topic-map-chars", default="300")
    parser.add_argument("--max-event-chars", default="100")
    parser.add_argument("--topic-size-penalty", default="0.05,0.10")
    parser.add_argument("--prefer-materialized-l3", default="true")
    parser.add_argument("--retrieval-mode", choices=["lexical", "semantic"], default="lexical")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Use heuristic planning. This is the default; retained for compatibility.",
    )
    parser.add_argument(
        "--use-llm-planner",
        action="store_true",
        help="Opt in to Gemini recall planning. With --retrieval-mode lexical, only the planner calls Gemini.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    grid = {
        "top_k_raw": _parse_csv_ints(args.top_k_raw),
        "max_l1_seeds_for_prompt": _parse_csv_ints(args.max_l1_seeds_for_prompt),
        "max_events_per_l2": _parse_csv_ints(args.max_events_per_l2),
        "max_events_per_child_l2": _parse_csv_ints(args.max_events_per_child_l2),
        "max_expanded_l2_topics": _parse_csv_ints(args.max_expanded_l2_topics),
        "max_global_topic_map_chars": _parse_csv_ints(args.max_global_topic_map_chars),
        "max_event_chars": _parse_csv_ints(args.max_event_chars),
        "topic_size_penalty": _parse_csv_floats(args.topic_size_penalty),
        "prefer_materialized_l3": _parse_csv_bools(args.prefer_materialized_l3),
    }
    report = evaluate_retrieval_grid(
        queries_path=args.queries,
        out=args.out,
        share_mem_root=args.share_mem_root,
        model_name=args.model,
        planner_model_name=args.planner_model,
        grid=grid,
        use_llm_planner=bool(args.use_llm_planner and not args.no_llm),
        retrieval_mode=args.retrieval_mode,
    )
    print(
        "[long_term] retrieval eval complete: "
        f"{report['query_count']} queries, {report['run_count']} parameter runs"
    )
    print(f"Report: {Path(args.out) / 'retrieval_eval_report.json'}")


if __name__ == "__main__":
    main()
