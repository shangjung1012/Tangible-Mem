from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import memory_context
from memory_observatory.services.token_utils import estimate_tokens
from optimization.long_term_v2.io_utils import utc_now_iso, write_json, write_text
from optimization.long_term_v2.shadow_mode_qa_config import default_backend_specs


L1_RE = re.compile(r"\bL1-[A-Za-z0-9_\-]+")
L2_RE = re.compile(r"\bL2-[A-Za-z0-9_\-]+")
L3_RE = re.compile(r"\bL3-[A-Za-z0-9_\-]+")
BACKEND_ENV_KEYS = {
    "LONG_TERM_BACKEND",
    "OPTIMIZATION_V2_RUN_ROOT",
    "OPTIMIZATION_V2_RUNTIME_ROOT",
}


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _safe_query_id(row: dict[str, Any], index: int) -> str:
    raw = str(row.get("query_id") or row.get("question_id") or f"q{index:03d}")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")
    return safe or f"q{index:03d}"


def extract_trace_features(context: str) -> dict[str, Any]:
    text = str(context or "")
    return {
        "context_char_count": len(text),
        "estimated_context_tokens": estimate_tokens(text),
        "has_global_topic_map": "=== Global Topic Map ===" in text,
        "has_l1_evidence_seeds": "=== L1 Evidence Seeds ===" in text,
        "has_l2_evolution_context": "=== L2 / Child-L2 Evolution Context ===" in text,
        "has_retrieval_debug": "=== Retrieval Debug ===" in text,
        "l1_ids": _ordered_unique(L1_RE.findall(text)),
        "l2_ids": _ordered_unique(L2_RE.findall(text)),
        "l3_ids": _ordered_unique(L3_RE.findall(text)),
    }


