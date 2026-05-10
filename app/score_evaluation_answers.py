from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import MODEL_NAME
from memory_observatory.services.token_utils import estimate_tokens, usage_metadata_to_tokens
from retrieve_once import resolve_api_keys

DEFAULT_INPUT = ROOT / "doc" / "evaluation_runs" / "all_questions_three_methods_all_transcripts.csv"
DEFAULT_OUTPUT = ROOT / "doc" / "evaluation_runs" / "all_questions_three_methods_scored.csv"

TARGET_COLUMNS: dict[str, str] = {
    "structured_answer": "agent_answer",
    "structured_evidence": "structured_evidence_answer",
    "rag_answer": "baseline_rag_answer",
    "rag_evidence": "rag_evidence_answer",
    "transcript_answer": "baseline_transcript_answer",
    "transcript_evidence": "transcript_evidence_answer",
}

TEMPORAL_CATEGORIES = {"topic_synthesis", "cross_meeting_recall"}
DECISION_CATEGORIES = {"decision_reasoning", "conflict_or_update"}


TEMPORAL_EVOLUTION_PROMPT = """
你是一位專業的會議記錄評審。請針對「生成回答」與「標準答案」進行比對。

【評分標準】

時間準確性：
- 若問題涉及天數、次數或會議場次，請勿懲罰正負 1 的誤差。
- 例如標準答案為 18 天，模型回答 19 天，仍可視為時間上正確。

演進完整度：
- 模型應包含技術從舊到新的轉變步驟。
- 若只回答最新狀態但漏掉主要轉折，細節分數應下降。

【輸入資訊】

問題: {question}

標準答案: {answer}

模型回答: {response}

【輸出要求】
只輸出 JSON，不要輸出 markdown code fence。
{{
  "is_correct_binary": "Yes/No",
  "temporal_score": 1-5,
  "reasoning": "說明是否因正負 1 容錯而判定正確，以及演進脈絡是否完整。"
}}
""".strip()


DECISION_UPDATE_PROMPT = """
你負責評估系統是否能追蹤「被推翻的決策」或「最新的方法選擇」。

【評分標準】

最新優先：
- 若生成回答中包含了舊資訊，但同時給出了正確的更新後答案，必須視為正確。
- 不應只因提及過時候選方案而扣成不正確。

狀態辨識：
- 模型必須明確區分哪一個決策是最後定案。
- 例如原本要做 A，後來改做 B，回答必須指出 B 是更新後狀態。

【輸入資訊】

問題: {question}

標準答案: {answer}

模型回答: {response}

【輸出要求】
只輸出 JSON，不要輸出 markdown code fence。
{{
  "is_latest_info_captured": "Yes/No",
  "knowledge_update_score": 1-5,
  "reasoning": "說明模型是否正確區分了新舊決策，即便它提到了過時的資訊。"
}}
""".strip()


