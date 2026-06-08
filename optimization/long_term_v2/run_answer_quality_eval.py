from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from google.genai import types

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from memory_observatory.services.experiment_runner import _generate_answer
from memory_observatory.services.token_utils import estimate_tokens, usage_metadata_to_tokens
from optimization.long_term_v2.effective_view import load_effective_topic_surface
from optimization.long_term_v2.evaluate_answer_quality import evaluate_answer_quality
from optimization.long_term_v2.evaluate_retrieval import _rank_l1
from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import load_profile
from share_mem.l1.gemini_clients import create_gemini_client
from share_mem.l1.io_utils import load_api_keys
from share_mem.store import build_l1_index, load_share_tree


DIMENSIONS = [
    "factual_correctness",
    "evidence_grounding",
    "topic_evolution",
    "completeness",
    "conciseness",
    "hallucination_risk",
    "source_traceability",
]


def _load_jsonl(path: Path | str) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 15)].rstrip() + "...(truncated)"


def _strategy_from_observatory(strategy: str) -> str:
    return {
        "full_context": "full_context",
        "rag_baseline": "rag_baseline",
        "layered_memory": "canonical_layered",
    }[strategy]


def _context_token_usage(context: str) -> dict[str, Any]:
    return {
        "estimated_context_tokens": estimate_tokens(context),
        "actual_input_tokens": None,
        "actual_output_tokens": None,
        "actual_total_tokens": None,
        "token_source": "estimated",
    }


