"""Recall: semantic retrieval from the temporal tree + optional short-term memory."""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Any

from google import genai

from embedder import EmbedCache, cosine_similarity, embed_text
from schema import DEFAULT_MODEL_NAME, EMBED_MODEL_NAME, RECALL_GATE_SCHEMA

FALLBACK_SCORE_THRESHOLD = 0.80
FALLBACK_MAX_RESULTS = 8


# ===================================================================
# Keyword matching (still used by short-term retrieval)
# ===================================================================

def _keyword_score(text: str, keywords: list[str]) -> float:
    """Fraction of *keywords* that appear in *text* (case-insensitive)."""
    if not keywords or not text:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in text_lower)
    return hits / len(keywords)


# ===================================================================
# Scoring helpers
# ===================================================================

def _importance_score(importance: float) -> float:
    """Map importance (0.0-1.0) to [0.0, 1.0] with clamping."""
    return max(0.0, min(1.0, float(importance)))


def _recency_score(
    meeting_date: str,
    timestamp: str,
    obj_type: str,
    query_date: datetime,
    importance: float,
) -> float:
    """Type-specific recency decay with graceful fallback."""
    date_str = meeting_date if meeting_date else timestamp

    try:
        meeting_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.5

    if meeting_dt.tzinfo is None:
        meeting_dt = meeting_dt.replace(tzinfo=timezone.utc)
    if query_date.tzinfo is None:
        query_date = query_date.replace(tzinfo=timezone.utc)

    delta_days = max(0, (query_date - meeting_dt).days)
    high_imp = importance >= 0.8

    if obj_type in ("decision", "method_change", "argument"):
        return max(0.3, 1.0 - delta_days / 360)
    if obj_type in ("result", "open_question"):
        floor = 0.3 if high_imp else 0.0
        return max(floor, 1.0 - delta_days / 180)
    if obj_type == "todo":
        floor = 0.3 if high_imp else 0.0
        return max(floor, 1.0 - delta_days / 30)

    floor = 0.3 if high_imp else 0.0
    return max(floor, 1.0 - delta_days / 180)


def _combined_score(
    s_sem: float,
    s_recency: float,
    s_importance: float,
    w_s: float = 0.6,
    w_r: float = 0.2,
    w_i: float = 0.2,
) -> float:
    """Weighted combination for semantic retrieval."""
    return w_s * s_sem + w_r * s_recency + w_i * s_importance


# ===================================================================
# L1 semantic search
# ===================================================================

def search_l1_semantic(
    tree: dict[str, Any],
    query_emb: list[float],
    api_key: str,
    cache: EmbedCache,
    obj_types: list[str] | None = None,
    min_importance: float = 0.0,
    top_k: int = 30,
    query_date: datetime | None = None,
    embed_model: str = EMBED_MODEL_NAME,
) -> list[dict[str, Any]]:
    """Search ALL L1 objects using semantic + recency + importance scoring."""
    if query_date is None:
        query_date = datetime.now(timezone.utc)

    results: list[dict[str, Any]] = []

    for meeting in tree.get("meetings", []):
        meeting_id = meeting.get("meeting_id", "")
        timestamp = meeting.get("timestamp", "")
        meeting_date = meeting.get("meeting_date", "")
        phase_id = meeting.get("phase_id", "")

        for obj in meeting.get("memory_objects", []):
            obj_type = obj.get("type", "")
            if obj_types and obj_type not in obj_types:
                continue

            try:
                importance = float(obj.get("importance") or 0.0)
            except (TypeError, ValueError):
                importance = 0.0

            if importance < min_importance:
                continue

            raw_topics = obj.get("related_topics", [])
            topics = [str(t) for t in raw_topics] if isinstance(raw_topics, list) else []
            text = " ".join(
                [
                    str(obj.get("content", "") or ""),
                    str(obj.get("evidence", "") or ""),
                    " ".join(topics),
                ]
            ).strip()
            if not text:
                continue

            obj_emb = embed_text(text, api_key, cache, model=embed_model)
            cos = cosine_similarity(query_emb, obj_emb)
            s_sem = (cos + 1.0) / 2.0
            s_recency = _recency_score(
                meeting_date, timestamp, str(obj_type), query_date, importance
            )
            s_importance = _importance_score(importance)
            score = _combined_score(s_sem, s_recency, s_importance)

            results.append(
                {
                    "source": "long_term_l1",
                    "meeting_id": meeting_id,
                    "timestamp": timestamp,
                    "meeting_date": meeting_date,
                    "phase_id": phase_id,
                    "obj_id": obj.get("obj_id", ""),
                    "type": obj_type,
                    "content": obj.get("content", ""),
                    "importance": importance,
                    "evidence": obj.get("evidence", ""),
                    "related_topics": topics,
                    "score": round(score, 4),
                    "s_sem": round(s_sem, 4),
                    "s_recency": round(s_recency, 4),
                    "s_importance": round(s_importance, 4),
                }
            )

    results.sort(key=lambda x: -x["score"])
    return results[:top_k]

