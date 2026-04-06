"""Recall: retrieve memories from the temporal tree and (optionally) short-term
memory, with a Recall Gate to filter noise for complex queries."""

from __future__ import annotations

import json
from typing import Any

from google import genai

from schema import DEFAULT_MODEL_NAME, RECALL_GATE_SCHEMA


# ===================================================================
# Keyword matching (lightweight BM25-style)
# ===================================================================

def _keyword_score(text: str, keywords: list[str]) -> float:
    """Fraction of *keywords* that appear in *text* (case-insensitive)."""
    if not keywords or not text:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in text_lower)
    return hits / len(keywords)


# ===================================================================
# L1 search (Meeting-level memory objects)
# ===================================================================

def search_l1(
    tree: dict[str, Any],
    keywords: list[str],
    obj_types: list[str] | None = None,
    min_importance: float = 0.0,
) -> list[dict[str, Any]]:
    """Search L1 meeting memory objects by keyword and optional filters."""
    results: list[dict[str, Any]] = []
    for meeting in tree.get("meetings", []):
        meeting_id = meeting.get("meeting_id", "")
        timestamp = meeting.get("timestamp", "")
        for obj in meeting.get("memory_objects", []):
            if obj_types and obj.get("type") not in obj_types:
                continue
            if (obj.get("importance") or 0) < min_importance:
                continue

            text = " ".join(
                [
                    obj.get("content", ""),
                    obj.get("evidence", ""),
                    " ".join(obj.get("related_topics", [])),
                ]
            )
            score = _keyword_score(text, keywords)
            if score > 0:
                results.append(
                    {
                        "source": "long_term_l1",
                        "meeting_id": meeting_id,
                        "timestamp": timestamp,
                        "obj_id": obj.get("obj_id", ""),
                        "type": obj.get("type", ""),
                        "content": obj.get("content", ""),
                        "importance": obj.get("importance", 0),
                        "evidence": obj.get("evidence", ""),
                        "related_topics": obj.get("related_topics", []),
                        "score": score,
                    }
                )
    results.sort(key=lambda x: (-x["score"], x.get("timestamp", "")))
    return results


# ===================================================================
# Trace method-change causal chain
# ===================================================================

def trace_method_changes(
    tree: dict[str, Any],
    keywords: list[str],
) -> list[dict[str, Any]]:
    """Return all method_change objects matching *keywords*, sorted by time."""
    results = search_l1(tree, keywords, obj_types=["method_change"])
    # Re-sort strictly by timestamp / meeting_id for causal chain
    results.sort(key=lambda x: (x.get("meeting_id", ""), x.get("timestamp", "")))
    return results


# ===================================================================
# L2 search (Phase summaries)
# ===================================================================

def search_l2(
    tree: dict[str, Any],
    keywords: list[str],
) -> list[dict[str, Any]]:
    """Search L2 phase summaries by keywords."""
    results: list[dict[str, Any]] = []
    for phase in tree.get("phases", []):
        text_parts = [
            phase.get("summary", ""),
            " ".join(phase.get("key_decisions", [])),
            " ".join(phase.get("unresolved_issues", [])),
        ]
        for evo in phase.get("method_evolution", []):
            text_parts.extend(
                [
                    evo.get("method", ""),
                    evo.get("change", ""),
                    evo.get("reason", ""),
                ]
            )
        text = " ".join(text_parts)
        score = _keyword_score(text, keywords)
        if score > 0:
            results.append(
                {
                    "source": "long_term_l2",
                    "phase_id": phase.get("phase_id", ""),
                    "time_range": phase.get("time_range", {}),
                    "summary": phase.get("summary", ""),
                    "key_decisions": phase.get("key_decisions", []),
                    "method_evolution": phase.get("method_evolution", []),
                    "score": score,
                }
            )
    results.sort(key=lambda x: (-x["score"], x.get("phase_id", "")))
    return results


# ===================================================================
# L3 retrieval (Project profile)
# ===================================================================

