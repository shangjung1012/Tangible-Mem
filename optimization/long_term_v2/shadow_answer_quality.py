from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from google.genai import types

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from memory_observatory.services.token_utils import estimate_tokens, usage_metadata_to_tokens
from optimization.long_term_v2.evaluate_answer_quality import DIMENSIONS, LOWER_IS_BETTER
from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text
from share_mem.l1.gemini_clients import create_gemini_client
from share_mem.l1.io_utils import load_api_keys


BACKEND_TO_STRATEGY = {
    "canonical": "canonical_layered",
    "optimization_v2": "optimization_v2_deterministic",
}
TRANSIENT_ERROR_RE = re.compile(r"RESOURCE_EXHAUSTED|429|UNAVAILABLE|DEADLINE_EXCEEDED|503|500", re.IGNORECASE)
ANSWER_SYSTEM_PROMPT = (
    "You are a meeting-memory QA assistant. Answer only from the provided context. "
    "If the context is insufficient, say what is missing. Cite meeting ids, L1 obj_ids, "
    "or transcript line ranges whenever possible. Keep the answer concise and factual."
)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _average(values: list[float]) -> float:
    return round(sum(values) / max(len(values), 1), 4)


def _overall_from_dimensions(dimensions: dict[str, Any]) -> float:
    scores = []
    for dimension in DIMENSIONS:
        value = max(0.0, min(1.0, _safe_float(dimensions.get(dimension))))
        scores.append(1.0 - value if dimension in LOWER_IS_BETTER else value)
    return round(sum(scores) / max(len(scores), 1), 4)


def _normal_backend(value: Any) -> str:
    backend = str(value or "").strip()
    if backend in {"canonical_layered", "canonical"}:
        return "canonical"
    if backend in {"optimization_v2_deterministic", "optimization_v2"}:
        return "optimization_v2"
    return backend


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    dims = dict(row.get("dimensions") or row.get("scores") or {})
    for dimension in DIMENSIONS:
        dims[dimension] = max(0.0, min(1.0, _safe_float(dims.get(dimension))))
    overall = row.get("overall_score")
    if overall is None:
        overall = _overall_from_dimensions(dims)
    return {
        "query_id": str(row.get("query_id") or ""),
        "query": str(row.get("query") or ""),
        "backend": _normal_backend(row.get("backend") or row.get("strategy")),
        "answer": str(row.get("answer") or ""),
        "retrieved_context": str(row.get("retrieved_context") or ""),
        "overall_score": max(0.0, min(1.0, _safe_float(overall))),
        "dimensions": dims,
        "scoring_rationale": str(row.get("scoring_rationale") or ""),
        "token_usage": row.get("token_usage", {}) or {},
        "latency_ms": _safe_float(row.get("latency_ms")),
    }


def summarize_shadow_answer_quality(
    rows: list[dict[str, Any]],
    *,
    canonical_is_gold_baseline: bool = False,
    diagnostic_canonical_baseline: bool = False,
) -> dict[str, Any]:
    normalized = [_normalize_row(row) for row in rows if _normal_backend(row.get("backend") or row.get("strategy"))]
    query_ids = sorted({row["query_id"] for row in normalized if row["query_id"]})
    by_backend: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        by_backend.setdefault(row["backend"], []).append(row)

    backend_summary: dict[str, Any] = {}
    for backend, backend_rows in sorted(by_backend.items()):
        dim_values = {dimension: [] for dimension in DIMENSIONS}
        overall_values: list[float] = []
        token_values: list[float] = []
        latency_values: list[float] = []
        for row in backend_rows:
            overall_values.append(row["overall_score"])
            for dimension in DIMENSIONS:
                dim_values[dimension].append(_safe_float(row["dimensions"].get(dimension)))
            token_values.append(_safe_float((row.get("token_usage") or {}).get("estimated_context_tokens")))
            latency_values.append(_safe_float(row.get("latency_ms")))
        backend_summary[backend] = {
            "row_count": len(backend_rows),
            "average_overall_score": _average(overall_values),
            "average_dimensions": {dimension: _average(values) for dimension, values in dim_values.items()},
            "average_context_tokens": _average(token_values),
            "average_latency_ms": _average(latency_values),
        }

    canonical = backend_summary.get("canonical", {})
    optimization = backend_summary.get("optimization_v2", {})
    overall_delta = {
        "optimization_minus_canonical": round(
            _safe_float(optimization.get("average_overall_score")) - _safe_float(canonical.get("average_overall_score")),
            4,
        )
    }
    dimension_delta = {}
    for dimension in DIMENSIONS:
        dimension_delta[dimension] = round(
            _safe_float((optimization.get("average_dimensions") or {}).get(dimension))
            - _safe_float((canonical.get("average_dimensions") or {}).get(dimension)),
            4,
        )

    reasons: list[str] = []
    if not canonical:
        reasons.append("missing_canonical_rows")
    if not optimization:
        reasons.append("missing_optimization_rows")
    if canonical and optimization:
        if overall_delta["optimization_minus_canonical"] < -0.03:
            reasons.append("optimization_overall_below_canonical")
        if canonical_is_gold_baseline:
            if dimension_delta.get("source_traceability", 0.0) < -0.0001:
                reasons.append("optimization_traceability_below_canonical")
            if dimension_delta.get("hallucination_risk", 0.0) > 0.03:
                reasons.append("optimization_hallucination_risk_above_canonical")
        if diagnostic_canonical_baseline:
            if dimension_delta.get("evidence_grounding", 0.0) < -0.0001:
                reasons.append("optimization_grounding_below_diagnostic_canonical")
            if dimension_delta.get("topic_evolution", 0.0) < -0.0001:
                reasons.append("optimization_evolution_below_diagnostic_canonical")

    decision = "answer_quality_pass" if not reasons else "answer_quality_needs_review"
    return {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "query_count": len(query_ids),
        "row_count": len(normalized),
        "decision": decision,
        "reason_codes": reasons,
        "canonical_is_gold_baseline": canonical_is_gold_baseline,
        "diagnostic_canonical_baseline": diagnostic_canonical_baseline,
        "backend_summary": backend_summary,
        "overall_delta": overall_delta,
        "dimension_delta": dimension_delta,
    }


