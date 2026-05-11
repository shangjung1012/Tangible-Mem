from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


BASE_FIELDS = [
    "question_id",
    "set",
    "demo_priority",
    "category",
    "expected_route",
    "expected_winner",
    "question",
    "expected_answer",
]

ANSWER_FIELDS = [
    "agent_answer",
    "structured_evidence_answer",
    "baseline_rag_answer",
    "rag_evidence_answer",
    "baseline_transcript_answer",
    "transcript_evidence_answer",
]

METRIC_FIELDS = [
    "gold_l1_obj_ids",
    "expected_l2_ids",
    "expected_l3_ids",
    "structured_context_tokens",
    "structured_total_tokens",
    "structured_token_source",
    "rag_context_tokens",
    "rag_total_tokens",
    "rag_token_source",
    "transcript_context_tokens",
    "transcript_total_tokens",
    "transcript_token_source",
]

SCORING_FIELDNAMES = BASE_FIELDS + ANSWER_FIELDS + METRIC_FIELDS

STRATEGY_COLUMNS = {
    "layered_memory": {
        "answer": "agent_answer",
        "evidence": "structured_evidence_answer",
        "context_tokens": "structured_context_tokens",
        "total_tokens": "structured_total_tokens",
        "token_source": "structured_token_source",
    },
    "rag_baseline": {
        "answer": "baseline_rag_answer",
        "evidence": "rag_evidence_answer",
        "context_tokens": "rag_context_tokens",
        "total_tokens": "rag_total_tokens",
        "token_source": "rag_token_source",
    },
    "full_context": {
        "answer": "baseline_transcript_answer",
        "evidence": "transcript_evidence_answer",
        "context_tokens": "transcript_context_tokens",
        "total_tokens": "transcript_total_tokens",
        "token_source": "transcript_token_source",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _as_csv_list(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value if str(item))
    if value is None:
        return ""
    return str(value)


def _answer_from_strategy(data: dict[str, Any]) -> str:
    answer = str(data.get("answer") or "").strip()
    if answer == "No answer generated in this run.":
        return ""
    return answer


def _metrics_value(metrics: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metrics.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _row_from_query(query: dict[str, Any]) -> dict[str, str]:
    row = {field: "" for field in SCORING_FIELDNAMES}
    row.update(
        {
            "question_id": str(query.get("question_id") or query.get("query_id") or ""),
            "set": str(query.get("set") or "observatory"),
            "demo_priority": str(query.get("demo_priority") or ""),
            "category": str(query.get("category") or "observatory"),
            "expected_route": str(query.get("expected_route") or ""),
            "expected_winner": str(query.get("expected_winner") or ""),
            "question": str(query.get("question") or query.get("query") or ""),
            "expected_answer": str(query.get("expected_answer") or ""),
            "gold_l1_obj_ids": _as_csv_list(query.get("expected_obj_ids") or query.get("strict_gold_obj_ids")),
            "expected_l2_ids": _as_csv_list(query.get("expected_l2_ids")),
            "expected_l3_ids": _as_csv_list(query.get("expected_l3_ids")),
        }
    )

    strategies = query.get("strategies") or {}
    if not isinstance(strategies, dict):
        return row
    for strategy_name, column_map in STRATEGY_COLUMNS.items():
        strategy = strategies.get(strategy_name) or {}
        if not isinstance(strategy, dict):
            continue
        metrics = strategy.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        row[column_map["answer"]] = _answer_from_strategy(strategy)
        evidence_answer = str(strategy.get("evidence_answer") or "").strip()
        row[column_map["evidence"]] = evidence_answer
        row[column_map["context_tokens"]] = _metrics_value(metrics, "estimated_context_tokens")
        row[column_map["total_tokens"]] = _metrics_value(metrics, "actual_total_tokens", "estimated_total_tokens")
        row[column_map["token_source"]] = _metrics_value(metrics, "token_source")
    return row


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCORING_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _write_summary_files(out_csv: Path, summary: dict[str, Any]) -> None:
    json_path = out_csv.with_suffix(".summary.json")
    md_path = out_csv.with_suffix(".summary.md")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Observatory Scoring Export",
        "",
        f"- run_id: {summary.get('run_id', '')}",
        f"- row_count: {summary.get('row_count', 0)}",
        f"- missing_expected_answer_count: {summary.get('missing_expected_answer_count', 0)}",
        f"- missing_answer_counts: {json.dumps(summary.get('missing_answer_counts', {}), ensure_ascii=False)}",
        "",
        "Use `app/score_evaluation_answers_v2.py --types answer` for Observatory runs that only contain one answer per strategy.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_observatory_run_to_scoring_csv(run_dir: Path | str, out_csv: Path | str) -> dict[str, Any]:
    run_path = Path(run_dir)
    output_path = Path(out_csv)
    results_path = run_path / "results.json"
    if not results_path.exists():
        raise FileNotFoundError(results_path)

    results = _read_json(results_path)
    queries = results.get("queries") or []
    if not isinstance(queries, list):
        raise ValueError("results.json field 'queries' must be a list.")

    rows = [_row_from_query(query) for query in queries if isinstance(query, dict)]
    _write_csv(output_path, rows)

    missing_answer_counts = {
        field: sum(1 for row in rows if not row.get(field))
        for field in ("agent_answer", "baseline_rag_answer", "baseline_transcript_answer")
    }
    summary = {
        "run_id": results.get("run_id", run_path.name),
        "source_results": str(results_path),
        "output_csv": str(output_path),
        "row_count": len(rows),
        "missing_expected_answer_count": sum(1 for row in rows if not row.get("expected_answer")),
        "missing_answer_counts": missing_answer_counts,
        "strategies_present": sorted(
            {
                strategy
                for query in queries
                if isinstance(query, dict)
                for strategy in (query.get("strategies") or {}).keys()
            }
        ),
    }
    _write_summary_files(output_path, summary)
    return summary
