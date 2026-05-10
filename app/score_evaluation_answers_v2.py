from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

from config import MODEL_NAME
from google.genai import types
from memory_observatory.services.token_utils import usage_metadata_to_tokens
from retrieve_once import resolve_api_keys
from share_mem.l1.gemini_clients import create_gemini_client


DEFAULT_INPUT = ROOT / "doc/evaluation_runs/all_questions_three_methods_scored.csv"
DEFAULT_OUTPUT = ROOT / "doc/evaluation_runs/per_question_method_type_scores_v2.csv"

METHODS = [
    ("Structured", "agent_answer", "structured_evidence_answer"),
    ("RAG", "baseline_rag_answer", "rag_evidence_answer"),
    ("Full Transcript", "baseline_transcript_answer", "transcript_evidence_answer"),
]
VARIANTS = [("answer", "Answer"), ("evidence", "Evidence")]
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
OUT_FIELDS = BASE_FIELDS + [
    "method",
    "type",
    "response",
    "type_specific_metric",
    "factuality_score",
    "completeness_score",
    "hallucination_control_score",
    "evidence_grounding_score",
    "context_specificity_score",
    "temporal_evolution_score",
    "knowledge_update_score",
    "base_quality_score",
    "type_specific_score",
    "final_quality_score",
    "final_judgment",
    "judge_notes",
    "judge_json",
    "judge_input_tokens",
    "judge_output_tokens",
    "judge_total_tokens",
    "judge_token_source",
]


def type_specific(category: str) -> tuple[str, str]:
    if category in {"topic_synthesis", "cross_meeting_recall"}:
        return "temporal_evolution_score", "Temporal Evolution"
    if category in {"decision_reasoning", "conflict_or_update"}:
        return "knowledge_update_score", "Knowledge Update"
    return "context_specificity_score", "Context Specificity"


def build_prompt(row: dict[str, str], method: str, variant: str, response: str) -> str:
    metric_key, metric_label = type_specific(row.get("category", ""))
    return f"""
你是一位嚴格但公平的研究會議記憶系統評審。請評估模型回答是否符合標準答案與題型要求。

重要：所有題目都必須評四個共用 metrics，再依題型評一個專屬 metric。不要因為題型不同而省略共用 metrics。

【問題資訊】
Question ID: {row.get('question_id', '')}
Category: {row.get('category', '')}
Method: {method}
Evaluation type: {variant}
Expected route: {row.get('expected_route', '')}
Expected winner: {row.get('expected_winner', '')}

【問題】
{row.get('question', '')}

【標準答案】
{row.get('expected_answer', '')}

【模型回答】
{response}

【共用 metrics，全部都要評 1-5】
1. factuality_score: 回答是否事實正確，是否符合標準答案與會議脈絡。
2. completeness_score: 是否涵蓋標準答案的關鍵點，是否遺漏核心資訊。
3. hallucination_control_score: 是否避免編造不存在的術語、決策、流程或證據。
4. evidence_grounding_score: 回答是否有足夠證據支撐；若是 Evidence 評分類型，請更嚴格檢查證據是否能支持主張。

【題型專屬 metric，請只填這一個】
- metric name: {metric_key}
- metric meaning: {metric_label}
- 若是 context_specificity_score：評估是否抓到近期專案狀態與特定技術細節。
- 若是 temporal_evolution_score：評估是否正確描述跨會議的時間順序、轉折與演進。
- 若是 knowledge_update_score：評估是否區分舊資訊與最新決策，是否抓到被推翻或更新後的狀態。

【分數收斂公式】
base_quality_score = mean(factuality_score, completeness_score, hallucination_control_score, evidence_grounding_score)
type_specific_score = {metric_key}
final_quality_score = 0.7 * base_quality_score + 0.3 * type_specific_score

【成功判定】
final_judgment 請輸出 Yes 或 No。若 final_quality_score >= 4 且沒有重大事實錯誤，通常為 Yes；若遺漏問題核心、無法回答、或有重大錯誤，應為 No。

【輸出格式】
只輸出 JSON，不要 markdown code fence。所有 score 都是 1-5 的數字。
{{
  "factuality_score": 1-5,
  "completeness_score": 1-5,
  "hallucination_control_score": 1-5,
  "evidence_grounding_score": 1-5,
  "context_specificity_score": null 或 1-5,
  "temporal_evolution_score": null 或 1-5,
  "knowledge_update_score": null 或 1-5,
  "base_quality_score": number,
  "type_specific_score": number,
  "final_quality_score": number,
  "final_judgment": "Yes/No",
  "judge_notes": "用 2-4 句說明主要得分與扣分原因。"
}}
""".strip()