def _is_transient_error(exc: Exception) -> bool:
    return bool(TRANSIENT_ERROR_RE.search(f"{type(exc).__name__}: {exc}"))


def _with_retries(callable_obj, *, max_attempts: int, retry_wait_seconds: float):
    last_error: Exception | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            return callable_obj()
        except Exception as exc:  # pragma: no cover - external API retry path
            last_error = exc
            if attempt >= max_attempts or not _is_transient_error(exc):
                raise
            time.sleep(max(0.0, retry_wait_seconds) * attempt)
    if last_error:
        raise last_error
    raise RuntimeError("retry loop failed without exception")


def _answer_prompt(query: str, context: str) -> str:
    return f"Context:\n{context.strip()}\n\nQuestion:\n{query.strip()}\n\nAnswer:"


def _generate_answer(query: str, context: str, *, model: str, max_attempts: int, retry_wait_seconds: float) -> dict[str, Any]:
    client = create_gemini_client(load_api_keys())

    def call():
        return client.models.generate_content(
            model=model,
            contents=_answer_prompt(query, context),
            config=types.GenerateContentConfig(
                system_instruction=ANSWER_SYSTEM_PROMPT,
                temperature=0.2,
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode="NONE")
                ),
            ),
        )

    started = time.perf_counter()
    response = _with_retries(call, max_attempts=max_attempts, retry_wait_seconds=retry_wait_seconds)
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    usage = usage_metadata_to_tokens(response)
    answer = (response.text or "").strip()
    estimated_input = estimate_tokens(ANSWER_SYSTEM_PROMPT + "\n" + _answer_prompt(query, context))
    estimated_output = estimate_tokens(answer)
    return {
        "answer": answer,
        "latency_ms": elapsed,
        "token_usage": {
            "estimated_context_tokens": estimate_tokens(context),
            "actual_input_tokens": usage["actual_input_tokens"] if usage["actual_input_tokens"] is not None else estimated_input,
            "actual_output_tokens": usage["actual_output_tokens"] if usage["actual_output_tokens"] is not None else estimated_output,
            "actual_total_tokens": usage["actual_total_tokens"] if usage["actual_total_tokens"] is not None else estimated_input + estimated_output,
            "token_source": "actual_usage_metadata" if usage["actual_total_tokens"] is not None else "estimated",
        },
    }


def _parse_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)


def _score_prompt(*, query: str, backend: str, context: str, answer: str, canonical_answer: str | None = None) -> str:
    canonical_section = ""
    if canonical_answer and backend == "optimization_v2":
        canonical_section = f"\nCanonical baseline answer for reference:\n{canonical_answer}\n"
    return f"""
You are judging a meeting-memory answer in a canonical-vs-optimization shadow comparison.

Judge only from the provided retrieved context and the user question. A good answer should be
factually supported, cite source ids when available, and explain evolution only when the query asks
for it. Do not reward unsupported detail.

Question:
{query}

Backend:
{backend}
{canonical_section}
Retrieved context excerpt:
{context[:90000]}

Answer:
{answer}

Return only JSON with scores between 0 and 1:
{{
  "factual_correctness": 0.0,
  "evidence_grounding": 0.0,
  "topic_evolution": 0.0,
  "completeness": 0.0,
  "conciseness": 0.0,
  "hallucination_risk": 0.0,
  "source_traceability": 0.0,
  "scoring_rationale": "brief reason"
}}

Important: hallucination_risk is the only inverse dimension. A perfectly grounded
answer with no unsupported claims must use "hallucination_risk": 0.0. A severely
fabricated answer must use "hallucination_risk": 1.0.
""".strip()


