import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_TREE_PATH = ROOT / "share_mem" / "tree.json"
LONG_TERM_DIR = ROOT / "long_term"
LONG_TERM_L2_INDEX_PATH = LONG_TERM_DIR / "l2" / "l2_index.json"
LONG_TERM_L2_VIEW_PATH = LONG_TERM_DIR / "l2" / "l2_view.json"
LONG_TERM_L2_SECONDARY_LINKS_PATH = LONG_TERM_DIR / "l2" / "l2_secondary_links.json"
LONG_TERM_L3_PROMOTIONS_PATH = LONG_TERM_DIR / "l3" / "l3_promotions.json"
LONG_TERM_L3_VIEW_PATH = LONG_TERM_DIR / "l3" / "l3_view.json"
LONG_TERM_L3_INDEX_PATH = LONG_TERM_DIR / "l3" / "l3_index.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

from recall import format_recall_for_prompt, recall
from recall_planner import plan_recall
from current_state_context import current_state_context_for_query
from retrieval_profiles import get_retrieval_budget_profile

try:
    from .memory_router import plan_memory_retrieval
except ImportError:  # pragma: no cover - direct script execution fallback
    from memory_router import plan_memory_retrieval


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _heuristic_long_term_plan(query: str) -> dict[str, Any]:
    keywords = [
        piece.lower().replace("_", "-")
        for piece in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*|[\u4e00-\u9fff]{2,}", str(query or ""))
        if piece.strip()
    ][:12]
    return {
        "complexity": "simple",
        "reasoning": "no-LLM heuristic long-term memory plan",
        "search_targets": ["long_term_l1", "long_term_l2", "long_term_l3"],
        "keywords": keywords,
        "time_range_hint": "",
    }


def _trim_context(context: str, max_chars: int) -> str:
    if max_chars <= 0:
        return context
    if len(context) <= max_chars:
        return context
    return context[:max_chars] + "\n...(truncated)"


def _long_term_runtime_budget_profile() -> dict[str, Any]:
    profile_name = os.getenv("LONG_TERM_RETRIEVAL_BUDGET_PROFILE", "generous_layered")
    try:
        return get_retrieval_budget_profile(profile_name)
    except ValueError:
        return get_retrieval_budget_profile("generous_layered")