# ===================================================================
# L2/L3 retrieval via parent-chain expansion
# ===================================================================

def _get_l2_for_meeting(tree: dict[str, Any], meeting_id: str) -> dict[str, Any] | None:
    """Find L2 phase that contains *meeting_id* in child_meeting_ids."""
    for phase in tree.get("phases", []):
        if meeting_id in phase.get("child_meeting_ids", []):
            return phase
    return None


def get_l3_profile(tree: dict[str, Any]) -> dict[str, Any] | None:
    """Return the L3 project profile if it contains meaningful data."""
    profile = tree.get("project_profile", {})
    if not profile.get("core_goal") and not profile.get("established_methods"):
        return None
    return {"source": "long_term_l3", **profile}


def expand_parent_chain(
    tree: dict[str, Any],
    l1_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Expand kept L1 objects to their L2 phases and singleton L3 profile."""
    seen_phase_ids: set[str] = set()
    l2_nodes: list[dict[str, Any]] = []

    for item in l1_results:
        phase_id = item.get("phase_id", "")
        meeting_id = item.get("meeting_id", "")

        phase = None
        if phase_id:
            if phase_id not in seen_phase_ids:
                phase = next(
                    (p for p in tree.get("phases", []) if p.get("phase_id") == phase_id),
                    None,
                )
        else:
            phase = _get_l2_for_meeting(tree, meeting_id)

        if not phase:
            continue

        pid = phase.get("phase_id", "")
        if pid and pid not in seen_phase_ids:
            seen_phase_ids.add(pid)
            l2_nodes.append({"source": "long_term_l2", **phase})

    l3_profile = get_l3_profile(tree)
    return l2_nodes, l3_profile


# ===================================================================
# Recall Gate (LLM-based noise filter)
# ===================================================================

def _build_gate_prompt(
    query: str,
    candidates: list[dict[str, Any]],
) -> str:
    candidates_text = ""
    for i, c in enumerate(candidates):
        obj_id = c.get("obj_id", c.get("phase_id", f"candidate_{i}"))
        content = c.get("content", c.get("summary", ""))
        obj_type = c.get("type", c.get("source", "?"))
        meeting_id = c.get("meeting_id", "")
        date_str = c.get("meeting_date") or c.get("timestamp", "")[:10]
        phase_id = c.get("phase_id", "")
        importance = c.get("importance", "?")
        score = c.get("score", "?")
        candidates_text += (
            f"\n[{obj_id}] type={obj_type} meeting={meeting_id} "
            f"date={date_str} phase={phase_id} "
            f"importance={importance} score={score}\n"
            f"  {content}\n"
        )

    return f"""
你是「記憶過濾閘門」(Recall Gate)。
任務：從候選記憶物件中，篩選出與使用者問題真正相關的，剔除雜訊。

規則：
1) 回傳 JSON only。
2) relevant_obj_ids 列出相關物件的 ID（保留 5-8 個為佳）。
3) 只保留真正能回答問題或提供重要背景的物件。
4) 語意接近但實際不相關的，請剔除。
5) 高度重疊或重複的物件，只保留最具代表性的一筆。
6) 可根據 date / phase 資訊，剔除過時或已被推翻的物件。

使用者問題：
{query}

