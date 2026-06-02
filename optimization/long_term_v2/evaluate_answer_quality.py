from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, utc_now_iso, write_json, write_text


DIMENSIONS = [
    "factual_correctness",
    "evidence_grounding",
    "topic_evolution",
    "completeness",
    "conciseness",
    "hallucination_risk",
    "source_traceability",
]
LOWER_IS_BETTER = {"hallucination_risk"}
V2_STRATEGIES = ["optimization_v2_deterministic", "optimization_v2_llm_assisted"]
METHOD_TO_STRATEGY = {
    "full context": "full_context",
    "full transcript": "full_context",
    "rag": "rag_baseline",
    "rag baseline": "rag_baseline",
    "traditional rag": "rag_baseline",
    "structured": "canonical_layered",
    "canonical layered": "canonical_layered",
    "layered memory": "canonical_layered",
    "optimization v2 deterministic": "optimization_v2_deterministic",
    "optimization_v2_deterministic": "optimization_v2_deterministic",
    "optimization v2 llm assisted": "optimization_v2_llm_assisted",
    "optimization_v2_llm_assisted": "optimization_v2_llm_assisted",
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_rows(path: Path | str) -> list[dict[str, Any]]:
    source = Path(path)
    if source.suffix.lower() == ".csv":
        with source.open(encoding="utf-8-sig", newline="") as handle:
            return [_row_from_csv(row) for row in csv.DictReader(handle)]
    if source.suffix.lower() == ".jsonl":
        rows = []
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
    payload = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return list(payload.get("rows", []) or payload.get("items", []) or [])


def _row_from_csv(row: dict[str, str]) -> dict[str, Any]:
    strategy = row.get("strategy") or row.get("method") or ""
    strategy = METHOD_TO_STRATEGY.get(strategy.strip().lower(), strategy)
    hallucination_control = _safe_float(row.get("hallucination_control_score"))
    topic_evolution = row.get("topic_evolution")
    if topic_evolution is None:
        topic_evolution = row.get("temporal_evolution_score") or row.get("knowledge_update_score")
    scores = {
        "factual_correctness": row.get("factual_correctness") or row.get("factuality_score"),
        "evidence_grounding": row.get("evidence_grounding") or row.get("evidence_grounding_score"),
        "topic_evolution": topic_evolution,
        "completeness": row.get("completeness") or row.get("completeness_score"),
        "conciseness": row.get("conciseness") or row.get("conciseness_score") or row.get("context_specificity_score"),
        "hallucination_risk": row.get("hallucination_risk") or (1.0 - hallucination_control if hallucination_control else ""),
        "source_traceability": row.get("source_traceability") or row.get("evidence_grounding_score"),
    }
    return {
        "query_id": row.get("query_id") or row.get("question_id"),
        "query": row.get("query") or row.get("question"),
        "strategy": strategy,
        "answer": row.get("answer") or row.get("response"),
        "retrieved_context": row.get("retrieved_context") or "",
        "scores": scores,
        "scoring_rationale": row.get("scoring_rationale") or row.get("judge_notes") or "",
        "token_usage": {
            "estimated_context_tokens": row.get("estimated_context_tokens") or "",
            "actual_input_tokens": row.get("judge_input_tokens") or "",
            "actual_output_tokens": row.get("judge_output_tokens") or "",
            "actual_total_tokens": row.get("judge_total_tokens") or "",
            "token_source": row.get("judge_token_source") or "",
        },
        "latency_ms": row.get("latency_ms") or "",
    }


def _normalized_scores(row: dict[str, Any]) -> dict[str, float]:
    scores = row.get("scores", {}) or {}
    normalized = {}
    for dimension in DIMENSIONS:
        value = max(0.0, min(1.0, _safe_float(scores.get(dimension))))
        normalized[dimension] = value
    return normalized


def _overall_score(scores: dict[str, float]) -> float:
    comparable = []
    for dimension, value in scores.items():
        comparable.append(1.0 - value if dimension in LOWER_IS_BETTER else value)
    return round(sum(comparable) / max(len(comparable), 1), 4)


def _average(values: list[float]) -> float:
    return round(sum(values) / max(len(values), 1), 4)


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strategy = str(row.get("strategy", "") or "")
        if strategy:
            by_strategy[strategy].append(row)
    summary: dict[str, Any] = {}
    for strategy, strategy_rows in sorted(by_strategy.items()):
        dimension_values: dict[str, list[float]] = {dimension: [] for dimension in DIMENSIONS}
        overall_values: list[float] = []
        context_tokens: list[float] = []
        latencies: list[float] = []
        for row in strategy_rows:
            scores = _normalized_scores(row)
            for dimension, value in scores.items():
                dimension_values[dimension].append(value)
            overall_values.append(_overall_score(scores))
            token_usage = row.get("token_usage", {}) or {}
            context_tokens.append(_safe_float(token_usage.get("estimated_context_tokens")))
            latencies.append(_safe_float(row.get("latency_ms")))
        summary[strategy] = {
            "query_count": len(strategy_rows),
            "average_overall_score": _average(overall_values),
            "average_dimensions": {
                dimension: _average(values)
                for dimension, values in dimension_values.items()
            },
            "average_context_tokens": _average(context_tokens),
            "average_latency_ms": _average(latencies),
        }
    return summary


def _best_v2(summary: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    candidates = [
        (strategy, summary[strategy])
        for strategy in V2_STRATEGIES
        if strategy in summary
    ]
    if not candidates:
        return "", {}
    candidates.sort(key=lambda item: item[1].get("average_overall_score", 0.0), reverse=True)
    return candidates[0]


def _gate_status(summary: dict[str, Any]) -> tuple[str, list[str]]:
    best_name, best_v2 = _best_v2(summary)
    reasons: list[str] = []
    if not best_v2:
        return "warning", ["missing_optimization_v2_strategy"]
    canonical = summary.get("canonical_layered")
    rag = summary.get("rag_baseline")
    full = summary.get("full_context")
    if not canonical:
        reasons.append("missing_canonical_layered")
    if not rag:
        reasons.append("missing_rag_baseline")
    if not full:
        reasons.append("missing_full_context")
    if reasons:
        return "warning", reasons
    best_dims = best_v2.get("average_dimensions", {}) or {}
    canonical_score = _safe_float(canonical.get("average_overall_score"))
    if _safe_float(best_v2.get("average_overall_score")) < canonical_score:
        reasons.append(f"{best_name}_below_canonical_layered")
    if _safe_float(best_dims.get("topic_evolution")) < _safe_float((rag.get("average_dimensions", {}) or {}).get("topic_evolution")):
        reasons.append(f"{best_name}_topic_evolution_below_rag")
    if _safe_float(best_dims.get("source_traceability")) <= _safe_float((full.get("average_dimensions", {}) or {}).get("source_traceability")):
        reasons.append(f"{best_name}_source_traceability_not_above_full_context")
    if _safe_float(best_dims.get("hallucination_risk")) > _safe_float((full.get("average_dimensions", {}) or {}).get("hallucination_risk")):
        reasons.append(f"{best_name}_hallucination_risk_above_full_context")
    return ("pass" if not reasons else "fail", reasons)


def evaluate_answer_quality(
    *,
    run_root: Path | str,
    scored_rows: list[dict[str, Any]] | None = None,
    scored_path: Path | str | None = None,
) -> dict[str, Any]:
    root = ensure_optimization_output(run_root)
    rows = scored_rows if scored_rows is not None else _load_rows(scored_path) if scored_path else []
    normalized_rows: list[dict[str, Any]] = []
    failure_cases: list[dict[str, Any]] = []
    for row in rows:
        scores = _normalized_scores(row)
        normalized = {
            "query_id": row.get("query_id", ""),
            "query": row.get("query", ""),
            "strategy": row.get("strategy", ""),
            "answer": row.get("answer", ""),
            "retrieved_context": row.get("retrieved_context", ""),
            "scores": scores,
            "overall_score": _overall_score(scores),
            "scoring_rationale": row.get("scoring_rationale", ""),
            "token_usage": row.get("token_usage", {}) or {},
            "latency_ms": _safe_float(row.get("latency_ms")),
        }
        normalized_rows.append(normalized)
        if normalized["overall_score"] < 0.65 or scores["hallucination_risk"] > 0.35:
            failure_cases.append(normalized)
    summary = _summarize(normalized_rows)
    status, gate_reasons = _gate_status(summary)
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "status": status,
        "gate_reasons": gate_reasons,
        "dimensions": DIMENSIONS,
        "summary": summary,
        "rows": normalized_rows,
        "failure_case_count": len(failure_cases),
    }
    out = root / "answer_quality"
    write_json(out / "answer_quality_report.json", report)
    write_json(out / "failure_cases.json", {"items": failure_cases})
    lines = [
        "# Optimization v2 Answer Quality Report",
        "",
        f"- status: `{status}`",
        f"- gate reasons: {', '.join(gate_reasons) if gate_reasons else 'none'}",
        f"- scored rows: {len(normalized_rows)}",
        "",
        "## Strategy Summary",
    ]
    for strategy, row in summary.items():
        lines.append(f"- {strategy}: overall={row['average_overall_score']} traceability={row['average_dimensions']['source_traceability']}")
    write_text(out / "answer_quality_report.md", "\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate optimization v2 answer-quality scores.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--scores", required=True, help="JSON or JSONL scored answer rows.")
    args = parser.parse_args()
    report = evaluate_answer_quality(run_root=args.run_root, scored_path=args.scores)
    print(f"[optimization:v2] answer quality complete: status={report['status']}")


if __name__ == "__main__":
    main()