@contextmanager
def temporary_backend_env(env: dict[str, str]) -> Iterator[None]:
    keys = BACKEND_ENV_KEYS | set(env)
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ.pop(key, None)
        for key, value in env.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _path_safe_resolver(resolver: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in resolver.items():
        output[key] = str(value) if isinstance(value, Path) else value
    return output


def run_backend_trace(
    *,
    query_id: str,
    query: str,
    backend_spec: dict[str, Any],
    max_context_chars: int = 16000,
    retrieval_mode: str = "lexical",
) -> dict[str, Any]:
    started = time.perf_counter()
    with temporary_backend_env(backend_spec.get("env", {})):
        resolver = memory_context.resolve_long_term_runtime_paths()
        try:
            context = memory_context.retrieve_long_term_context(
                query=query,
                api_key="",
                model_name="gemini-2.5-pro",
                max_context_chars=max_context_chars,
                use_llm_planner=False,
                retrieval_mode=retrieval_mode,
            )
            status = "ok"
            error = None
        except Exception as exc:
            context = ""
            status = "error"
            error = {"type": type(exc).__name__, "message": str(exc)}
    elapsed_ms = (time.perf_counter() - started) * 1000
    features = extract_trace_features(context)
    return {
        "query_id": query_id,
        "query": query,
        "backend_name": backend_spec["backend_name"],
        "expected_backend": backend_spec["expected_backend"],
        "resolved_backend": resolver.get("backend"),
        "fallback_reason": resolver.get("fallback_reason"),
        "resolver": _path_safe_resolver(resolver),
        "status": status,
        "error": error,
        "latency_ms": round(elapsed_ms, 3),
        "features": features,
        "context_preview": context[:2400],
        "context": context,
    }


def compare_backend_traces(canonical: dict[str, Any], shadow: dict[str, Any]) -> dict[str, Any]:
    canonical_features = canonical.get("features", {})
    shadow_features = shadow.get("features", {})
    canonical_l1 = set(canonical_features.get("l1_ids", []))
    shadow_l1 = set(shadow_features.get("l1_ids", []))
    overlap = sorted(canonical_l1 & shadow_l1)
    reason_codes: list[str] = []

    if canonical.get("status") != "ok":
        reason_codes.append("canonical_trace_error")
    if shadow.get("status") != "ok":
        reason_codes.append("shadow_trace_error")
    if shadow.get("resolved_backend") != "optimization_v2":
        reason_codes.append("shadow_backend_not_resolved")
    if not shadow_features.get("has_l1_evidence_seeds"):
        reason_codes.append("shadow_missing_l1_evidence")
    if not shadow_features.get("has_global_topic_map"):
        reason_codes.append("shadow_missing_global_topic_map")
    if not shadow_features.get("has_l2_evolution_context"):
        reason_codes.append("shadow_missing_l2_context")

    decision = "shadow_trace_ready" if not reason_codes else "needs_review"
    return {
        "decision": decision,
        "reason_codes": reason_codes,
        "l1_overlap_count": len(overlap),
        "l1_overlap_ids": overlap,
        "canonical_l1_count": len(canonical_l1),
        "shadow_l1_count": len(shadow_l1),
        "shadow_l2_count": len(set(shadow_features.get("l2_ids", []))),
        "shadow_l3_count": len(set(shadow_features.get("l3_ids", []))),
        "shadow_token_delta_vs_canonical": shadow_features.get("estimated_context_tokens", 0)
        - canonical_features.get("estimated_context_tokens", 0),
    }


def load_queries(path: Path | str, *, max_queries: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if max_queries is not None:
        rows = rows[:max_queries]
    return rows


def summarize_shadow_qa(query_results: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    ready_count = 0
    canonical_tokens: list[float] = []
    shadow_tokens: list[float] = []
    canonical_latency: list[float] = []
    shadow_latency: list[float] = []
    review_items: list[dict[str, Any]] = []

    for row in query_results:
        comparison = row.get("comparison", {})
        if comparison.get("decision") == "shadow_trace_ready":
            ready_count += 1
        else:
            review_items.append(
                {
                    "query_id": row.get("query_id"),
                    "query": row.get("query"),
                    "reason_codes": comparison.get("reason_codes", []),
                }
            )
        for code in comparison.get("reason_codes", []):
            reason_counts[code] = reason_counts.get(code, 0) + 1
        canonical = row.get("backends", {}).get("canonical", {})
        shadow = row.get("backends", {}).get("optimization_v2", {})
        canonical_tokens.append(float(canonical.get("features", {}).get("estimated_context_tokens", 0)))
        shadow_tokens.append(float(shadow.get("features", {}).get("estimated_context_tokens", 0)))
        canonical_latency.append(float(canonical.get("latency_ms", 0)))
        shadow_latency.append(float(shadow.get("latency_ms", 0)))

    needs_review = len(query_results) - ready_count
    return {
        "query_count": len(query_results),
        "shadow_trace_ready_count": ready_count,
        "needs_review_count": needs_review,
        "reason_code_counts": reason_counts,
        "average_context_tokens": {
            "canonical": _average(canonical_tokens),
            "optimization_v2": _average(shadow_tokens),
        },
        "average_latency_ms": {
            "canonical": _average(canonical_latency),
            "optimization_v2": _average(shadow_latency),
        },
        "review_items": review_items[:10],
        "decision": "shadow_qa_pass" if needs_review == 0 else "needs_review",
    }


def _trace_without_context(trace: dict[str, Any], *, context_path: str) -> dict[str, Any]:
    copy = dict(trace)
    copy.pop("context", None)
    copy["context_path"] = context_path
    return copy


def _write_summary_markdown(report: dict[str, Any], out: Path) -> None:
    summary = report["summary"]
    lines = [
        "# Optimization V2 Shadow-Mode QA",
        "",
        f"- decision: `{summary['decision']}`",
        f"- query count: `{summary['query_count']}`",
        f"- shadow trace ready: `{summary['shadow_trace_ready_count']}`",
        f"- needs review: `{summary['needs_review_count']}`",
        f"- optimization run root: `{report['optimization_run_root']}`",
        f"- raw run root: `{report['raw_run_root']}`",
        f"- retrieval mode: `{report['retrieval_mode']}`",
        f"- max context chars: `{report['max_context_chars']}`",
        f"- answer quality status: `{report['answer_quality_status']}`",
        "",
        "## Average Context Tokens",
        "",
        "| Backend | Tokens | Latency ms |",
        "|---|---:|---:|",
        f"| canonical | {summary['average_context_tokens']['canonical']} | {summary['average_latency_ms']['canonical']} |",
        f"| optimization_v2 | {summary['average_context_tokens']['optimization_v2']} | {summary['average_latency_ms']['optimization_v2']} |",
        "",
        "## Reason Codes",
        "",
    ]
    if summary["reason_code_counts"]:
        lines.extend(
            f"- `{code}`: {count}"
            for code, count in sorted(summary["reason_code_counts"].items())
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Review Items", ""])
    if summary["review_items"]:
        for item in summary["review_items"]:
            lines.append(
                f"- `{item.get('query_id')}`: {', '.join(item.get('reason_codes', []))}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This is shadow-mode QA only.",
            "- It does not modify `.env`, canonical `share_mem/`, or canonical `long_term/` artifacts.",
            "- `shadow_qa_pass` means the optimization backend can enter controlled shadow comparison; it is not canonical promotion.",
        ]
    )
    write_text(out / "summary.md", "\n".join(lines) + "\n")


def run_shadow_mode_qa(
    *,
    optimization_run_root: Path | str,
    queries_path: Path | str,
    out: Path | str,
    summary_out: Path | str,
    max_queries: int | None = None,
    max_context_chars: int = 16000,
    retrieval_mode: str = "lexical",
    generate_answers: bool = False,
    model: str = "gemini-2.5-pro",
    judge_model: str = "gemini-2.5-pro",
    max_answer_queries: int | None = None,
) -> dict[str, Any]:
    raw_root = Path(out)
    report_root = Path(summary_out)
    raw_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    backend_specs = default_backend_specs(optimization_run_root=optimization_run_root)
    queries = load_queries(queries_path, max_queries=max_queries)
    query_results: list[dict[str, Any]] = []

    for index, row in enumerate(queries, start=1):
        query_id = _safe_query_id(row, index)
        query = str(row.get("query") or row.get("question") or "").strip()
        contexts_dir = raw_root / "contexts" / query_id
        traces_dir = raw_root / "traces"
        contexts_dir.mkdir(parents=True, exist_ok=True)
        traces_dir.mkdir(parents=True, exist_ok=True)

        backend_results: dict[str, dict[str, Any]] = {}
        for backend_key in ("canonical", "optimization_v2"):
            trace = run_backend_trace(
                query_id=query_id,
                query=query,
                backend_spec=backend_specs[backend_key],
                max_context_chars=max_context_chars,
                retrieval_mode=retrieval_mode,
            )
            context_path = contexts_dir / f"{backend_key}.txt"
            write_text(context_path, trace.get("context", ""))
            backend_results[backend_key] = _trace_without_context(
                trace,
                context_path=str(context_path.resolve()),
            )

        comparison = compare_backend_traces(
            backend_results["canonical"],
            backend_results["optimization_v2"],
        )
        query_report = {
            "query_id": query_id,
            "query": query,
            "backends": backend_results,
            "comparison": comparison,
        }
        write_json(traces_dir / f"{query_id}.json", query_report)
        query_results.append(query_report)

    summary = summarize_shadow_qa(query_results)
    answer_quality_status = "not_run"
    if generate_answers:
        answer_quality_status = "deferred_generate_answers_not_implemented_in_trace_qa"
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "optimization_run_root": str(Path(optimization_run_root).resolve()),
        "queries_path": str(Path(queries_path).resolve()),
        "raw_run_root": str(raw_root.resolve()),
        "retrieval_mode": retrieval_mode,
        "max_context_chars": max_context_chars,
        "model": model,
        "judge_model": judge_model,
        "max_answer_queries": max_answer_queries,
        "answer_quality_status": answer_quality_status,
        "summary": summary,
        "query_results": query_results,
        "promotion_boundary": "shadow_qa_is_not_canonical_promotion",
        "canonical_mutation": False,
    }
    write_json(raw_root / "shadow_qa_report.json", report)
    compact = dict(report)
    compact["query_results"] = [
        {
            "query_id": row["query_id"],
            "query": row["query"],
            "comparison": row["comparison"],
            "backends": {
                key: {
                    "status": backend["status"],
                    "resolved_backend": backend["resolved_backend"],
                    "fallback_reason": backend.get("fallback_reason"),
                    "latency_ms": backend["latency_ms"],
                    "features": backend["features"],
                    "context_path": backend["context_path"],
                }
                for key, backend in row["backends"].items()
            },
        }
        for row in query_results
    ]
    write_json(report_root / "summary.json", compact)
    _write_summary_markdown(compact, report_root)
    return compact


def main() -> None:
    parser = argparse.ArgumentParser(description="Run canonical vs optimization v2 shadow-mode trace QA.")
    parser.add_argument("--optimization-run-root", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary-out", required=True)
    parser.add_argument("--max-queries", type=int, default=None)
    parser.add_argument("--max-context-chars", type=int, default=16000)
    parser.add_argument("--retrieval-mode", default="lexical")
    parser.add_argument("--generate-answers", action="store_true")
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument("--judge-model", default="gemini-2.5-pro")
    parser.add_argument("--max-answer-queries", type=int, default=None)
    args = parser.parse_args()
    report = run_shadow_mode_qa(
        optimization_run_root=args.optimization_run_root,
        queries_path=args.queries,
        out=args.out,
        summary_out=args.summary_out,
        max_queries=args.max_queries,
        max_context_chars=args.max_context_chars,
        retrieval_mode=args.retrieval_mode,
        generate_answers=args.generate_answers,
        model=args.model,
        judge_model=args.judge_model,
        max_answer_queries=args.max_answer_queries,
    )
    print(
        "[optimization:v2] shadow QA complete: "
        f"decision={report['summary']['decision']} "
        f"ready={report['summary']['shadow_trace_ready_count']} "
        f"needs_review={report['summary']['needs_review_count']}"
    )


if __name__ == "__main__":
    main()