候選記憶物件：
{candidates_text.strip()}
""".strip()


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
        raise RuntimeError("Failed to parse gate JSON.") from exc
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


def recall_gate(
    query: str,
    candidates: list[dict[str, Any]],
    api_key: str,
    model_name: str = DEFAULT_MODEL_NAME,
    max_retries: int = 5,
) -> list[dict[str, Any]]:
    """Use LLM to filter candidate memories, removing noise."""
    if len(candidates) <= 3:
        return candidates

    client = genai.Client(api_key=api_key)
    prompt = _build_gate_prompt(query, candidates)
    config = {
        "temperature": 0.1,
        "response_mime_type": "application/json",
        "response_json_schema": RECALL_GATE_SCHEMA,
    }
    result: dict[str, Any] | None = None
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            result = _extract_json(response.text or "")
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries or not _is_retryable_error(exc):
                break
            backoff = min(90.0, 2.0 * (2 ** (attempt - 1)))
            wait_s = backoff + random.uniform(0.0, 1.5)
            print(
                f"  Recall gate API busy ({type(exc).__name__}), "
                f"retry {attempt}/{max_retries} in {wait_s:.1f}s..."
            )
            time.sleep(wait_s)

    if result is None:
        if last_exc:
            print(
                "  Recall gate fallback: applying score-based truncation because gate API is unavailable."
            )
        filtered = [
            c for c in candidates if float(c.get("score", 0.0) or 0.0) >= FALLBACK_SCORE_THRESHOLD
        ]
        filtered.sort(key=lambda x: -float(x.get("score", 0.0) or 0.0))
        return filtered[:FALLBACK_MAX_RESULTS]

    relevant_ids = set(result.get("relevant_obj_ids", []))

    if not relevant_ids:
        return candidates

    filtered = [
        c for c in candidates if c.get("obj_id", c.get("phase_id", "")) in relevant_ids
    ]
    return filtered if filtered else candidates


# ===================================================================
# Main recall orchestrator
# ===================================================================

def recall(
    query: str,
    plan: dict[str, Any],
    tree: dict[str, Any],
    api_key: str,
    model_name: str = DEFAULT_MODEL_NAME,
    short_term_memory: dict[str, Any] | None = None,
    query_date: datetime | None = None,
    embed_cache: EmbedCache | None = None,
    top_k_raw: int = 30,
) -> dict[str, Any]:
    """Execute a recall plan and return retrieved memories."""
    if query_date is None:
        query_date = datetime.now(timezone.utc)
    embed_model = os.getenv("GEMINI_EMBED_MODEL", EMBED_MODEL_NAME).strip() or EMBED_MODEL_NAME

    keywords = plan.get("keywords", [])
    targets = set(plan.get("search_targets", []))
    type_filter_raw = plan.get("type_filter", [])
    type_filter = (
        [str(t).strip() for t in type_filter_raw if str(t).strip()]
        if isinstance(type_filter_raw, list)
        else []
    )

    own_cache = embed_cache is None
    if embed_cache is None:
        embed_cache = EmbedCache()

    stm_results: list[dict[str, Any]] = []
    l1_results: list[dict[str, Any]] = []
    l2_results: list[dict[str, Any]] = []
    l3_profile = None

    # --- short-term search (keyword-based; unchanged) ---
    if "short_term" in targets and short_term_memory:
        for mw in short_term_memory.get("meeting_window", []):
            text = " ".join([mw.get("summary", ""), " ".join(mw.get("key_points", []))])
            score = _keyword_score(text, keywords)
            if score > 0:
                stm_results.append(
                    {
                        "source": "short_term",
                        "meeting_id": mw.get("meeting_id", ""),
                        "summary": mw.get("summary", ""),
                        "key_points": mw.get("key_points", []),
                        "score": score,
                    }
                )

        for ai in short_term_memory.get("action_items", []):
            text = f"{ai.get('title', '')} {ai.get('detail', '')}"
            score = _keyword_score(text, keywords)
            if score > 0:
                stm_results.append(
                    {
                        "source": "short_term",
                        "obj_id": ai.get("item_id", ""),
                        "type": "action_item",
                        "content": f"{ai.get('title', '')}: {ai.get('detail', '')}",
                        "status": ai.get("status", ""),
                        "score": score,
                    }
                )

    # --- long-term search (semantic L1 + parent expansion to L2/L3) ---
    if any(t.startswith("long_term") for t in targets):
        query_emb = embed_text(query, api_key, embed_cache, model=embed_model)

        l1_candidates = search_l1_semantic(
            tree=tree,
            query_emb=query_emb,
            api_key=api_key,
            cache=embed_cache,
            obj_types=type_filter or None,
            top_k=top_k_raw,
            query_date=query_date,
            embed_model=embed_model,
        )

        if plan.get("complexity") == "complex" and len(l1_candidates) > 5:
            l1_results = recall_gate(query, l1_candidates, api_key, model_name)
        else:
            l1_results = l1_candidates

        l2_results, l3_profile = expand_parent_chain(tree, l1_results)

    if own_cache:
        embed_cache.save()

    return {
        "complexity": plan.get("complexity", "simple"),
        "short_term_results": stm_results,
        "long_term_results": l1_results,  # backward compatibility alias
        "long_term_l1": l1_results,
        "long_term_l2": l2_results,
        "project_profile": l3_profile,
    }


# ===================================================================
# Format for prompt injection
# ===================================================================

def format_recall_for_prompt(recall_result: dict[str, Any]) -> str:
    """Format recall results for prompt injection.

    Output order: L3 -> L2 -> L1 -> short-term.
    """
    parts: list[str] = []

    # --- L3 profile ---
    profile = recall_result.get("project_profile")
    if profile:
        parts.append("=== 研究計畫輪廓 (L3) ===")
        if profile.get("core_goal"):
            parts.append(f"目標：{profile['core_goal']}")
        if profile.get("current_phase"):
            parts.append(f"目前階段：{profile['current_phase']}")
        if profile.get("established_methods"):
            parts.append("確立做法：")
            for method in profile["established_methods"]:
                parts.append(f"  · {method}")
        if profile.get("long_term_open_questions"):
            parts.append("長期懸案：")
            for question in profile["long_term_open_questions"]:
                parts.append(f"  ? {question}")

    # --- L2 phases ---
    l2_results = recall_result.get("long_term_l2", [])
    if l2_results:
        parts.append("\n=== 階段摘要 (L2) ===")
        for phase in l2_results:
            phase_id = phase.get("phase_id", "?")
            tr = phase.get("time_range", {})
            time_str = f"{tr.get('start', '?')} ~ {tr.get('end', '?')}"
            parts.append(f"\n[Phase {phase_id} | {time_str}]")
            if phase.get("summary"):
                parts.append(f"  {phase['summary']}")
            for change in phase.get("changes", []):
                status_label = {
                    "adopted": "✓確立",
                    "abandoned": "✗棄用",
                    "evolved": "→演進",
                }.get(change.get("status", ""), change.get("status", "?"))
                parts.append(f"  [{status_label}] {change.get('method', '')}")
            for issue in phase.get("open_to_next", []):
                parts.append(f"  [懸案] {issue}")

    # --- L1 memory objects ---
    l1_results = recall_result.get(
        "long_term_l1",
        recall_result.get("long_term_results", []),
    )
    if l1_results:
        parts.append("\n=== 記憶物件 (L1) ===")

        def _sort_key(item: dict[str, Any]) -> str:
            return item.get("meeting_date") or item.get("timestamp") or item.get("meeting_id", "")

        for item in sorted(l1_results, key=_sort_key):
            date_str = item.get("meeting_date") or item.get("timestamp", "")[:10]
            parts.append(
                f"  [{item.get('meeting_id', '?')} | {date_str}] "
                f"({item.get('type', '?')}) "
                f"importance={item.get('importance', '?')} "
                f"score={item.get('score', '?')}\n"
                f"    {item.get('content', '')}"
            )

    # --- short-term results ---
    stm = recall_result.get("short_term_results", [])
    if stm:
        parts.append("\n=== 短期記憶結果 ===")
        for item in stm:
            if item.get("type") == "action_item":
                parts.append(
                    f"  [TODO] {item.get('content', '')} "
                    f"(status={item.get('status', '')})"
                )
            else:
                parts.append(
                    f"  [{item.get('meeting_id', '?')}] "
                    f"{item.get('summary', '')}"
                )

    return "\n".join(parts) if parts else "（無相關記憶）"