def get_l3_profile(tree: dict[str, Any]) -> dict[str, Any] | None:
    """Return the L3 project profile if it contains meaningful data."""
    profile = tree.get("project_profile", {})
    if not profile.get("methodology") and not profile.get("method_timeline"):
        return None
    return {"source": "long_term_l3", **profile}


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
        candidates_text += f"\n[{obj_id}] ({c.get('source', '?')}) {content}"

    return f"""
你是「記憶過濾閘門」(Recall Gate)。
任務：從候選記憶物件中，篩選出與使用者問題真正相關的，剔除雜訊。

規則：
1) 回傳 JSON only。
2) relevant_obj_ids 列出相關物件的 ID。
3) 只保留真正能回答問題或提供重要背景的物件。
4) 表面包含相同關鍵字但實際不相關的，請剔除。

使用者問題：
{query}

候選記憶物件：
{candidates_text}
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


def recall_gate(
    query: str,
    candidates: list[dict[str, Any]],
    api_key: str,
    model_name: str = DEFAULT_MODEL_NAME,
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
    response = client.models.generate_content(
        model=model_name, contents=prompt, config=config
    )
    result = _extract_json(response.text or "")
    relevant_ids = set(result.get("relevant_obj_ids", []))

    if not relevant_ids:
        return candidates  # fallback

    filtered = [
        c
        for c in candidates
        if c.get("obj_id", c.get("phase_id", "")) in relevant_ids
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
) -> dict[str, Any]:
    """Execute a recall plan and return retrieved memories.

    Parameters
    ----------
    query : str
        The user's question.
    plan : dict
        Output of ``recall_planner.plan_recall()``.
    tree : dict
        The temporal memory tree (``tree.json``).
    api_key : str
        Gemini API key.
    model_name : str
        Gemini model name.
    short_term_memory : dict | None
        The short-term memory (``current_memory.json``).

    Returns
    -------
    dict with keys:
        complexity, short_term_results, long_term_results, project_profile
    """
    keywords = plan.get("keywords", [])
    targets = set(plan.get("search_targets", []))

    stm_results: list[dict[str, Any]] = []
    ltm_candidates: list[dict[str, Any]] = []

    # --- short-term search ---
    if "short_term" in targets and short_term_memory:
        for mw in short_term_memory.get("meeting_window", []):
            text = " ".join(
                [mw.get("summary", ""), " ".join(mw.get("key_points", []))]
            )
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

    # --- long-term L1 ---
    if "long_term_l1" in targets:
        ltm_candidates.extend(search_l1(tree, keywords))

    # --- long-term L2 ---
    if "long_term_l2" in targets:
        ltm_candidates.extend(search_l2(tree, keywords))

    # --- long-term L3 ---
    l3_profile = None
    if "long_term_l3" in targets:
        l3_profile = get_l3_profile(tree)

    # --- recall gate for complex queries ---
    if plan.get("complexity") == "complex" and len(ltm_candidates) > 5:
        ltm_candidates = recall_gate(query, ltm_candidates, api_key, model_name)

    # Sort long-term results by time for causal coherence
    ltm_candidates.sort(
        key=lambda x: x.get("timestamp", x.get("phase_id", ""))
    )

    return {
        "complexity": plan.get("complexity", "simple"),
        "short_term_results": stm_results,
        "long_term_results": ltm_candidates,
        "project_profile": l3_profile,
    }


# ===================================================================
# Format for prompt injection
# ===================================================================

def format_recall_for_prompt(recall_result: dict[str, Any]) -> str:
    """Format recall results into text suitable for injecting into a system
    prompt or chat context."""
    parts: list[str] = []

    # L3 profile
    profile = recall_result.get("project_profile")
    if profile:
        parts.append("=== 研究計畫輪廓 (L3) ===")
        if profile.get("methodology"):
            parts.append(f"方法論：{profile['methodology']}")
        for entry in profile.get("method_timeline", []):
            parts.append(
                f"  [{entry.get('period', '?')}] {entry.get('method', '')} "
                f"→ {entry.get('status', '')}（{entry.get('reason', '')}）"
            )

    # Long-term hits
    ltm = recall_result.get("long_term_results", [])
    if ltm:
        parts.append("\n=== 長期記憶檢索結果（按時間排序）===")
        for item in ltm:
            if item["source"] == "long_term_l2":
                parts.append(
                    f"\n[Phase {item.get('phase_id', '?')}] "
                    f"{item.get('summary', '')}"
                )
            elif item["source"] == "long_term_l1":
                parts.append(
                    f"  [{item.get('meeting_id', '?')}] "
                    f"({item.get('type', '?')}) {item.get('content', '')}"
                )

    # Short-term hits
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