def _score_answer(
    *,
    query: str,
    backend: str,
    context: str,
    answer: str,
    canonical_answer: str | None,
    model: str,
    max_attempts: int,
    retry_wait_seconds: float,
) -> dict[str, Any]:
    client = create_gemini_client(load_api_keys())
    prompt = _score_prompt(query=query, backend=backend, context=context, answer=answer, canonical_answer=canonical_answer)

    def call():
        return client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode="NONE")
                ),
            ),
        )

    started = time.perf_counter()
    response = _with_retries(call, max_attempts=max_attempts, retry_wait_seconds=retry_wait_seconds)
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    parsed = _parse_json(response.text or "")
    dimensions = {}
    for dimension in DIMENSIONS:
        dimensions[dimension] = max(0.0, min(1.0, _safe_float(parsed.get(dimension))))
    return {
        "dimensions": dimensions,
        "overall_score": _overall_from_dimensions(dimensions),
        "scoring_rationale": str(parsed.get("scoring_rationale") or ""),
        "judge_latency_ms": elapsed,
        "judge_usage": usage_metadata_to_tokens(response),
        "judge_raw": response.text or "",
    }


def _load_context(path: str) -> str:
    if not path:
        return ""
    source = Path(path)
    if not source.exists():
        return ""
    return source.read_text(encoding="utf-8", errors="replace")


