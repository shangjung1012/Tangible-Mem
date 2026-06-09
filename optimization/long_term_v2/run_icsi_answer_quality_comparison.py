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
from optimization.long_term_v2.evaluate_answer_quality import evaluate_answer_quality
from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.run_answer_quality_eval import _build_v2_context
from share_mem.l1.gemini_clients import create_gemini_client
from share_mem.l1.io_utils import load_api_keys


ANSWER_SYSTEM_PROMPT = (
    "You are a meeting-memory QA assistant. Answer only from the provided context. "
    "If the context is insufficient, say what is missing. Cite meeting ids, L1 obj_ids, "
    "or transcript line ranges whenever possible. Keep the answer concise and factual."
)
STRATEGY_NAMES = {
    "full_context": "full_context",
    "rag_baseline": "rag_baseline",
    "optimization_v2": "optimization_v2_deterministic",
}

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.IGNORECASE)
TRANSIENT_ERROR_RE = re.compile(r"RESOURCE_EXHAUSTED|429|UNAVAILABLE|DEADLINE_EXCEEDED|503|500", re.IGNORECASE)


def _load_jsonl(path: Path | str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _query_id(row: dict[str, Any], index: int) -> str:
    return str(row.get("query_id") or row.get("question_id") or f"q{index:03d}")


def _meeting_base_id(meeting_id: str) -> str:
    return str(meeting_id).replace("_first360", "").replace("-first360", "")


def _first_lines(text: str, limit: int) -> str:
    lines = str(text or "").splitlines()
    if limit > 0:
        lines = lines[:limit]
    return "\n".join(lines)


def _share_tree_meetings(share_tree: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for meeting in share_tree.get("meetings", []) or []:
        meeting_id = str(meeting.get("meeting_id", "") or "")
        if meeting_id:
            output.append(meeting_id)
    return output


def build_first360_full_context(
    *,
    share_mem_root: Path | str,
    transcript_dir: Path | str,
    max_lines_per_meeting: int = 360,
) -> tuple[str, dict[str, Any]]:
    share_tree = load_json(Path(share_mem_root) / "tree.json")
    transcript_root = Path(transcript_dir)
    parts = ["=== Full Context First360 Baseline ==="]
    included: list[str] = []
    missing: list[str] = []
    for meeting_id in _share_tree_meetings(share_tree):
        base_id = _meeting_base_id(meeting_id)
        path = transcript_root / f"{base_id}.txt"
        if not path.exists():
            missing.append(meeting_id)
            continue
        text = _first_lines(path.read_text(encoding="utf-8", errors="replace"), max_lines_per_meeting)
        included.append(meeting_id)
        parts.extend([f"\n--- meeting {meeting_id} ---", text])
    context = "\n".join(parts).rstrip() + "\n"
    return context, {
        "included_meeting_count": len(included),
        "included_meetings": included,
        "missing_meetings": missing,
        "max_lines_per_meeting": max_lines_per_meeting,
        "context_char_count": len(context),
        "estimated_context_tokens": estimate_tokens(context),
        "token_truncated": False,
    }


def _tokens(text: str) -> list[str]:
    return [term.lower() for term in TOKEN_RE.findall(str(text or "").lower())]


def _line_chunks(lines: list[str], *, chunk_size_lines: int, overlap_lines: int) -> list[tuple[int, int, str]]:
    chunk_size_lines = max(1, int(chunk_size_lines))
    overlap_lines = max(0, min(int(overlap_lines), chunk_size_lines - 1))
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(lines):
        end = min(len(lines), start + chunk_size_lines)
        chunks.append((start + 1, end, "\n".join(lines[start:end])))
        if end >= len(lines):
            break
        start = max(start + 1, end - overlap_lines)
    return chunks


def retrieve_first360_lexical_rag(
    query: str,
    *,
    share_mem_root: Path | str,
    transcript_dir: Path | str,
    max_lines_per_meeting: int = 360,
    top_k: int = 12,
    chunk_size_lines: int = 30,
    chunk_overlap_lines: int = 10,
) -> tuple[str, dict[str, Any]]:
    started = time.perf_counter()
    share_tree = load_json(Path(share_mem_root) / "tree.json")
    transcript_root = Path(transcript_dir)
    query_terms = set(_tokens(query))
    scored: list[dict[str, Any]] = []
    for meeting_id in _share_tree_meetings(share_tree):
        base_id = _meeting_base_id(meeting_id)
        path = transcript_root / f"{base_id}.txt"
        if not path.exists():
            continue
        lines = _first_lines(path.read_text(encoding="utf-8", errors="replace"), max_lines_per_meeting).splitlines()
        for start_line, end_line, chunk in _line_chunks(
            lines,
            chunk_size_lines=chunk_size_lines,
            overlap_lines=chunk_overlap_lines,
        ):
            lowered = chunk.lower()
            matched_terms = sorted(term for term in query_terms if term in lowered)
            if not matched_terms:
                continue
            score = len(matched_terms) / max(len(query_terms), 1)
            scored.append(
                {
                    "chunk_id": f"rag-{meeting_id}-L{start_line}-L{end_line}",
                    "meeting_id": meeting_id,
                    "start_line": start_line,
                    "end_line": end_line,
                    "score": round(score, 4),
                    "matched_terms": matched_terms,
                    "text": chunk,
                }
            )
    scored.sort(key=lambda row: (-float(row["score"]), str(row["meeting_id"]), int(row["start_line"])))
    selected = scored[: max(1, int(top_k))]
    parts = ["=== Traditional Lexical RAG First360 ==="]
    for chunk in selected:
        parts.extend(
            [
                f"\n[{chunk['chunk_id']}] meeting={chunk['meeting_id']} "
                f"lines={chunk['start_line']}-{chunk['end_line']} score={chunk['score']}",
                str(chunk["text"]),
            ]
        )
    context = "\n".join(parts).rstrip() + "\n"
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    return context, {
        "retrieved_chunk_count": len(selected),
        "retrieved_chunks": selected,
        "context_char_count": len(context),
        "estimated_context_tokens": estimate_tokens(context),
        "retrieval_ms": elapsed,
        "token_truncated": False,
    }


def _l1_index_from_tree(share_tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for meeting in share_tree.get("meetings", []) or []:
        meeting_id = str(meeting.get("meeting_id", "") or "")
        meeting_date = str(meeting.get("meeting_date", "") or "")
        for obj in meeting.get("memory_objects", []) or []:
            if not isinstance(obj, dict) or not obj.get("obj_id"):
                continue
            row = dict(obj)
            row.setdefault("meeting_id", meeting_id)
            row.setdefault("meeting_date", meeting_date)
            index[str(row["obj_id"])] = row
    return index


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    return []


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 15)].rstrip() + "...(truncated)"


def build_expected_answer_brief(query_row: dict[str, Any], share_tree: dict[str, Any]) -> str:
    l1_index = _l1_index_from_tree(share_tree)
    expected_l2 = _as_list(query_row.get("expected_l2_labels")) or _as_list(query_row.get("expected_l2_ids"))
    expected_l3 = _as_list(query_row.get("expected_l3_labels")) or _as_list(query_row.get("expected_l3_ids"))
    lines = [
        "Expected answer should be grounded in these gold signals.",
        f"Expected L2 labels: {', '.join(expected_l2) if expected_l2 else 'not specified'}",
        f"Expected L3 labels: {', '.join(expected_l3) if expected_l3 else 'not specified'}",
        "Expected L1 evidence:",
    ]
    for obj_id in _as_list(query_row.get("expected_obj_ids")):
        obj = l1_index.get(obj_id)
        if not obj:
            lines.append(f"- [{obj_id}] missing from effective L1 root")
            continue
        lines.append(
            f"- [{obj.get('meeting_id', '')} | {obj.get('meeting_date', '')} | {obj_id}] "
            f"type={obj.get('type', '')} content={_truncate(str(obj.get('content', '')), 420)} "
            f"evidence={_truncate(str(obj.get('evidence', '')), 360)}"
        )
    return "\n".join(lines)


def _answer_prompt(query: str, context: str) -> str:
    return f"Context:\n{context.strip()}\n\nQuestion:\n{query.strip()}\n\nAnswer:"


def _generate_answer(query: str, context: str, *, model: str) -> dict[str, Any]:
    started = time.perf_counter()
    client = create_gemini_client(load_api_keys())
    prompt = _answer_prompt(query, context)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=ANSWER_SYSTEM_PROMPT,
            temperature=0.2,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE")
            ),
        ),
    )
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    usage = usage_metadata_to_tokens(response)
    answer = (response.text or "").strip()
    estimated_input = estimate_tokens(ANSWER_SYSTEM_PROMPT + "\n" + prompt)
    estimated_output = estimate_tokens(answer)
    return {
        "answer": answer,
        "generation_ms": elapsed,
        "actual_input_tokens": usage["actual_input_tokens"] if usage["actual_input_tokens"] is not None else estimated_input,
        "actual_output_tokens": usage["actual_output_tokens"] if usage["actual_output_tokens"] is not None else estimated_output,
        "actual_total_tokens": usage["actual_total_tokens"] if usage["actual_total_tokens"] is not None else estimated_input + estimated_output,
        "token_source": "actual_usage_metadata" if usage["actual_total_tokens"] is not None else "estimated",
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


def _score_prompt(row: dict[str, Any], *, context_excerpt_chars: int) -> str:
    context = str(row.get("retrieved_context", ""))
    context_excerpt = _truncate(context, context_excerpt_chars)
    return f"""
You are judging a meeting-memory answer for an ICSI BMR first360 experiment.

Use the expected gold evidence as the main target. Use the retrieved context
excerpt only to assess grounding and traceability. The full-context strategy may
have a very large retrieved context, so the excerpt can be incomplete; do not
set factual_correctness to zero merely because the answer cites a detail outside
the excerpt. Score factual correctness by comparing the answer to the expected
gold evidence and the question.

Question:
{row.get('query', '')}

Expected gold evidence:
{row.get('expected_answer', '')}

Strategy:
{row.get('strategy', '')}

Retrieved context excerpt:
{context_excerpt}

Answer:
{row.get('answer', '')}

Score definitions:
- factual_correctness: high when the answer matches the expected gold evidence.
- evidence_grounding: high when claims are supported by retrieved context or cited gold evidence.
- topic_evolution: high when the answer captures evolution over time when the query asks for it; otherwise score neutral to high if not relevant.
- completeness: high when the answer covers the expected gold evidence.
- conciseness: high when the answer is focused and avoids unrelated detail.
- hallucination_risk: 0.0 means no unsupported fabrication risk; 1.0 means severe unsupported fabrication. A well-grounded answer should have hallucination_risk near 0.0, not 1.0.
- source_traceability: high when the answer cites meeting ids, L1 obj_ids, or transcript line ranges.

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
""".strip()


def _is_transient_error(exc: Exception) -> bool:
    return bool(TRANSIENT_ERROR_RE.search(f"{type(exc).__name__}: {exc}"))


def _with_retries(callable_obj, *, max_attempts: int, retry_wait_seconds: float):
    last_error: Exception | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            return callable_obj()
        except Exception as exc:  # pragma: no cover - integration retry path
            last_error = exc
            if attempt >= max_attempts or not _is_transient_error(exc):
                raise
            time.sleep(max(0.0, retry_wait_seconds) * attempt)
    if last_error:
        raise last_error
    raise RuntimeError("retry loop failed without exception")


def _score_row_for_icsi(
    row: dict[str, Any],
    *,
    model: str,
    context_excerpt_chars: int = 80000,
    max_attempts: int = 4,
    retry_wait_seconds: float = 30.0,
) -> dict[str, Any]:
    client = create_gemini_client(load_api_keys())
    prompt = _score_prompt(row, context_excerpt_chars=context_excerpt_chars)
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
    scores = {}
    for key in (
        "factual_correctness",
        "evidence_grounding",
        "topic_evolution",
        "completeness",
        "conciseness",
        "hallucination_risk",
        "source_traceability",
    ):
        try:
            value = float(parsed.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        scores[key] = max(0.0, min(1.0, value))
    usage = usage_metadata_to_tokens(response)
    return {
        **row,
        "scores": scores,
        "scoring_rationale": parsed.get("scoring_rationale", ""),
        "judge_raw": response.text or "",
        "judge_latency_ms": elapsed,
        "judge_usage": usage,
    }


def _strategy_row(
    *,
    query_row: dict[str, Any],
    strategy: str,
    context: str,
    metrics: dict[str, Any],
    model: str,
    expected_answer: str,
    max_attempts: int,
    retry_wait_seconds: float,
) -> dict[str, Any]:
    answer_result = _with_retries(
        lambda: _generate_answer(str(query_row.get("query", "")), context, model=model),
        max_attempts=max_attempts,
        retry_wait_seconds=retry_wait_seconds,
    )
    token_usage = {
        "estimated_context_tokens": metrics.get("estimated_context_tokens", estimate_tokens(context)),
        "actual_input_tokens": answer_result["actual_input_tokens"],
        "actual_output_tokens": answer_result["actual_output_tokens"],
        "actual_total_tokens": answer_result["actual_total_tokens"],
        "token_source": answer_result["token_source"],
    }
    return {
        "query_id": query_row.get("query_id", ""),
        "query": query_row.get("query", ""),
        "expected_answer": expected_answer,
        "strategy": strategy,
        "answer": answer_result["answer"],
        "retrieved_context": context,
        "token_usage": token_usage,
        "latency_ms": answer_result["generation_ms"],
        "retrieval_metrics": metrics,
    }


def _write_strategy_artifacts(out: Path, row: dict[str, Any]) -> None:
    query_id = str(row.get("query_id", "unknown"))
    strategy = str(row.get("strategy", "unknown"))
    write_text(out / "contexts" / query_id / f"{strategy}.txt", str(row.get("retrieved_context", "")))
    write_text(out / "answers" / query_id / f"{strategy}.txt", str(row.get("answer", "")))
    write_json(
        out / "retrieved" / query_id / f"{strategy}.json",
        {
            "strategy": strategy,
            "query_id": query_id,
        "token_usage": row.get("token_usage", {}),
        "latency_ms": row.get("latency_ms", 0.0),
        "retrieval_metrics": row.get("retrieval_metrics", {}),
        "scores": row.get("scores", {}),
        "scoring_rationale": row.get("scoring_rationale", ""),
    },
    )


def _compact_report(report: dict[str, Any], *, raw_run_root: Path) -> dict[str, Any]:
    summary = report.get("summary", {}) or {}
    full = summary.get(STRATEGY_NAMES["full_context"], {}) or {}
    rag = summary.get(STRATEGY_NAMES["rag_baseline"], {}) or {}
    v2 = summary.get(STRATEGY_NAMES["optimization_v2"], {}) or {}

    def score(row: dict[str, Any]) -> float:
        try:
            return float(row.get("average_overall_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def tokens(row: dict[str, Any]) -> float:
        try:
            return float(row.get("average_context_tokens", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    v2_score = score(v2)
    full_score = score(full)
    rag_score = score(rag)
    if v2 and full and rag and v2_score >= full_score and v2_score >= rag_score:
        decision = "optimization_v2_wins_available_baselines"
    elif not v2:
        decision = "missing_optimization_v2"
    else:
        decision = "optimization_v2_does_not_win_available_baselines"
    return {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "raw_run_root": str(raw_run_root.resolve()),
        "status": report.get("status"),
        "gate_reasons": report.get("gate_reasons", []),
        "icsi_available_baseline_decision": decision,
        "pairwise_overall_delta": {
            "optimization_v2_minus_full_context": round(v2_score - full_score, 4),
            "optimization_v2_minus_rag": round(v2_score - rag_score, 4),
        },
        "pairwise_context_token_delta": {
            "optimization_v2_minus_full_context": round(tokens(v2) - tokens(full), 4),
            "optimization_v2_minus_rag": round(tokens(v2) - tokens(rag), 4),
        },
        "summary": summary,
        "failure_case_count": report.get("failure_case_count", 0),
        "dimensions": report.get("dimensions", []),
    }


def _format_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# ICSI BMR First360 Answer Quality Comparison",
        "",
        f"- status: `{summary.get('status')}`",
        f"- gate reasons: {', '.join(summary.get('gate_reasons', [])) or 'none'}",
        f"- ICSI available-baseline decision: `{summary.get('icsi_available_baseline_decision')}`",
        f"- raw run root: `{summary.get('raw_run_root')}`",
        f"- v2 overall delta vs full context: `{(summary.get('pairwise_overall_delta') or {}).get('optimization_v2_minus_full_context')}`",
        f"- v2 overall delta vs RAG: `{(summary.get('pairwise_overall_delta') or {}).get('optimization_v2_minus_rag')}`",
        f"- v2 token delta vs full context: `{(summary.get('pairwise_context_token_delta') or {}).get('optimization_v2_minus_full_context')}`",
        f"- v2 token delta vs RAG: `{(summary.get('pairwise_context_token_delta') or {}).get('optimization_v2_minus_rag')}`",
        "",
        "## Strategy Summary",
        "",
        "| Strategy | Overall | Factual | Grounding | Evolution | Completeness | Conciseness | Hallucination Risk | Traceability | Context Tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy, row in sorted((summary.get("summary", {}) or {}).items()):
        dims = row.get("average_dimensions", {}) or {}
        lines.append(
            f"| {strategy} | {row.get('average_overall_score')} | "
            f"{dims.get('factual_correctness')} | {dims.get('evidence_grounding')} | "
            f"{dims.get('topic_evolution')} | {dims.get('completeness')} | "
            f"{dims.get('conciseness')} | {dims.get('hallucination_risk')} | "
            f"{dims.get('source_traceability')} | {row.get('average_context_tokens')} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- `full_context_first360` uses all available first360 transcript lines from the effective corpus and is not token-capped.",
            "- `rag_baseline_first360` uses normal lexical top-k chunks and is not token-capped.",
            "- `optimization_v2_candidate6` uses the isolated candidate6 effective L2/L3 view.",
            "- This report is ICSI BMR first360-specific and does not promote optimization v2 into canonical runtime.",
        ]
    )
    return "\n".join(lines) + "\n"


def summarize_existing_icsi_answer_quality(*, out: Path | str, summary_out: Path | str) -> dict[str, Any]:
    out_root = ensure_optimization_output(out)
    scored_rows = load_json(out_root / "answer_quality" / "scored_rows.json")
    rows = scored_rows.get("rows", []) if isinstance(scored_rows, dict) else scored_rows
    report = evaluate_answer_quality(run_root=out_root, scored_rows=rows)
    compact = _compact_report(report, raw_run_root=out_root)
    manifest_path = out_root / "answer_quality" / "manifest.json"
    if manifest_path.exists():
        compact["manifest"] = load_json(manifest_path)
    summary_root = Path(summary_out)
    write_json(summary_root / "summary.json", compact)
    write_text(summary_root / "summary.md", _format_summary_md(compact))
    return compact


def run_icsi_answer_quality_comparison(
    *,
    run_root: Path | str,
    share_mem_root: Path | str,
    transcript_dir: Path | str,
    queries_path: Path | str,
    out: Path | str,
    summary_out: Path | str,
    model: str = "gemini-2.5-pro",
    judge_model: str = "gemini-2.5-pro",
    max_queries: int = 0,
    max_lines_per_meeting: int = 360,
    rag_top_k: int = 12,
    max_attempts: int = 4,
    retry_wait_seconds: float = 30.0,
    inter_call_sleep_seconds: float = 2.0,
) -> dict[str, Any]:
    out_root = ensure_optimization_output(out)
    summary_root = Path(summary_out)
    share_tree = load_json(Path(share_mem_root) / "tree.json")
    queries = _load_jsonl(queries_path)
    if max_queries > 0:
        queries = queries[:max_queries]
    rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    full_context, full_meta = build_first360_full_context(
        share_mem_root=share_mem_root,
        transcript_dir=transcript_dir,
        max_lines_per_meeting=max_lines_per_meeting,
    )
    for index, query in enumerate(queries, start=1):
        query = dict(query)
        query["query_id"] = _query_id(query, index)
        expected_answer = build_expected_answer_brief(query, share_tree)

        try:
            full_row = _strategy_row(
                query_row=query,
                strategy=STRATEGY_NAMES["full_context"],
                context=full_context,
                metrics=full_meta,
                model=model,
                expected_answer=expected_answer,
                max_attempts=max_attempts,
                retry_wait_seconds=retry_wait_seconds,
            )
            rows.append(
                _score_row_for_icsi(
                    full_row,
                    model=judge_model,
                    max_attempts=max_attempts,
                    retry_wait_seconds=retry_wait_seconds,
                )
            )
            _write_strategy_artifacts(out_root, rows[-1])
            write_json(out_root / "answer_quality" / "scored_rows_partial.json", {"rows": rows})
            if inter_call_sleep_seconds > 0:
                time.sleep(inter_call_sleep_seconds)
        except Exception as exc:
            skipped_rows.append(
                {
                    "query_id": query.get("query_id", ""),
                    "strategy": STRATEGY_NAMES["full_context"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            write_json(out_root / "answer_quality" / "skipped_rows_partial.json", {"rows": skipped_rows})

        rag_context, rag_meta = retrieve_first360_lexical_rag(
            str(query.get("query", "")),
            share_mem_root=share_mem_root,
            transcript_dir=transcript_dir,
            max_lines_per_meeting=max_lines_per_meeting,
            top_k=rag_top_k,
        )
        try:
            rag_row = _strategy_row(
                query_row=query,
                strategy=STRATEGY_NAMES["rag_baseline"],
                context=rag_context,
                metrics=rag_meta,
                model=model,
                expected_answer=expected_answer,
                max_attempts=max_attempts,
                retry_wait_seconds=retry_wait_seconds,
            )
            rows.append(
                _score_row_for_icsi(
                    rag_row,
                    model=judge_model,
                    max_attempts=max_attempts,
                    retry_wait_seconds=retry_wait_seconds,
                )
            )
            _write_strategy_artifacts(out_root, rows[-1])
            write_json(out_root / "answer_quality" / "scored_rows_partial.json", {"rows": rows})
            if inter_call_sleep_seconds > 0:
                time.sleep(inter_call_sleep_seconds)
        except Exception as exc:
            skipped_rows.append(
                {
                    "query_id": query.get("query_id", ""),
                    "strategy": STRATEGY_NAMES["rag_baseline"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            write_json(out_root / "answer_quality" / "skipped_rows_partial.json", {"rows": skipped_rows})

        v2_context, v2_trace = _build_v2_context(
            query=str(query.get("query", "")),
            run_root=Path(run_root),
            share_mem_root=Path(share_mem_root),
            max_l1=10,
            max_l2=4,
            max_events_per_l2=6,
        )
        v2_metrics = {
            "selected_l1_count": len(v2_trace.get("selected_l1", []) or []),
            "selected_l2_count": len(v2_trace.get("selected_l2", []) or []),
            "selected_l3_count": len(v2_trace.get("selected_l3_ids", []) or []),
            "context_char_count": len(v2_context),
            "estimated_context_tokens": estimate_tokens(v2_context),
            "token_truncated": False,
        }
        try:
            v2_row = _strategy_row(
                query_row=query,
                strategy=STRATEGY_NAMES["optimization_v2"],
                context=v2_context,
                metrics=v2_metrics,
                model=model,
                expected_answer=expected_answer,
                max_attempts=max_attempts,
                retry_wait_seconds=retry_wait_seconds,
            )
            v2_row["retrieval_trace"] = v2_trace
            rows.append(
                _score_row_for_icsi(
                    v2_row,
                    model=judge_model,
                    max_attempts=max_attempts,
                    retry_wait_seconds=retry_wait_seconds,
                )
            )
            _write_strategy_artifacts(out_root, rows[-1])
            write_json(out_root / "answer_quality" / "scored_rows_partial.json", {"rows": rows})
            if inter_call_sleep_seconds > 0:
                time.sleep(inter_call_sleep_seconds)
        except Exception as exc:
            skipped_rows.append(
                {
                    "query_id": query.get("query_id", ""),
                    "strategy": STRATEGY_NAMES["optimization_v2"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            write_json(out_root / "answer_quality" / "skipped_rows_partial.json", {"rows": skipped_rows})

    write_json(out_root / "answer_quality" / "scored_rows.json", {"rows": rows})
    write_json(out_root / "answer_quality" / "skipped_rows.json", {"rows": skipped_rows})
    report = evaluate_answer_quality(run_root=out_root, scored_rows=rows)
    manifest = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "source_run_root": str(Path(run_root).resolve()),
        "share_mem_root": str(Path(share_mem_root).resolve()),
        "transcript_dir": str(Path(transcript_dir).resolve()),
        "queries_path": str(Path(queries_path).resolve()),
        "query_count": len(queries),
        "scored_row_count": len(rows),
        "skipped_row_count": len(skipped_rows),
        "model": model,
        "judge_model": judge_model,
        "max_lines_per_meeting": max_lines_per_meeting,
        "rag_top_k": rag_top_k,
        "max_attempts": max_attempts,
        "retry_wait_seconds": retry_wait_seconds,
        "inter_call_sleep_seconds": inter_call_sleep_seconds,
        "report_status": report.get("status"),
        "gate_reasons": report.get("gate_reasons", []),
    }
    write_json(out_root / "answer_quality" / "manifest.json", manifest)
    compact = _compact_report(report, raw_run_root=out_root)
    compact["manifest"] = manifest
    write_json(summary_root / "summary.json", compact)
    write_text(summary_root / "summary.md", _format_summary_md(compact))
    return compact


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ICSI BMR first360 answer-quality comparison.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--share-mem-root", required=True)
    parser.add_argument("--transcript-dir", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary-out", required=True)
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument("--judge-model", default="gemini-2.5-pro")
    parser.add_argument("--max-queries", type=int, default=0)
    parser.add_argument("--max-lines-per-meeting", type=int, default=360)
    parser.add_argument("--rag-top-k", type=int, default=12)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--retry-wait-seconds", type=float, default=30.0)
    parser.add_argument("--inter-call-sleep-seconds", type=float, default=2.0)
    parser.add_argument("--summarize-existing", action="store_true")
    args = parser.parse_args()
    if args.summarize_existing:
        report = summarize_existing_icsi_answer_quality(out=args.out, summary_out=args.summary_out)
        print(
            "[optimization:v2] ICSI answer-quality summary refreshed: "
            f"decision={report.get('icsi_available_baseline_decision')}"
        )
        return
    report = run_icsi_answer_quality_comparison(
        run_root=args.run_root,
        share_mem_root=args.share_mem_root,
        transcript_dir=args.transcript_dir,
        queries_path=args.queries,
        out=args.out,
        summary_out=args.summary_out,
        model=args.model,
        judge_model=args.judge_model,
        max_queries=args.max_queries,
        max_lines_per_meeting=args.max_lines_per_meeting,
        rag_top_k=args.rag_top_k,
        max_attempts=args.max_attempts,
        retry_wait_seconds=args.retry_wait_seconds,
        inter_call_sleep_seconds=args.inter_call_sleep_seconds,
    )
    print(
        "[optimization:v2] ICSI answer-quality comparison complete: "
        f"status={report.get('status')} rows={report.get('manifest', {}).get('scored_row_count')}"
    )


if __name__ == "__main__":
    main()