def parse_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Judge response JSON must be an object.")
    return parsed


def score_from_parsed(parsed: dict[str, Any], metric_key: str) -> dict[str, Any]:
    def getnum(key: str) -> float | None:
        value = parsed.get(key)
        if value in ("", None):
            return None
        return float(value)

    common = [
        "factuality_score",
        "completeness_score",
        "hallucination_control_score",
        "evidence_grounding_score",
    ]
    common_scores = [getnum(key) for key in common]
    if any(score is None for score in common_scores):
        raise ValueError(f"missing common score: {parsed}")
    type_score = getnum(metric_key)
    if type_score is None:
        raise ValueError(f"missing type score {metric_key}: {parsed}")

    base = sum(float(score) for score in common_scores) / 4.0
    final = 0.7 * base + 0.3 * type_score
    parsed["base_quality_score"] = round(base, 2)
    parsed["type_specific_score"] = round(type_score, 2)
    parsed["final_quality_score"] = round(final, 2)
    return parsed


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def existing_rows(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    if not path.exists():
        return {}
    rows = load_rows(path)
    return {
        (row["question_id"], row["method"], row["type"]): row
        for row in rows
        if row.get("final_quality_score")
    }


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score evaluation answers with shared base metrics plus type-specific metrics.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output)
    source_rows = load_rows(input_path)
    existing = {} if args.force else existing_rows(output_path)

    api_keys = resolve_api_keys()
    api_key: Any = api_keys if len(api_keys) > 1 else (api_keys[0] if api_keys else None)
    client = create_gemini_client(api_key)

    output_rows: list[dict[str, str]] = []
    for row in source_rows:
        for method_label, answer_col, evidence_col in METHODS:
            for variant_key, variant_label in VARIANTS:
                key = (row["question_id"], method_label, variant_label)
                if key in existing:
                    output_rows.append(existing[key])
                    continue

                response = row.get(answer_col if variant_key == "answer" else evidence_col, "")
                metric_key, metric_label = type_specific(row.get("category", ""))
                prompt = build_prompt(row, method_label, variant_label, response)

                parsed: dict[str, Any] | None = None
                usage = {
                    "actual_input_tokens": None,
                    "actual_output_tokens": None,
                    "actual_total_tokens": None,
                }
                for attempt in range(1, 5):
                    try:
                        print(
                            f"{row['question_id']}: judging {method_label} {variant_label} ({metric_label})",
                            flush=True,
                        )
                        response_obj = client.models.generate_content(
                            model=args.model,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                temperature=0.0,
                                response_mime_type="application/json",
                                tool_config=types.ToolConfig(
                                    function_calling_config=types.FunctionCallingConfig(mode="NONE")
                                ),
                            ),
                        )
                        raw = (response_obj.text or "").strip()
                        usage = usage_metadata_to_tokens(response_obj)
                        parsed = score_from_parsed(parse_json(raw), metric_key)
                        break
                    except Exception as exc:
                        if attempt >= 4:
                            raise
                        wait_s = min(20.0, 2**attempt) + random.random()
                        print(f"retry after {type(exc).__name__}: {wait_s:.1f}s", flush=True)
                        time.sleep(wait_s)

                assert parsed is not None
                output_row = {field: row.get(field, "") for field in BASE_FIELDS}
                output_row.update(
                    {
                        "method": method_label,
                        "type": variant_label,
                        "response": response,
                        "type_specific_metric": metric_key,
                    }
                )
                for field in OUT_FIELDS:
                    if field in output_row:
                        continue
                    if field == "judge_json":
                        output_row[field] = json.dumps(parsed, ensure_ascii=False)
                    elif field == "judge_input_tokens":
                        value = usage.get("actual_input_tokens")
                        output_row[field] = "" if value is None else str(value)
                    elif field == "judge_output_tokens":
                        value = usage.get("actual_output_tokens")
                        output_row[field] = "" if value is None else str(value)
                    elif field == "judge_total_tokens":
                        value = usage.get("actual_total_tokens")
                        output_row[field] = "" if value is None else str(value)
                    elif field == "judge_token_source":
                        output_row[field] = (
                            "actual_usage_metadata"
                            if usage.get("actual_total_tokens") is not None
                            else "estimated"
                        )
                    else:
                        value = parsed.get(field)
                        output_row[field] = "" if value is None else str(value)

                output_rows.append(output_row)
                write_rows(output_path, output_rows)

    write_rows(output_path, output_rows)
    print(f"wrote {output_path} rows={len(output_rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
