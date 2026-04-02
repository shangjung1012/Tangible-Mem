from __future__ import annotations

import json
from typing import Any

from google import genai

from schema import RESPONSE_JSON_SCHEMA, SCHEMA_DESCRIPTION


def build_prompt(
    transcript: str,
    current_memory: dict[str, Any],
    meeting_id: str,
    source_file: str,
) -> str:
    return f"""
你是一個「短期記憶更新器」。
任務：根據單次會議逐字稿，更新 short-term memory。

你必須遵守：
1) 回傳 JSON only，不要有任何額外文字。
2) JSON 結構固定，欄位名稱與型態必須符合 schema。
3) 必須保留舊記憶資訊，僅新增/更新，不能任意刪除未完成項目。
4) meeting_window 不需要負責刪除舊會議；請至少正確提供目前會議的摘要，最近三次的裁切會由系統在本地完成。
5) action_items 要盡量維持 item_id 一致；新項目才新增新 id。系統會在本地只保留最近三次會議範圍內建立或更新過的 action items。
6) 若逐字稿有完成/取消/方法修正跡象，要更新 status 或 method_changes。
7) 能從逐字稿抓到證據時，寫在 evidence 欄位（短句即可）。
8) memory_version 應該是 current_memory.memory_version + 1。
9) 文字欄位請優先使用繁體中文。
10) 若無法確定 owner / proposer，請填 unknown，不要臆測。
11) `meeting_history_ids` 是系統在本地維護的順序欄位；如果你輸出它，請原樣保留 current_memory 的值，不要自行推測或重建。

Schema:
{json.dumps(SCHEMA_DESCRIPTION, ensure_ascii=False, indent=2)}

Current memory JSON:
{json.dumps(current_memory, ensure_ascii=False, indent=2)}

Current meeting metadata:
- meeting_id: {meeting_id}
- source_file: {source_file}

Transcript:
{transcript}
""".strip()


def extract_json(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise RuntimeError("Gemini response does not contain valid JSON object.")

    candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse Gemini JSON output.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Gemini JSON output must be an object.")
    return data


def generate_updated_memory(
    model_name: str,
    api_key: str,
    transcript: str,
    current_memory: dict[str, Any],
    meeting_id: str,
    source_file: str,
) -> dict[str, Any]:
    client = genai.Client(api_key=api_key)
    prompt = build_prompt(transcript, current_memory, meeting_id, source_file)
    config = {
        "temperature": 0.15,
        "response_mime_type": "application/json",
        "response_json_schema": RESPONSE_JSON_SCHEMA,
    }
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=config,
    )
    return extract_json(response.text or "")