def _load_observatory_rows(*, baseline_run_root: Path, queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, query_row in enumerate(queries, start=1):
        query_id = str(query_row.get("query_id") or query_row.get("question_id") or f"q{index:03d}")
        for strategy in ("full_context", "rag_baseline", "layered_memory"):
            answer_path = baseline_run_root / "answers" / query_id / f"{strategy}.txt"
            context_path = baseline_run_root / "contexts" / query_id / f"{strategy}.txt"
            retrieved_path = baseline_run_root / "retrieved" / query_id / f"{strategy}.json"
            if not answer_path.exists() or not context_path.exists():
                continue
            metrics = {}
            if retrieved_path.exists():
                retrieved = load_json(retrieved_path)
                metrics = retrieved.get("metrics", {}) or {}
            rows.append(
                {
                    "query_id": query_id,
                    "query": query_row.get("query", ""),
                    "expected_answer": query_row.get("expected_answer", ""),
                    "strategy": _strategy_from_observatory(strategy),
                    "answer": answer_path.read_text(encoding="utf-8"),
                    "retrieved_context": context_path.read_text(encoding="utf-8"),
                    "token_usage": {
                        "estimated_context_tokens": metrics.get("estimated_context_tokens"),
                        "actual_input_tokens": metrics.get("actual_input_tokens"),
                        "actual_output_tokens": metrics.get("actual_output_tokens"),
                        "actual_total_tokens": metrics.get("actual_total_tokens"),
                        "token_source": metrics.get("token_source", ""),
                    },
                    "latency_ms": metrics.get("total_ms", 0.0),
                }
            )
    return rows


def _l2_by_id(run_root: Path) -> dict[str, dict[str, Any]]:
    l2_view = load_effective_topic_surface(run_root)["l2_view"]
    return {str(node.get("l2_id")): node for node in l2_view.get("l2_nodes", []) or []}


def _child_l3_by_obj_from_view(l3_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for parent in l3_view.get("l3_parents", []) or []:
        for child in parent.get("child_l2_nodes", []) or []:
            for obj_id in child.get("linked_obj_ids", []) or []:
                output[str(obj_id)] = {
                    "parent_l3_id": parent.get("l3_id", ""),
                    "parent_l3_label": parent.get("label", ""),
                    "child_l2_id": child.get("child_l2_id", ""),
                    "child_l2_label": child.get("label", ""),
                    "timeline_digest": child.get("timeline_digest", []) or [],
                }
    return output


def _child_l3_by_obj(run_root: Path) -> dict[str, dict[str, Any]]:
    return _child_l3_by_obj_from_view(load_effective_topic_surface(run_root)["l3_view"])


def _build_v2_context(
    *,
    query: str,
    run_root: Path,
    share_mem_root: Path,
    max_l1: int = 8,
    max_l2: int = 3,
    max_events_per_l2: int = 4,
) -> tuple[str, dict[str, Any]]:
    tree = load_share_tree(share_mem_root)
    l1_index = build_l1_index(tree)
    manifest = load_json(run_root / "manifest.json")
    profile = load_profile(str(manifest.get("profile_path")))
    selected_l1 = _rank_l1(query, l1_index, top_k=max_l1, profile=profile)
    effective_surface = load_effective_topic_surface(run_root)
    l2_index = effective_surface["l2_index"]
    l2_nodes = {str(node.get("l2_id")): node for node in effective_surface["l2_view"].get("l2_nodes", []) or []}
    l3_index = effective_surface["l3_index"]
    child_by_obj = _child_l3_by_obj_from_view(effective_surface["l3_view"])

    grouped: dict[str, dict[str, Any]] = {}
    for seed in selected_l1:
        obj_id = seed["obj_id"]
        assignment = l2_index.get(obj_id, {}) if isinstance(l2_index.get(obj_id), dict) else {}
        l2_id = str(assignment.get("l2_id", ""))
        if not l2_id:
            continue
        group = grouped.setdefault(
            l2_id,
            {
                "l2_id": l2_id,
                "matched_l1_ids": [],
                "best_score": 0.0,
            },
        )
        group["matched_l1_ids"].append(obj_id)
        group["best_score"] = max(float(group["best_score"]), float(seed.get("score", 0.0) or 0.0))
    ordered_l2 = sorted(grouped.values(), key=lambda row: (-float(row["best_score"]), row["l2_id"]))[:max_l2]

    lines = [
        "=== Optimization v2 Retrieval Context ===",
        "This context is evidence-first. L2/L3 are navigation and evolution context; L1 evidence is the factual source.",
        "",
        "=== L1 Evidence Seeds ===",
    ]
    for seed in selected_l1:
        obj = l1_index.get(seed["obj_id"], {})
        lines.extend(
            [
                f"- [{obj.get('meeting_id', '')} | {obj.get('meeting_date', '')} | {seed['obj_id']}] "
                f"type={obj.get('type', '')} importance={obj.get('importance', '')} score={seed.get('score')}",
                f"  content: {_truncate(str(obj.get('content', '')), 420)}",
                f"  evidence: {_truncate(str(obj.get('evidence', '')), 520)}",
            ]
        )
    lines.append("")
    lines.append("=== L2 / L3 Topic Context ===")
    topic_rows = []
    for group in ordered_l2:
        l2_id = group["l2_id"]
        node = l2_nodes.get(l2_id, {})
        linked = node.get("linked_obj_ids", []) or []
        timeline = node.get("timeline_digest", []) or []
        selected_events = [
            event
            for event in timeline
            if event.get("obj_id") in set(group["matched_l1_ids"])
        ]
        if len(selected_events) < min(max_events_per_l2, len(timeline)):
            seen = {event.get("obj_id") for event in selected_events}
            for event in timeline:
                if event.get("obj_id") in seen:
                    continue
                selected_events.append(event)
                seen.add(event.get("obj_id"))
                if len(selected_events) >= max_events_per_l2:
                    break
        parent_l3 = {}
        for obj_id in group["matched_l1_ids"]:
            if obj_id in l3_index and isinstance(l3_index[obj_id], dict):
                parent_l3 = l3_index[obj_id]
                break
        lines.extend(
            [
                f"- [{l2_id}] {node.get('label', '')}",
                f"  matched_l1_ids: {', '.join(group['matched_l1_ids'])}",
                f"  topic_size: {len(linked)}",
                f"  current_state: {_truncate(str(node.get('current_state', '')), 360)}",
                f"  evolution_summary: {_truncate(str(node.get('evolution_summary', '')), 500)}",
            ]
        )
        if parent_l3:
            lines.append(
                f"  parent_l3: {parent_l3.get('parent_l3_id', '')} {parent_l3.get('parent_l3_label', '')}"
            )
        child_rows = [child_by_obj[obj_id] for obj_id in group["matched_l1_ids"] if obj_id in child_by_obj]
        if child_rows:
            child = child_rows[0]
            lines.append(f"  child_l2: {child.get('child_l2_id', '')} {child.get('child_l2_label', '')}")
        lines.append("  timeline_digest:")
        for event in selected_events[:max_events_per_l2]:
            lines.append(
                f"    - [{event.get('meeting_date', '')} {event.get('obj_id', '')}] "
                f"{_truncate(str(event.get('summary', '')), 260)}"
            )
        topic_rows.append(
            {
                "l2_id": l2_id,
                "label": node.get("label", ""),
                "matched_l1_ids": group["matched_l1_ids"],
                "topic_size": len(linked),
                "selected_event_count": len(selected_events[:max_events_per_l2]),
            }
        )
    context = "\n".join(lines).strip() + "\n"
    trace = {
        "selected_l1": selected_l1,
        "selected_l2": topic_rows,
        "selected_l3_ids": sorted(
            {
                str(l3_index[obj_id].get("parent_l3_id", ""))
                for obj_id in [row["obj_id"] for row in selected_l1]
                if obj_id in l3_index and isinstance(l3_index[obj_id], dict)
            }
        ),
        "effective_topic_surface": {
            "has_topic_review": effective_surface["has_topic_review"],
            "suppressed_l2_count": effective_surface["suppressed_l2_count"],
            "suppressed_l2_index_count": effective_surface["suppressed_l2_index_count"],
        },
    }
    return context, trace


def _judge_prompt(row: dict[str, Any]) -> str:
    return f"""
You are evaluating an answer for a mentor-mentee research meeting memory system.
Use the expected answer as the primary gold standard. Use the retrieved context
as supplementary grounding and traceability evidence. The retrieved context may
be truncated for very large strategies such as full transcript, so do not mark
factual_correctness as zero merely because a cited detail is absent from the
excerpt. Penalize evidence_grounding and source_traceability when the answer
does not cite or align with the available context.

Question:
{row.get('query', '')}

Expected answer:
{row.get('expected_answer', '')}

Strategy:
{row.get('strategy', '')}

Retrieved context:
{_truncate(str(row.get('retrieved_context', '')), 20000)}

Answer:
{row.get('answer', '')}

Dimensions:
- factual_correctness: answer matches expected facts and context.
- evidence_grounding: claims are supported by retrieved context.
- topic_evolution: answer captures chronological/topic evolution when relevant.
- completeness: answer covers the important expected points.
- conciseness: answer is focused and not bloated.
- hallucination_risk: 0 means no hallucination risk, 1 means high unsupported fabrication risk.
- source_traceability: answer points to meeting_id, obj_id, or concrete evidence.

Return only JSON:
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


def _parse_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)


def _score_row(row: dict[str, Any], *, model: str) -> dict[str, Any]:
    client = create_gemini_client(load_api_keys())
    prompt = _judge_prompt(row)
    last_error = ""
    for attempt in range(1, 5):
        try:
            started = time.perf_counter()
            response = client.models.generate_content(
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
            elapsed = (time.perf_counter() - started) * 1000
            parsed = _parse_json(response.text or "")
            usage = usage_metadata_to_tokens(response)
            scores = {}
            for key in DIMENSIONS:
                value = float(parsed.get(key, 0.0) or 0.0)
                scores[key] = max(0.0, min(1.0, value))
            return {
                **row,
                "scores": scores,
                "scoring_rationale": parsed.get("scoring_rationale", ""),
                "judge_raw": response.text or "",
                "judge_usage": usage,
                "judge_latency_ms": round(elapsed, 3),
            }
        except Exception as exc:  # pragma: no cover - integration retry path
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt >= 4:
                break
            time.sleep(min(20.0, 2**attempt) + random.random())
    return {
        **row,
        "scores": {key: 0.0 for key in DIMENSIONS},
        "scoring_rationale": f"judge_failed_after_retries: {last_error}",
        "judge_raw": "",
        "judge_usage": {},
        "judge_latency_ms": 0.0,
    }


def run_answer_quality_eval(
    *,
    run_root: Path | str,
    baseline_run_root: Path | str,
    queries_path: Path | str,
    share_mem_root: Path | str = "share_mem",
    llm_run_root: Path | str | None = None,
    model: str = "gemini-2.5-pro",
    judge_model: str = "gemini-2.5-pro",
    max_queries: int = 0,
) -> dict[str, Any]:
    root = ensure_optimization_output(run_root)
    baseline_root = Path(baseline_run_root)
    queries = _load_jsonl(queries_path)
    if max_queries > 0:
        queries = queries[:max_queries]
    rows = _load_observatory_rows(baseline_run_root=baseline_root, queries=queries)

    v2_runs = [("optimization_v2_deterministic", Path(run_root))]
    if llm_run_root:
        v2_runs.append(("optimization_v2_llm_assisted", Path(llm_run_root)))
    for strategy, v2_root in v2_runs:
        for index, query_row in enumerate(queries, start=1):
            query_id = str(query_row.get("query_id") or query_row.get("question_id") or f"q{index:03d}")
            context, trace = _build_v2_context(
                query=str(query_row.get("query", "")),
                run_root=v2_root,
                share_mem_root=Path(share_mem_root),
            )
            answer_result = _generate_answer(str(query_row.get("query", "")), context, model=model)
            rows.append(
                {
                    "query_id": query_id,
                    "query": query_row.get("query", ""),
                    "expected_answer": query_row.get("expected_answer", ""),
                    "strategy": strategy,
                    "answer": answer_result.get("answer", ""),
                    "retrieved_context": context,
                    "retrieval_trace": trace,
                    "token_usage": {
                        **_context_token_usage(context),
                        "actual_input_tokens": answer_result.get("actual_input_tokens"),
                        "actual_output_tokens": answer_result.get("actual_output_tokens"),
                        "actual_total_tokens": answer_result.get("actual_total_tokens"),
                        "token_source": answer_result.get("token_source", "estimated"),
                    },
                    "latency_ms": answer_result.get("generation_ms", 0.0),
                }
            )

    scored_rows = []
    for row in rows:
        scored_rows.append(_score_row(row, model=judge_model))
        write_json(root / "answer_quality" / "scored_rows_partial.json", {"rows": scored_rows})
    write_json(root / "answer_quality" / "scored_rows.json", {"rows": scored_rows})
    for row in scored_rows:
        qid = str(row.get("query_id", "unknown"))
        strategy = str(row.get("strategy", "unknown"))
        write_text(root / "answer_quality" / "contexts" / qid / f"{strategy}.txt", str(row.get("retrieved_context", "")))
        write_text(root / "answer_quality" / "answers" / qid / f"{strategy}.txt", str(row.get("answer", "")))
    report = evaluate_answer_quality(run_root=root, scored_rows=scored_rows)
    manifest = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "baseline_run_root": str(baseline_root.resolve()),
        "queries_path": str(Path(queries_path).resolve()),
        "query_count": len(queries),
        "row_count": len(scored_rows),
        "model": model,
        "judge_model": judge_model,
        "report_status": report.get("status"),
        "gate_reasons": report.get("gate_reasons", []),
    }
    write_json(root / "answer_quality" / "answer_quality_eval_manifest.json", manifest)
    return report


def rescore_existing_answer_quality(
    *,
    run_root: Path | str,
    scored_rows_path: Path | str | None = None,
    judge_model: str = "gemini-2.5-pro",
) -> dict[str, Any]:
    root = ensure_optimization_output(run_root)
    source = Path(scored_rows_path) if scored_rows_path else root / "answer_quality" / "scored_rows.json"
    payload = load_json(source)
    rows = payload.get("rows", []) if isinstance(payload, dict) else payload
    rescored = []
    for row in rows:
        rescored.append(_score_row(row, model=judge_model))
        write_json(root / "answer_quality" / "rescored_rows_partial.json", {"rows": rescored})
    write_json(root / "answer_quality" / "rescored_rows.json", {"rows": rescored})
    return evaluate_answer_quality(run_root=root, scored_rows=rescored)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run optimization v2 answer-quality scoring against baselines.")
    parser.add_argument("--run-root", required=True, help="Optimization v2 deterministic run root; answer-quality outputs are written here.")
    parser.add_argument("--baseline-run-root", required=True, help="Memory Observatory run containing full/RAG/canonical layered answers.")
    parser.add_argument("--queries", required=True)
    parser.add_argument("--share-mem-root", default="share_mem")
    parser.add_argument("--llm-run-root")
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument("--judge-model", default="gemini-2.5-pro")
    parser.add_argument("--max-queries", type=int, default=0)
    parser.add_argument("--rescore-existing", action="store_true", help="Reuse existing answer/context rows and rerun only the judge.")
    parser.add_argument("--scored-rows")
    args = parser.parse_args()
    if args.rescore_existing:
        report = rescore_existing_answer_quality(
            run_root=args.run_root,
            scored_rows_path=args.scored_rows,
            judge_model=args.judge_model,
        )
        print(f"[optimization:v2] answer-quality rescore complete: status={report['status']}")
        return
    report = run_answer_quality_eval(
        run_root=args.run_root,
        baseline_run_root=args.baseline_run_root,
        queries_path=args.queries,
        share_mem_root=args.share_mem_root,
        llm_run_root=args.llm_run_root,
        model=args.model,
        judge_model=args.judge_model,
        max_queries=args.max_queries,
    )
    print(f"[optimization:v2] answer-quality eval complete: status={report['status']}")


if __name__ == "__main__":
    main()