def _trace_rows_from_shadow_report(shadow_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for query in shadow_report.get("query_results", []) or []:
        for backend in ("canonical", "optimization_v2"):
            trace = ((query.get("backends") or {}).get(backend) or {})
            context = _load_context(str(trace.get("context_path") or ""))
            rows.append(
                {
                    "query_id": query.get("query_id", ""),
                    "query": query.get("query", ""),
                    "backend": backend,
                    "retrieved_context": context,
                    "trace": trace,
                }
            )
    return rows


def run_shadow_answer_quality(
    *,
    shadow_qa_report: Path | str,
    out: Path | str,
    raw_out: Path | str | None = None,
    canonical_is_gold_baseline: bool = False,
    diagnostic_canonical_baseline: bool = False,
    generate_answers: bool = False,
    model: str = "gemini-2.5-pro",
    judge_model: str = "gemini-2.5-pro",
    max_attempts: int = 4,
    retry_wait_seconds: float = 30.0,
) -> dict[str, Any]:
    report_root = ensure_optimization_output(out)
    raw_root = ensure_optimization_output(raw_out or report_root)
    shadow_report = load_json(shadow_qa_report)
    trace_rows = _trace_rows_from_shadow_report(shadow_report)
    if not generate_answers:
        summary = {
            "schema_version": 1,
            "generated_at_utc": utc_now_iso(),
            "decision": "blocked_missing_generated_answers",
            "reason_codes": ["generate_answers_not_requested"],
            "shadow_qa_report": str(Path(shadow_qa_report).resolve()),
            "query_count": len({row["query_id"] for row in trace_rows}),
            "row_count": len(trace_rows),
            "canonical_is_gold_baseline": canonical_is_gold_baseline,
            "diagnostic_canonical_baseline": diagnostic_canonical_baseline,
        }
        write_json(report_root / "summary.json", summary)
        write_text(report_root / "summary.md", _format_summary_md(summary))
        return summary

    scored_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    by_query_backend = {(row["query_id"], row["backend"]): row for row in trace_rows}
    query_ids = sorted({row["query_id"] for row in trace_rows})
    for query_id in query_ids:
        canonical_answer = None
        for backend in ("canonical", "optimization_v2"):
            trace_row = by_query_backend.get((query_id, backend))
            if not trace_row:
                continue
            try:
                answer_result = _generate_answer(
                    str(trace_row.get("query", "")),
                    str(trace_row.get("retrieved_context", "")),
                    model=model,
                    max_attempts=max_attempts,
                    retry_wait_seconds=retry_wait_seconds,
                )
                if backend == "canonical":
                    canonical_answer = answer_result["answer"]
                score_result = _score_answer(
                    query=str(trace_row.get("query", "")),
                    backend=backend,
                    context=str(trace_row.get("retrieved_context", "")),
                    answer=answer_result["answer"],
                    canonical_answer=canonical_answer,
                    model=judge_model,
                    max_attempts=max_attempts,
                    retry_wait_seconds=retry_wait_seconds,
                )
                row = {
                    "query_id": query_id,
                    "query": trace_row.get("query", ""),
                    "backend": backend,
                    "strategy": BACKEND_TO_STRATEGY.get(backend, backend),
                    "answer": answer_result["answer"],
                    "retrieved_context": trace_row.get("retrieved_context", ""),
                    "dimensions": score_result["dimensions"],
                    "overall_score": score_result["overall_score"],
                    "scoring_rationale": score_result["scoring_rationale"],
                    "token_usage": answer_result["token_usage"],
                    "latency_ms": answer_result["latency_ms"],
                    "judge_latency_ms": score_result["judge_latency_ms"],
                    "judge_usage": score_result["judge_usage"],
                }
                scored_rows.append(row)
                write_text(raw_root / "answers" / query_id / f"{backend}.txt", answer_result["answer"])
                write_text(raw_root / "contexts" / query_id / f"{backend}.txt", str(trace_row.get("retrieved_context", "")))
                write_json(raw_root / "scores" / query_id / f"{backend}.json", row | {"retrieved_context": ""})
                write_json(raw_root / "scored_rows_partial.json", {"rows": scored_rows})
            except Exception as exc:  # pragma: no cover - external API failure path
                skipped_rows.append({"query_id": query_id, "backend": backend, "error": f"{type(exc).__name__}: {exc}"})
                write_json(raw_root / "skipped_rows_partial.json", {"rows": skipped_rows})

    write_json(raw_root / "scored_rows.json", {"rows": scored_rows})
    write_json(raw_root / "skipped_rows.json", {"rows": skipped_rows})
    summary = summarize_shadow_answer_quality(
        scored_rows,
        canonical_is_gold_baseline=canonical_is_gold_baseline,
        diagnostic_canonical_baseline=diagnostic_canonical_baseline,
    )
    summary.update(
        {
            "shadow_qa_report": str(Path(shadow_qa_report).resolve()),
            "raw_run_root": str(raw_root.resolve()),
            "model": model,
            "judge_model": judge_model,
            "skipped_row_count": len(skipped_rows),
        }
    )
    write_json(report_root / "summary.json", summary)
    write_text(report_root / "summary.md", _format_summary_md(summary))
    return summary


def _format_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# Optimization V2 Shadow Answer Quality",
        "",
        f"- decision: `{summary.get('decision')}`",
        f"- query count: `{summary.get('query_count')}`",
        f"- row count: `{summary.get('row_count')}`",
        f"- reason codes: {', '.join(summary.get('reason_codes', [])) or 'none'}",
        f"- raw run root: `{summary.get('raw_run_root', '')}`",
        "",
        "## Backend Summary",
        "",
        "| Backend | Overall | Traceability | Hallucination Risk | Context Tokens |",
        "|---|---:|---:|---:|---:|",
    ]
    for backend, row in sorted((summary.get("backend_summary") or {}).items()):
        dims = row.get("average_dimensions", {}) or {}
        lines.append(
            f"| {backend} | {row.get('average_overall_score')} | "
            f"{dims.get('source_traceability')} | {dims.get('hallucination_risk')} | "
            f"{row.get('average_context_tokens')} |"
        )
    lines.extend(
        [
            "",
            "## Delta",
            "",
            f"- optimization overall minus canonical: `{(summary.get('overall_delta') or {}).get('optimization_minus_canonical')}`",
            f"- dimension delta: `{summary.get('dimension_delta', {})}`",
            "",
            "## Boundary",
            "",
            "- This report compares shadow traces only.",
            "- It does not modify `.env`, canonical `share_mem/`, or canonical `long_term/` artifacts.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run canonical-vs-optimization shadow answer quality.")
    parser.add_argument("--shadow-qa-report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--raw-out", default=None)
    parser.add_argument("--canonical-is-gold-baseline", action="store_true")
    parser.add_argument("--diagnostic-canonical-baseline", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--generate-answers", action="store_true")
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument("--judge-model", default="gemini-2.5-pro")
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--retry-wait-seconds", type=float, default=30.0)
    args = parser.parse_args()
    summary = run_shadow_answer_quality(
        shadow_qa_report=args.shadow_qa_report,
        out=args.out,
        raw_out=args.raw_out,
        canonical_is_gold_baseline=args.canonical_is_gold_baseline,
        diagnostic_canonical_baseline=args.diagnostic_canonical_baseline,
        generate_answers=args.generate_answers and not args.no_llm,
        model=args.model,
        judge_model=args.judge_model,
        max_attempts=args.max_attempts,
        retry_wait_seconds=args.retry_wait_seconds,
    )
    print(f"[optimization:v2] shadow answer quality complete: decision={summary['decision']}")


if __name__ == "__main__":
    main()
