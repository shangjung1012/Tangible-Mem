from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from google.genai import types

from .baselines import build_full_context, retrieve_lexical_rag
from .data_loader import ObservatoryDataLoader
from .report_store import ReportStore
from .retrieval_trace import RetrievalTraceService
from .token_utils import estimate_tokens, usage_metadata_to_tokens


ANSWER_SYSTEM_PROMPT = (
    "你是一個會議記憶問答助手。請只根據提供的 context 回答使用者問題。"
    "若 context 不足，請說目前資料不足。請用繁體中文回答。"
    "回答中請盡量指出來源 meeting_id / obj_id / line range。"
)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    return []


def _query_id(row: dict[str, Any], index: int) -> str:
    return str(row.get("question_id") or row.get("query_id") or f"q{index:03d}")


def _score_layered(row: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    expected_obj_ids = set(_as_list(row.get("expected_obj_ids")))
    strict_gold_obj_ids = set(_as_list(row.get("strict_gold_obj_ids")))
    acceptable_obj_ids = set(_as_list(row.get("acceptable_obj_ids")))
    scoring_obj_ids = expected_obj_ids | acceptable_obj_ids or strict_gold_obj_ids
    expected_l2_ids = set(_as_list(row.get("expected_l2_ids")))
    expected_l3_ids = set(_as_list(row.get("expected_l3_ids")))
    selected_obj_ids = {str(item.get("obj_id", "")) for item in trace.get("l1_evidence_seeds", [])}
    selected_l2_ids = {
        str(item.get("l2_id", "") or item.get("promoted_from_l2_id", ""))
        for item in trace.get("l2_evolution_context", [])
    }
    selected_l3_ids = {str(item.get("l3_id", "")) for item in trace.get("l3_navigation", [])}
    return {
        "expected_obj_recall_at_context": (
            round(len(scoring_obj_ids & selected_obj_ids) / max(1, len(scoring_obj_ids)), 4)
            if scoring_obj_ids
            else 1.0
        ),
        "strict_obj_recall_at_context": (
            round(len(strict_gold_obj_ids & selected_obj_ids) / max(1, len(strict_gold_obj_ids)), 4)
            if strict_gold_obj_ids
            else 1.0
        ),
        "acceptable_obj_recall_at_context": (
            round(len(acceptable_obj_ids & selected_obj_ids) / max(1, len(acceptable_obj_ids)), 4)
            if acceptable_obj_ids
            else None
        ),
        "expected_l2_hit": not expected_l2_ids or bool(expected_l2_ids & selected_l2_ids),
        "expected_l3_hit": not expected_l3_ids or bool(expected_l3_ids & selected_l3_ids),
        "selected_obj_ids": sorted(selected_obj_ids),
        "selected_l2_ids": sorted(selected_l2_ids),
        "selected_l3_ids": sorted(selected_l3_ids),
    }


def _summarize(results: list[dict[str, Any]], strategies: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "query_count": len(results),
        "strategies": strategies,
        "avg_total_ms": {},
        "avg_retrieval_ms": {},
        "avg_generation_ms": {},
        "avg_context_tokens": {},
        "avg_input_tokens": {},
        "avg_output_tokens": {},
        "avg_total_tokens": {},
        "prompt_budget_pass_rate": {},
        "truncation_rate": {},
        "expected_obj_recall": {},
        "expected_l2_hit_rate": {},
        "expected_l3_hit_rate": {},
    }
    for strategy in strategies:
        rows = [row["strategies"].get(strategy, {}) for row in results if strategy in row.get("strategies", {})]
        metrics = [row.get("metrics", {}) for row in rows]
        if not rows:
            continue

        def avg(key: str) -> float:
            return round(sum(float(m.get(key, 0.0) or 0.0) for m in metrics) / max(1, len(metrics)), 3)

        summary["avg_total_ms"][strategy] = avg("total_ms")
        summary["avg_retrieval_ms"][strategy] = avg("retrieval_ms")
        summary["avg_generation_ms"][strategy] = avg("generation_ms")
        summary["avg_context_tokens"][strategy] = avg("estimated_context_tokens")
        summary["avg_input_tokens"][strategy] = avg("actual_input_tokens")
        summary["avg_output_tokens"][strategy] = avg("actual_output_tokens")
        summary["avg_total_tokens"][strategy] = avg("actual_total_tokens")
        summary["prompt_budget_pass_rate"][strategy] = round(
            sum(1 for m in metrics if m.get("prompt_budget_pass", not m.get("truncated", False))) / max(1, len(metrics)),
            4,
        )
        summary["truncation_rate"][strategy] = round(
            sum(1 for m in metrics if m.get("truncated")) / max(1, len(metrics)),
            4,
        )
        score_rows = [row.get("scores", {}) for row in rows]
        if score_rows:
            summary["expected_obj_recall"][strategy] = round(
                sum(float(row.get("expected_obj_recall_at_context", 0.0) or 0.0) for row in score_rows) / len(score_rows),
                4,
            )
            summary["expected_l2_hit_rate"][strategy] = round(
                sum(1 for row in score_rows if row.get("expected_l2_hit")) / len(score_rows),
                4,
            )
            summary["expected_l3_hit_rate"][strategy] = round(
                sum(1 for row in score_rows if row.get("expected_l3_hit")) / len(score_rows),
                4,
            )
    return summary


def _default_api_key() -> str | list[str]:
    try:
        from share_mem.l1.io_utils import load_api_keys

        return load_api_keys()
    except Exception:
        import os

        return os.getenv("GEMINI_API_KEY", "")


def _answer_prompt(query: str, context: str) -> str:
    return (
        "Context:\n"
        f"{context.strip()}\n\n"
        "Question:\n"
        f"{query.strip()}\n\n"
        "Answer:"
    )


def _generate_answer(query: str, context: str, *, model: str) -> dict[str, Any]:
    from share_mem.l1.gemini_clients import create_gemini_client

    prompt = _answer_prompt(query, context)
    started = time.perf_counter()
    client = create_gemini_client(_default_api_key())
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
    elapsed = (time.perf_counter() - started) * 1000
    usage = usage_metadata_to_tokens(response)
    estimated_input = estimate_tokens(ANSWER_SYSTEM_PROMPT + "\n" + prompt)
    output_text = (response.text or "").strip()
    estimated_output = estimate_tokens(output_text)
    token_source = "actual_usage_metadata" if usage["actual_total_tokens"] is not None else "estimated"
    return {
        "answer": output_text or "目前資料不足。",
        "generation_ms": round(elapsed, 3),
        "actual_input_tokens": usage["actual_input_tokens"] if usage["actual_input_tokens"] is not None else estimated_input,
        "actual_output_tokens": usage["actual_output_tokens"] if usage["actual_output_tokens"] is not None else estimated_output,
        "actual_total_tokens": (
            usage["actual_total_tokens"]
            if usage["actual_total_tokens"] is not None
            else estimated_input + estimated_output
        ),
        "token_source": token_source,
    }


def run_experiment(
    *,
    repo_root: Path | str,
    queries_path: Path | str,
    out: Path | str,
    strategies: Sequence[str],
    retrieval_mode: str = "lexical",
    no_llm: bool = True,
    generate_answers: bool = False,
    model: str = "gemini-2.5-pro",
    max_context_chars: int = 4000,
) -> dict[str, Any]:
    repo = Path(repo_root)
    loader = ObservatoryDataLoader(repo)
    query_rows = loader.load_eval_queries(queries_path)
    strategy_list = [str(item).strip() for item in strategies if str(item).strip()]
    report_store = ReportStore(Path(out))
    run_dir = report_store.create_run_dir("observatory")
    run_id = run_dir.name
    config = {
        "queries_path": str(queries_path),
        "strategies": strategy_list,
        "retrieval_mode": retrieval_mode,
        "no_llm": no_llm,
        "generate_answers": generate_answers,
        "model": model,
        "max_context_chars": max_context_chars,
    }
    report_store.write_json(run_dir / "run_config.json", config)
    report_store.write_text(
        run_dir / "queries.jsonl",
        "\n".join(json.dumps(row, ensure_ascii=False) for row in query_rows) + ("\n" if query_rows else ""),
    )
    trace_service = RetrievalTraceService(repo)
    query_results: list[dict[str, Any]] = []
    for index, row in enumerate(query_rows, start=1):
        qid = _query_id(row, index)
        query = str(row.get("query") or row.get("question") or "")
        query_result: dict[str, Any] = {
            "query_id": qid,
            "query": query,
            "strict_gold_obj_ids": _as_list(row.get("strict_gold_obj_ids")),
            "expected_obj_ids": _as_list(row.get("expected_obj_ids")),
            "expected_l2_ids": _as_list(row.get("expected_l2_ids")),
            "expected_l3_ids": _as_list(row.get("expected_l3_ids")),
            "notes": row.get("notes", ""),
            "strategies": {},
        }
        if "full_context" in strategy_list:
            full = build_full_context(
                repo_root=repo,
                meeting_ids=row.get("gold_meeting_ids", ""),
                scope="gold" if row.get("gold_meeting_ids") else "all",
                max_context_chars=max_context_chars,
            )
            query_result["strategies"]["full_context"] = full
        if "rag_baseline" in strategy_list:
            rag = retrieve_lexical_rag(
                query,
                repo_root=repo,
                top_k=6,
                max_context_chars=max_context_chars,
            )
            query_result["strategies"]["rag_baseline"] = rag
        if "layered_memory" in strategy_list:
            layered = trace_service.run_trace(
                query,
                retrieval_mode=retrieval_mode,
                no_llm=no_llm,
                include_debug=True,
                model_name=model,
                max_context_chars=max_context_chars,
            )
            layered["scores"] = _score_layered(row, layered)
            query_result["strategies"]["layered_memory"] = layered

        for strategy, data in query_result["strategies"].items():
            context = str(data.get("context") or data.get("formatted_prompt_context") or "")
            if generate_answers:
                answer_result = _generate_answer(query, context, model=model)
                data["answer"] = answer_result["answer"]
                metrics = data.setdefault("metrics", {})
                metrics["generation_ms"] = answer_result["generation_ms"]
                metrics["actual_input_tokens"] = answer_result["actual_input_tokens"]
                metrics["actual_output_tokens"] = answer_result["actual_output_tokens"]
                metrics["actual_total_tokens"] = answer_result["actual_total_tokens"]
                metrics["token_source"] = answer_result["token_source"]
                metrics["total_ms"] = round(
                    float(metrics.get("total_ms", 0.0) or 0.0)
                    + float(answer_result["generation_ms"] or 0.0),
                    3,
                )
            report_store.write_text(run_dir / "contexts" / qid / f"{strategy}.txt", context)
            report_store.write_json(
                run_dir / "retrieved" / qid / f"{strategy}.json",
                {key: value for key, value in data.items() if key not in {"context", "formatted_prompt_context"}},
            )
            report_store.write_text(
                run_dir / "answers" / qid / f"{strategy}.txt",
                "No answer generated in this run." if not generate_answers else str(data.get("answer", "")),
            )
        report_store.write_json(run_dir / "results_by_query" / f"{qid}.json", query_result)
        query_results.append(query_result)

    result = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "config": config,
        "summary": _summarize(query_results, strategy_list),
        "queries": query_results,
    }
    report_store.write_run(run_dir, result)
    return result
