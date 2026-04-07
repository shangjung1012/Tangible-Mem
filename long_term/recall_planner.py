"""Recall Planner: classify query complexity and decide which memory stores to
search (Complexity-Aware Recall)."""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

from google import genai

from schema import DEFAULT_MODEL_NAME, RECALL_PLAN_SCHEMA

TODO_KEYWORDS = {
    "待辦",
    "todo",
    "任務",
    "還沒做",
    "需要做",
    "尚未",
}


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


def _is_retryable_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {429, 500, 502, 503, 504}:
        return True
    msg = str(exc).upper()
    retry_tokens = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "RATE LIMIT",
    )
    return any(token in msg for token in retry_tokens)


def _heuristic_keywords(query: str) -> list[str]:
    pieces = [p.strip() for p in re.split(r"[，。！？；、\s,:]+", query) if p.strip()]
    keywords = [p for p in pieces if len(p) >= 2]
    if not keywords and query.strip():
        keywords = [query.strip()]
    return keywords[:6]


def _heuristic_plan(query: str, reason: str) -> dict[str, Any]:
    complex_hints = ("演進", "變化", "過程", "為什麼", "原因", "歷史", "始末", "一路")
    is_complex = any(hint in query for hint in complex_hints)
    return {
        "complexity": "complex" if is_complex else "simple",
        "reasoning": f"{reason}（heuristic fallback）",
        "search_targets": (
            ["long_term_l1", "long_term_l2", "long_term_l3"]
            if is_complex
            else ["short_term"]
        ),
        "keywords": _heuristic_keywords(query),
        "time_range_hint": "",
    }


def _contains_todo_intent(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in TODO_KEYWORDS)


def _apply_todo_type_filter(plan: dict[str, Any], query: str) -> dict[str, Any]:
    """For TODO-like queries, constrain long-term retrieval to todo objects."""
    if not _contains_todo_intent(query):
        return plan

    plan["type_filter"] = ["todo"]

    targets = plan.get("search_targets", [])
    if not isinstance(targets, list):
        targets = []
    if "short_term" not in targets:
        targets.append("short_term")
    if "long_term_l1" not in targets:
        targets.append("long_term_l1")
    plan["search_targets"] = targets

    if plan.get("complexity") not in ("simple", "complex"):
        plan["complexity"] = "simple"

    return plan


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan_recall(
    query: str,
    api_key: str,
    model_name: str = DEFAULT_MODEL_NAME,
    context_hint: str = "",
    max_retries: int = 6,
) -> dict[str, Any]:
    """Classify query complexity and return a recall plan.

    Returns a dict with keys:
        complexity      – "simple" | "complex"
        reasoning       – str
        search_targets  – list[str]
        keywords        – list[str]
        time_range_hint – str
        type_filter     – optional list[str], e.g. ["todo"]
    """
    client = genai.Client(api_key=api_key)
    prompt = _build_planner_prompt(query, context_hint)
    config = {
        "temperature": 0.1,
        "response_mime_type": "application/json",
        "response_json_schema": RECALL_PLAN_SCHEMA,
    }
    last_exc: Exception | None = None
    plan: dict[str, Any] | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            plan = _extract_json(response.text or "")
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries or not _is_retryable_error(exc):
                break
            backoff = min(90.0, 2.0 * (2 ** (attempt - 1)))
            wait_s = backoff + random.uniform(0.0, 1.5)
            print(
                f"  Planner API busy ({type(exc).__name__}), "
                f"retry {attempt}/{max_retries} in {wait_s:.1f}s..."
            )
            time.sleep(wait_s)

    if plan is None:
        if last_exc and _is_retryable_error(last_exc):
            print(
                "  Planner fallback: using heuristic plan because API is temporarily unavailable."
            )
            return _apply_todo_type_filter(
                _heuristic_plan(query, reason=str(last_exc)),
                query,
            )
        if last_exc:
            raise last_exc
        return _apply_todo_type_filter(
            _heuristic_plan(query, reason="planner returned no result"),
            query,
        )

    # Validate / fallback
    if plan.get("complexity") not in ("simple", "complex"):
        plan["complexity"] = "simple"
    if not isinstance(plan.get("search_targets"), list) or not plan["search_targets"]:
        plan["search_targets"] = ["short_term"]
    if not isinstance(plan.get("keywords"), list):
        plan["keywords"] = []
    if not isinstance(plan.get("time_range_hint"), str):
        plan["time_range_hint"] = ""

    return _apply_todo_type_filter(plan, query)
