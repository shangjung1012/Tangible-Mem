from __future__ import annotations

import json
import math
import os
import re
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
    "回答演進、歷史、設計轉變、或 why later 類問題時，請按 chronological order 整合 "
    "L1 Evidence Seeds 與 L2 / child-L2 Evolution Context。"
    "如果 context 中有 latest retrieved stage，必須簡短納入；不要只回答早期或中期階段。"
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
    selected_obj_ids = _layered_context_obj_ids(trace)
    selected_l2_ids: set[str] = set()
    for item in trace.get("l2_evolution_context", []) or []:
        if not isinstance(item, dict):
            continue
        for key in ("l2_id", "promoted_from_l2_id", "source_l2_id"):
            value = str(item.get(key, "") or "").strip()
            if value:
                selected_l2_ids.add(value)
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


def _layered_context_obj_ids(trace: dict[str, Any]) -> set[str]:
    """Return L1 ids that are actually visible in the layered prompt context.

    This intentionally counts evidence seeds and selected timeline slices, but
    not full linked_obj_ids from an L2 node, because those are navigation data
    and are not necessarily injected into the prompt.
    """
    selected: set[str] = set()
    for item in trace.get("l1_evidence_seeds", []) or []:
        if isinstance(item, dict) and item.get("obj_id"):
            selected.add(str(item["obj_id"]))
    for node in trace.get("l2_evolution_context", []) or []:
        if not isinstance(node, dict):
            continue
        for obj_id in node.get("matched_l1_ids", []) or []:
            if str(obj_id).strip():
                selected.add(str(obj_id))
        for event in node.get("timeline_digest", []) or []:
            if isinstance(event, dict) and event.get("obj_id"):
                selected.add(str(event["obj_id"]))
        materialized = node.get("materialized_l3")
        if isinstance(materialized, dict):
            for child in materialized.get("child_l2_contexts", []) or []:
                if not isinstance(child, dict):
                    continue
                for obj_id in child.get("matched_l1_ids", []) or []:
                    if str(obj_id).strip():
                        selected.add(str(obj_id))
                for event in child.get("timeline_digest", []) or []:
                    if isinstance(event, dict) and event.get("obj_id"):
                        selected.add(str(event["obj_id"]))
    return selected


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


def _is_evolution_answer_query(query: str) -> bool:
    lowered = str(query or "").lower()
    if re.search(r"\bfrom\b.+\bto\b", lowered):
        return True
    markers = (
        "evolve",
        "evolution",
        "history",
        "timeline",
        "progression",
        "later",
        "changed",
        "change over time",
        "演進",
        "演變",
        "歷史",
        "時間線",
        "後來",
        "最後",
        "轉變",
        "轉折",
        "怎麼變",
        "變成",
        "從",
        "到",
    )
    return any(marker in lowered for marker in markers)


