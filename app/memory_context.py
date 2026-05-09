import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_TREE_PATH = ROOT / "share_mem" / "tree.json"
LONG_TERM_DIR = ROOT / "long_term"
LONG_TERM_L2_INDEX_PATH = LONG_TERM_DIR / "l2" / "l2_index.json"
LONG_TERM_L2_VIEW_PATH = LONG_TERM_DIR / "l2" / "l2_view.json"
LONG_TERM_L3_PROMOTIONS_PATH = LONG_TERM_DIR / "l3" / "l3_promotions.json"
LONG_TERM_L3_VIEW_PATH = LONG_TERM_DIR / "l3" / "l3_view.json"
LONG_TERM_L3_INDEX_PATH = LONG_TERM_DIR / "l3" / "l3_index.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

from recall import format_recall_for_prompt, recall
from recall_planner import plan_recall
from memory_router import plan_memory_retrieval


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _trim_context(context: str, max_chars: int) -> str:
    if len(context) <= max_chars:
        return context
    return context[:max_chars] + "\n...(truncated)"


def retrieve_memory_context(
    query: str,
    api_key: str,
    model_name: str,
    planner_model_name: str | None = None,
    max_context_chars: int = 4000,
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
        short_term_budget = max(700, min(1600, max_context_chars // 3))
        long_term_budget = max(1200, max_context_chars - short_term_budget - 300)

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
                )[:long_term_budget],
            ]
        )
    context = "\n".join(parts)
    return _trim_context(context, max_context_chars)


def retrieve_short_term_context_adapter(
    query: str,
    api_key: str,
    max_context_chars: int = 4000,
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
    max_context_chars: int = 4000,
) -> str:
    tree = load_json_object(LONG_TERM_TREE_PATH)
    if not tree:
        return "（無長期記憶）"

    effective_planner_model = planner_model_name or os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash")
    plan = plan_recall(query=query, api_key=api_key, model_name=effective_planner_model)
    long_targets = [t for t in plan.get("search_targets", []) if t.startswith("long_term_")]
    if not long_targets:
        long_targets = ["long_term_l1", "long_term_l2", "long_term_l3"]
    plan["search_targets"] = long_targets

    result = recall(
        query=query,
        plan=plan,
        tree=tree,
        api_key=api_key,
        model_name=model_name,
        short_term_memory=None,
        l2_index_path=LONG_TERM_L2_INDEX_PATH,
        l2_view_path=LONG_TERM_L2_VIEW_PATH,
        l3_promotions_path=LONG_TERM_L3_PROMOTIONS_PATH,
        l3_view_path=LONG_TERM_L3_VIEW_PATH,
        l3_index_path=LONG_TERM_L3_INDEX_PATH,
        top_k_raw=30,
        max_l1_seeds_for_prompt=8,
        max_global_topic_map_chars=800,
        max_relevant_l2_summaries=3,
        max_expanded_l2_topics=2,
        max_events_per_l2=6,
        max_events_per_child_l2=8,
        max_event_chars=280,
        prefer_materialized_l3=True,
        topic_size_penalty=0.05,
        include_retrieval_debug=False,
    )
    context = format_recall_for_prompt(result)
    if len(context) > max_context_chars:
        return context[:max_context_chars] + "\n...(truncated)"
    return context
