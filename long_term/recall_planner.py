"""Recall Planner: classify query complexity and decide which memory stores to
search (Complexity-Aware Recall)."""

from __future__ import annotations

import json
from typing import Any

from google import genai

from schema import DEFAULT_MODEL_NAME, RECALL_PLAN_SCHEMA


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _build_planner_prompt(query: str, context_hint: str = "") -> str:
    return f"""
你是「記憶檢索規劃器」(Recall Planner)。
任務：判斷使用者的問題屬於「簡單/執行型」還是「複雜/演進型」，並決定應搜尋哪些記憶層。

判斷標準：
- simple（簡單/執行型）：詢問最近的待辦、最近的決策、具體的單一事實。
  範例：「上次會議決定怎麼處理缺失值？」、「我目前的待辦事項是什麼？」
  路由：主要搜尋 short_term

- complex（複雜/演進型）：詢問時間跨度較長的演進、因果關係、方法變更歷史。
  範例：「我們這半年來模型架構的演進史為何？」、「為什麼後來不繼續用圖神經網路？」
  路由：搜尋 long_term_l1（會議層）、long_term_l2（階段層）、long_term_l3（計畫層）

search_targets 可多選：
  short_term        — 短期記憶（最近 3 次會議的滑動窗）
  long_term_l1      — 長期記憶的會議層（所有會議的記憶物件）
  long_term_l2      — 長期記憶的階段層（月度 / 衝刺期摘要）
  long_term_l3      — 長期記憶的計畫層（研究計畫輪廓）

keywords：提取問題中的搜尋關鍵字。
time_range_hint：若問題暗示了時間範圍請描述，否則留空字串。

{f"額外情境：{context_hint}" if context_hint else ""}

使用者問題：
{query}
""".strip()


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _extract_json(raw_text: str) -> dict[str, Any]:
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
        raise RuntimeError("Response does not contain valid JSON.")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse planner JSON.") from exc
    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan_recall(
    query: str,
    api_key: str,
    model_name: str = DEFAULT_MODEL_NAME,
    context_hint: str = "",
) -> dict[str, Any]:
    """Classify query complexity and return a recall plan.

    Returns a dict with keys:
        complexity      – "simple" | "complex"
        reasoning       – str
        search_targets  – list[str]
        keywords        – list[str]
        time_range_hint – str
    """
    client = genai.Client(api_key=api_key)
    prompt = _build_planner_prompt(query, context_hint)
    config = {
        "temperature": 0.1,
        "response_mime_type": "application/json",
        "response_json_schema": RECALL_PLAN_SCHEMA,
    }
    response = client.models.generate_content(
        model=model_name, contents=prompt, config=config
    )
    plan = _extract_json(response.text or "")

    # Validate / fallback
    if plan.get("complexity") not in ("simple", "complex"):
        plan["complexity"] = "simple"
    if not isinstance(plan.get("search_targets"), list) or not plan["search_targets"]:
        plan["search_targets"] = ["short_term"]
    if not isinstance(plan.get("keywords"), list):
        plan["keywords"] = []
    if not isinstance(plan.get("time_range_hint"), str):
        plan["time_range_hint"] = ""

    return plan