def _query_terms_for_answer_selection(query: str) -> set[str]:
    lowered = str(query or "").lower()
    terms = {term for term in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", lowered)}
    for marker in ("update", "retrieve", "retrieval", "memory", "inspector", "visualization", "l1", "l2", "l3"):
        if marker in lowered:
            terms.add(marker)
    return terms


def _extract_context_evidence_rows(context: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lines = str(context or "").splitlines()
    seed_pattern = re.compile(
        r"^\s*-\s*\[(?P<meeting>[^|\]]+)\|\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\|\s*(?P<obj_id>L1-[^\]]+)\]"
    )
    timeline_pattern = re.compile(
        r"^\s*-\s*\[(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<obj_id>L1-[^\]]+)\]\s*(?P<content>.+)$"
    )
    for index, line in enumerate(lines):
        seed_match = seed_pattern.match(line)
        if seed_match:
            content = ""
            for following in lines[index + 1 : index + 5]:
                stripped = following.strip()
                if stripped.startswith("content:"):
                    content = stripped.removeprefix("content:").strip()
                    break
            rows.append(
                {
                    "date": seed_match.group("date"),
                    "meeting": seed_match.group("meeting").strip(),
                    "obj_id": seed_match.group("obj_id").strip(),
                    "content": content,
                    "order": index,
                }
            )
            continue

        timeline_match = timeline_pattern.match(line)
        if timeline_match:
            obj_id = timeline_match.group("obj_id").strip()
            meeting_match = re.match(r"L1-([^-]+)-", obj_id)
            rows.append(
                {
                    "date": timeline_match.group("date"),
                    "meeting": meeting_match.group(1) if meeting_match else "",
                    "obj_id": obj_id,
                    "content": timeline_match.group("content").strip(),
                    "order": index,
                }
            )
    return rows


def _latest_relevant_evidence_block(query: str, context: str, *, limit: int = 6) -> str:
    if not _is_evolution_answer_query(query):
        return ""
    rows = _extract_context_evidence_rows(context)
    if not rows:
        return ""

    latest_date = max(row["date"] for row in rows)
    latest_rows = [row for row in rows if row.get("date") == latest_date]
    query_terms = _query_terms_for_answer_selection(query)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in latest_rows:
        key = row.get("obj_id") or f"{row.get('date')}:{row.get('content')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    def score(row: dict[str, Any]) -> int:
        text = f"{row.get('obj_id', '')} {row.get('content', '')}".lower()
        return sum(1 for term in query_terms if term in text)

    deduped.sort(key=lambda row: (-score(row), int(row.get("order", 0) or 0)))
    if not deduped:
        return ""

    lines = [
        "Latest Relevant Evidence",
        "Use this checklist before answering evolution/history/update questions; it is extracted from the same context below.",
    ]
    for row in deduped[:limit]:
        content = " ".join(row.get("content", "").split())
        if len(content) > 260:
            content = content[:257].rstrip() + "..."
        lines.append(
            f"- [{row.get('meeting', '').strip()} | {row.get('date')} | {row.get('obj_id')}] {content}"
        )
    return "\n".join(lines)


def _answer_prompt(query: str, context: str) -> str:
    latest_block = _latest_relevant_evidence_block(query, context)
    latest_section = f"{latest_block}\n\n" if latest_block else ""
    return (
        latest_section +
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
    retrieval_mode: str = "hybrid",
    no_llm: bool = True,
    generate_answers: bool = False,
    model: str = "gemini-2.5-pro",
    planner_model: str | None = None,
    max_context_chars: int = 0,
    rag_top_k: int = 6,
    budget_profile: str = "",
    full_context_scope: str = "all",
    baseline_token_multiplier: float = 0.0,
    full_context_max_tokens: int = 0,
    rag_max_context_tokens: int = 0,
) -> dict[str, Any]:
    repo = Path(repo_root)
    effective_planner_model = planner_model or os.getenv("GEMINI_PLANNER_MODEL", "") or model
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
        "planner_model": "heuristic" if no_llm else effective_planner_model,
        "max_context_chars": max_context_chars,
        "rag_top_k": rag_top_k,
        "budget_profile": budget_profile,
        "full_context_scope": full_context_scope,
        "baseline_token_multiplier": baseline_token_multiplier,
        "full_context_max_tokens": full_context_max_tokens,
        "rag_max_context_tokens": rag_max_context_tokens,
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
            "question_id": str(row.get("question_id") or qid),
            "set": row.get("set", ""),
            "demo_priority": row.get("demo_priority", ""),
            "category": row.get("category", ""),
            "expected_route": row.get("expected_route", ""),
            "expected_winner": row.get("expected_winner", ""),
            "expected_answer": row.get("expected_answer", ""),
            "strict_gold_obj_ids": _as_list(row.get("strict_gold_obj_ids")),
            "acceptable_obj_ids": _as_list(row.get("acceptable_obj_ids")),
            "expected_obj_ids": _as_list(row.get("expected_obj_ids")),
            "expected_l2_ids": _as_list(row.get("expected_l2_ids")),
            "expected_l3_ids": _as_list(row.get("expected_l3_ids")),
            "gold_meeting_ids": _as_list(row.get("gold_meeting_ids")),
            "notes": row.get("notes", ""),
            "strategies": {},
        }

        def run_layered_trace() -> dict[str, Any]:
            layered_result = trace_service.run_trace(
                query,
                retrieval_mode=retrieval_mode,
                no_llm=no_llm,
                include_debug=True,
                model_name=model,
                planner_model_name=None if no_llm else effective_planner_model,
                max_context_chars=max_context_chars,
                budget_profile=budget_profile,
            )
            layered_result["scores"] = _score_layered(row, layered_result)
            return layered_result

        if "layered_memory" in strategy_list and baseline_token_multiplier > 0:
            query_result["strategies"]["layered_memory"] = run_layered_trace()

        def baseline_token_budget(explicit_budget: int) -> int:
            if explicit_budget and explicit_budget > 0:
                return int(explicit_budget)
            if baseline_token_multiplier <= 0:
                return 0
            layered = query_result["strategies"].get("layered_memory", {})
            metrics = layered.get("metrics", {}) if isinstance(layered, dict) else {}
            layered_tokens = int(metrics.get("estimated_context_tokens", 0) or 0)
            if layered_tokens <= 0:
                return 0
            return max(1, int(math.ceil(layered_tokens * baseline_token_multiplier)))

        if "full_context" in strategy_list:
            if full_context_scope == "gold":
                full_scope = "gold" if row.get("gold_meeting_ids") else "all"
                full_meeting_ids = row.get("gold_meeting_ids", "")
            else:
                full_scope = full_context_scope
                full_meeting_ids = ""
            full = build_full_context(
                repo_root=repo,
                meeting_ids=full_meeting_ids,
                scope=full_scope,
                max_context_chars=max_context_chars,
                max_context_tokens=baseline_token_budget(full_context_max_tokens),
            )
            query_result["strategies"]["full_context"] = full
        if "rag_baseline" in strategy_list:
            rag = retrieve_lexical_rag(
                query,
                repo_root=repo,
                top_k=rag_top_k,
                max_context_chars=max_context_chars,
                max_context_tokens=baseline_token_budget(rag_max_context_tokens),
            )
            query_result["strategies"]["rag_baseline"] = rag
        if "layered_memory" in strategy_list and "layered_memory" not in query_result["strategies"]:
            query_result["strategies"]["layered_memory"] = run_layered_trace()

        for strategy, data in query_result["strategies"].items():
            context = str(data.get("context") or data.get("formatted_prompt_context") or "")
            if generate_answers:
                metrics = data.setdefault("metrics", {})
                try:
                    answer_result = _generate_answer(query, context, model=model)
                    data["answer"] = answer_result["answer"]
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
                except Exception as exc:
                    error_message = f"{type(exc).__name__}: {exc}"
                    data["answer"] = f"Answer generation failed: {error_message}"
                    data["answer_error"] = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    metrics["generation_ms"] = 0.0
                    metrics["actual_input_tokens"] = None
                    metrics["actual_output_tokens"] = None
                    metrics["actual_total_tokens"] = None
                    metrics["token_source"] = "generation_error"
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