def retrieve_memory_context(
    query: str,
    api_key: str,
    model_name: str,
    planner_model_name: str | None = None,
    max_context_chars: int = 16000,
    use_llm_planner: bool = False,
    retrieval_mode: str = "hybrid",
) -> str:
    plan = plan_memory_retrieval(query)
    targets = [
        target
        for target in plan.get("targets", [])
        if target in {"short_term", "long_term"}
    ]
    if not targets:
        return "（此問題不需要會議記憶檢索）"

    short_term_budget = max_context_chars
    long_term_budget = max_context_chars
    if "short_term" in targets and "long_term" in targets:
        if max_context_chars <= 0:
            short_term_budget = 0
            long_term_budget = 0
        elif max_context_chars < 2400:
            short_term_budget = max(300, max_context_chars // 2 - 150)
            long_term_budget = max(300, max_context_chars - short_term_budget - 300)
        else:
            short_term_budget = max(1200, min(2400, max_context_chars // 4))
            long_term_budget = max(2400, max_context_chars - short_term_budget - 300)

    parts = [
        "=== Memory Router ===",
        f"strategy: {plan.get('strategy', '')}",
        f"reason: {plan.get('reason', '')}",
        f"confidence: {plan.get('confidence', '')}",
    ]
    if "short_term" in targets:
        parts.extend(
            [
                "",
                "=== Short-Term Memory ===",
                retrieve_short_term_context_adapter(
                    query=query,
                    api_key=api_key,
                    max_context_chars=short_term_budget,
                )[:short_term_budget],
            ]
        )
    if "long_term" in targets:
        parts.extend(
            [
                "",
                "=== Long-Term Memory ===",
                retrieve_long_term_context(
                    query=query,
                    api_key=api_key,
                    model_name=model_name,
                    planner_model_name=planner_model_name,
                    max_context_chars=long_term_budget,
                    use_llm_planner=use_llm_planner,
                    retrieval_mode=retrieval_mode,
                )[:long_term_budget],
            ]
        )
    context = "\n".join(parts)
    return _trim_context(context, max_context_chars)


def retrieve_short_term_context_adapter(
    query: str,
    api_key: str,
    max_context_chars: int = 6000,
    retrieval_mode: str = "hybrid",
    top_k: int = 6,
) -> str:
    """Call the short-term retrieval module when it exists.

    This adapter lets long/short integration land before the new short-term
    retrieval package is pushed. Once `short_term.retrieval.short_term_context`
    exists, the same interface will call it directly.
    """
    try:
        from short_term.retrieval.short_term_context import retrieve_short_term_context
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("short_term.retrieval"):
            return "（short-term retrieval module is not available yet）"
        raise

    return retrieve_short_term_context(
        query=query,
        api_key=api_key,
        retrieval_mode=retrieval_mode,
        top_k=top_k,
        max_context_chars=max_context_chars,
    )


def retrieve_long_term_context(
    query: str,
    api_key: str,
    model_name: str,
    planner_model_name: str | None = None,
    max_context_chars: int = 16000,
    use_llm_planner: bool = False,
    retrieval_mode: str = "hybrid",
) -> str:
    tree = load_json_object(LONG_TERM_TREE_PATH)
    if not tree:
        return "（無長期記憶）"

    if use_llm_planner:
        effective_planner_model = planner_model_name or os.getenv("GEMINI_PLANNER_MODEL", "") or model_name
        plan = plan_recall(query=query, api_key=api_key, model_name=effective_planner_model)
    else:
        plan = _heuristic_long_term_plan(query)
    long_targets = [t for t in plan.get("search_targets", []) if t.startswith("long_term_")]
    if not long_targets:
        long_targets = ["long_term_l1", "long_term_l2", "long_term_l3"]
    plan["search_targets"] = long_targets

    budget = _long_term_runtime_budget_profile()
    result = recall(
        query=query,
        plan=plan,
        tree=tree,
        api_key=api_key,
        model_name=model_name,
        short_term_memory=None,
        l2_index_path=LONG_TERM_L2_INDEX_PATH,
        l2_view_path=LONG_TERM_L2_VIEW_PATH,
        l2_secondary_links_path=LONG_TERM_L2_SECONDARY_LINKS_PATH,
        l3_promotions_path=LONG_TERM_L3_PROMOTIONS_PATH,
        l3_view_path=LONG_TERM_L3_VIEW_PATH,
        l3_index_path=LONG_TERM_L3_INDEX_PATH,
        top_k_raw=int(budget["top_k_raw"]),
        max_l1_seeds_for_prompt=int(budget["max_l1_seeds_for_prompt"]),
        max_global_topic_map_chars=int(budget["max_global_topic_map_chars"]),
        max_relevant_l2_summaries=int(budget["max_relevant_l2_summaries"]),
        max_expanded_l2_topics=int(budget["max_expanded_l2_topics"]),
        max_sibling_child_l2_topics=int(budget.get("max_sibling_child_l2_topics", 0) or 0),
        max_events_per_l2=int(budget["max_events_per_l2"]),
        max_events_per_child_l2=int(budget["max_events_per_child_l2"]),
        max_events_per_sibling_child_l2=int(
            budget.get("max_events_per_sibling_child_l2", 3) or 3
        ),
        max_event_chars=int(budget["max_event_chars"]),
        prefer_materialized_l3=bool(budget["prefer_materialized_l3"]),
        topic_size_penalty=float(budget["topic_size_penalty"]),
        include_retrieval_debug=False,
        retrieval_mode=retrieval_mode,
    )
    context = format_recall_for_prompt(
        result,
        l1_content_chars=220,
        l1_evidence_chars=320,
    )
    current_state_context = current_state_context_for_query(query, ROOT)
    if current_state_context:
        context = f"{current_state_context}\n\n{context}"
    if len(context) > max_context_chars:
        return context[:max_context_chars] + "\n...(truncated)"
    return context