THREE_LAYER_PROMPT = """
你將評估一個具備 L1/L2/L3 結構化記憶系統的表現。

【評判準則】

正確性 (Factuality)：
- 等同於標準答案或包含所有必要推導步驟。
- 若只包含子集或避開問題核心，分數應下降。

完整性 (Completeness)：
- 模型是否回想並正確利用用戶的個人化背景或會議專有名詞。
- 例如 Object、Candidate、Context Planner、L1/L2/L3、sidecar、fade-out。

幻覺偵測 (Hallucination)：
- 嚴禁出現逐字稿或標準答案脈絡中不存在的術語。
- 例如將 Object 誤植為 Outjet，或自行編造不存在的架構名稱。

【輸入資訊】

問題: {question}

標準答案: {answer}

模型回答: {response}

評分量表 (Rubric): {rubric}

【輸出要求】
只輸出 JSON，不要輸出 markdown code fence。
{{
  "factuality_score": 1-5,
  "completeness_score": 1-5,
  "hallucination_control_score": 1-5,
  "final_judgment": "Yes/No",
  "expert_notes": "針對專題競賽展示的亮點點評。"
}}
""".strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Judge generated evaluation answers with category-specific prompts."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input answer CSV path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output scored CSV path.")
    parser.add_argument("--model", default=MODEL_NAME, help=f"Gemini model. Default: {MODEL_NAME}")
    parser.add_argument("--limit", type=int, default=0, help="Score only the first N selected rows.")
    parser.add_argument("--ids", default="", help="Comma-separated question ids to score.")
    parser.add_argument(
        "--targets",
        default="",
        help=(
            "Comma-separated targets. Defaults to all: "
            + ", ".join(TARGET_COLUMNS)
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-score targets even when judge JSON already exists.",
    )
    return parser


def load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def select_judge_variant(row: dict[str, str]) -> str:
    category = str(row.get("category", "")).strip()
    if category in TEMPORAL_CATEGORIES:
        return "temporal_evolution"
    if category in DECISION_CATEGORIES:
        return "decision_update"
    return "three_layer"


def build_rubric(row: dict[str, str]) -> str:
    pieces = [
        f"category={row.get('category', '')}",
        f"expected_route={row.get('expected_route', '')}",
        f"expected_winner={row.get('expected_winner', '')}",
        f"gold_meeting_ids={row.get('gold_meeting_ids', '')}",
        f"gold_l1_obj_ids={row.get('gold_l1_obj_ids', '')}",
    ]
    return "\n".join(piece for piece in pieces if piece.split("=", 1)[1])


def build_judge_prompt(row: dict[str, str], response: str) -> str:
    variant = select_judge_variant(row)
    values = {
        "question": str(row.get("question", "")).strip(),
        "answer": str(row.get("expected_answer", "")).strip(),
        "response": str(response or "").strip(),
        "rubric": build_rubric(row),
    }
    if variant == "temporal_evolution":
        return TEMPORAL_EVOLUTION_PROMPT.format(**values)
    if variant == "decision_update":
        return DECISION_UPDATE_PROMPT.format(**values)
    return THREE_LAYER_PROMPT.format(**values)


def parse_judge_json(text: str) -> dict[str, Any]:
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


def parse_targets(value: str) -> list[tuple[str, str]]:
    requested = [part.strip() for part in str(value or "").split(",") if part.strip()]
    if not requested:
        return list(TARGET_COLUMNS.items())
    unknown = [target for target in requested if target not in TARGET_COLUMNS]
    if unknown:
        raise ValueError(f"Unsupported judge target(s): {', '.join(sorted(unknown))}")
    return [(target, TARGET_COLUMNS[target]) for target in requested]


def add_fieldnames(fieldnames: list[str], targets: Sequence[tuple[str, str]]) -> None:
    common_suffixes = [
        "judge_variant",
        "judge_json",
        "judge_reasoning",
        "judge_input_tokens",
        "judge_output_tokens",
        "judge_total_tokens",
        "judge_token_source",
        "is_correct_binary",
        "temporal_score",
        "is_latest_info_captured",
        "knowledge_update_score",
        "factuality_score",
        "completeness_score",
        "hallucination_control_score",
        "final_judgment",
        "expert_notes",
    ]
    for target, _source_col in targets:
        for suffix in common_suffixes:
            field = f"{target}_{suffix}"
            if field not in fieldnames:
                fieldnames.append(field)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def write_score_fields(
    row: dict[str, str],
    target: str,
    variant: str,
    parsed: dict[str, Any],
    usage: dict[str, int | None],
) -> None:
    row[f"{target}_judge_variant"] = variant
    row[f"{target}_judge_json"] = json.dumps(parsed, ensure_ascii=False)
    row[f"{target}_judge_reasoning"] = _stringify(
        parsed.get("reasoning") or parsed.get("expert_notes")
    )
    for key in (
        "is_correct_binary",
        "temporal_score",
        "is_latest_info_captured",
        "knowledge_update_score",
        "factuality_score",
        "completeness_score",
        "hallucination_control_score",
        "final_judgment",
        "expert_notes",
    ):
        row[f"{target}_{key}"] = _stringify(parsed.get(key))

    input_tokens = usage.get("actual_input_tokens")
    output_tokens = usage.get("actual_output_tokens")
    total_tokens = usage.get("actual_total_tokens")
    row[f"{target}_judge_input_tokens"] = "" if input_tokens is None else str(input_tokens)
    row[f"{target}_judge_output_tokens"] = "" if output_tokens is None else str(output_tokens)
    row[f"{target}_judge_total_tokens"] = "" if total_tokens is None else str(total_tokens)
    row[f"{target}_judge_token_source"] = (
        "actual_usage_metadata" if total_tokens is not None else "estimated"
    )


def generate_judge_response(
    *,
    prompt: str,
    api_key: str | Sequence[str] | None,
    model_name: str,
) -> tuple[str, dict[str, int | None]]:
    from google.genai import types
    from share_mem.l1.gemini_clients import create_gemini_client

    client = create_gemini_client(api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE")
            ),
        ),
    )
    return (response.text or "").strip(), usage_metadata_to_tokens(response)


def estimate_usage(prompt: str, response: str) -> dict[str, int]:
    input_tokens = estimate_tokens(prompt)
    output_tokens = estimate_tokens(response)
    return {
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "actual_total_tokens": input_tokens + output_tokens,
    }


def should_score(row: dict[str, str], target: str, source_col: str, force: bool) -> bool:
    response = str(row.get(source_col, "")).strip()
    if not response or response.startswith("ERROR:"):
        return False
    if force:
        return True
    existing = str(row.get(f"{target}_judge_json", "")).strip()
    return not existing or existing.startswith("ERROR:")


def run_batch(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.output)
    rows, fieldnames = load_rows(input_path)
    targets = parse_targets(args.targets)
    add_fieldnames(fieldnames, targets)

    target_ids = {part.strip() for part in str(args.ids or "").split(",") if part.strip()}
    selected = [row for row in rows if not target_ids or row.get("question_id", "") in target_ids]
    if int(args.limit or 0) > 0:
        selected = selected[: int(args.limit)]
    selected_ids = {id(row) for row in selected}

    api_keys = resolve_api_keys()
    judge_api_key: Any = api_keys if len(api_keys) > 1 else (api_keys[0] if api_keys else None)

    for row in rows:
        if id(row) not in selected_ids:
            continue
        qid = row.get("question_id", "").strip() or "unknown"
        for target, source_col in targets:
            if not should_score(row, target, source_col, bool(args.force)):
                continue
            response = row.get(source_col, "")
            prompt = build_judge_prompt(row, response)
            variant = select_judge_variant(row)
            try:
                print(f"{qid}: judging {target} ({variant})", flush=True)
                raw, usage = generate_judge_response(
                    prompt=prompt,
                    api_key=judge_api_key,
                    model_name=args.model,
                )
                parsed = parse_judge_json(raw)
            except Exception as exc:
                raw = json.dumps(
                    {"error": f"{exc.__class__.__name__}: {str(exc).strip()}"},
                    ensure_ascii=False,
                )
                usage = estimate_usage(prompt, raw)
                parsed = {"error": raw}
            write_score_fields(row, target, variant, parsed, usage)
            write_rows(output_path, rows, fieldnames)

    write_rows(output_path, rows, fieldnames)
    print(f"wrote {output_path}", flush=True)
    return 0


def main() -> None:
    raise SystemExit(run_batch())


if __name__ == "__main__":
    main()
