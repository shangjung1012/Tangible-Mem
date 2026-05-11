from __future__ import annotations

import sys
import time
import os
from pathlib import Path
from typing import Any

from .data_loader import ObservatoryDataLoader, REPO_ROOT
from .token_utils import context_token_metrics

DEFAULT_PLANNER_MODEL = os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash")


def _ensure_long_term_path(repo_root: Path) -> None:
    long_term_dir = repo_root / "long_term"
    # Tests can use a temporary repo fixture that has artifacts but not source
    # modules. Keep the checked-out long_term source importable while passing
    # fixture artifact paths explicitly into recall().
    for path in (repo_root, long_term_dir, REPO_ROOT, REPO_ROOT / "long_term"):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _heuristic_plan(query: str) -> dict[str, Any]:
    import re

    keywords = [
        piece.lower()
        for piece in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*|[\u4e00-\u9fff]{2,}", str(query or ""))
        if piece.strip()
    ][:12]
    return {
        "complexity": "simple",
        "reasoning": "Memory Observatory no-LLM heuristic plan.",
        "search_targets": ["long_term_l1", "long_term_l2", "long_term_l3"],
        "keywords": keywords,
        "time_range_hint": "",
    }


class RetrievalTraceService:
    def __init__(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root)
        self.loader = ObservatoryDataLoader(self.repo_root)
        _ensure_long_term_path(self.repo_root)

    def _recall_params(self, budget_profile: str = "") -> dict[str, Any]:
        if budget_profile:
            from retrieval_profiles import get_retrieval_budget_profile

            return get_retrieval_budget_profile(budget_profile)
        best = self.loader.load_retrieval_eval_report().get("best_params", {})
        if not isinstance(best, dict):
            best = {}
        return {
            "top_k_raw": int(best.get("top_k_raw", 30) or 30),
            "max_l1_seeds_for_prompt": int(best.get("max_l1_seeds_for_prompt", 8) or 8),
            "max_global_topic_map_chars": int(best.get("max_global_topic_map_chars", 800) or 800),
            "max_relevant_l2_summaries": int(best.get("max_expanded_l2_topics", 2) or 2),
            "max_expanded_l2_topics": int(best.get("max_expanded_l2_topics", 2) or 2),
            "max_events_per_l2": int(best.get("max_events_per_l2", 6) or 6),
            "max_events_per_child_l2": int(best.get("max_events_per_child_l2", 8) or 8),
            "max_event_chars": int(best.get("max_event_chars", 280) or 280),
            "prefer_materialized_l3": bool(best.get("prefer_materialized_l3", True)),
            "topic_size_penalty": float(best.get("topic_size_penalty", 0.05) or 0.05),
        }

    def run_trace(
        self,
        query: str,
        *,
        retrieval_mode: str = "lexical",
        no_llm: bool = True,
        include_debug: bool = True,
        model_name: str = "gemini-2.5-pro",
        planner_model_name: str | None = None,
        max_context_chars: int = 6000,
        budget_profile: str = "",
    ) -> dict[str, Any]:
        started = time.perf_counter()
        from recall import format_recall_for_prompt, recall
        from recall_planner import plan_recall

        tree = self.loader.load_share_tree()
        effective_planner_model = planner_model_name or DEFAULT_PLANNER_MODEL or model_name
        if no_llm:
            plan = _heuristic_plan(query)
            api_key: str | list[str] = ""
        else:
            try:
                from share_mem.l1.io_utils import load_api_keys

                api_key = load_api_keys()
            except Exception:
                api_key = ""
            plan = plan_recall(query=query, api_key=api_key, model_name=effective_planner_model)
            plan["search_targets"] = ["long_term_l1", "long_term_l2", "long_term_l3"]
        params = self._recall_params(budget_profile)
        result = recall(
            query=query,
            plan=plan,
            tree=tree,
            api_key=api_key,
            model_name=model_name,
            l2_index_path=self.repo_root / "long_term" / "l2" / "l2_index.json",
            l2_view_path=self.repo_root / "long_term" / "l2" / "l2_view.json",
            l3_promotions_path=self.repo_root / "long_term" / "l3" / "l3_promotions.json",
            l3_view_path=self.repo_root / "long_term" / "l3" / "l3_view.json",
            l3_index_path=self.repo_root / "long_term" / "l3" / "l3_index.json",
            include_retrieval_debug=True,
            retrieval_mode=retrieval_mode,
            **params,
        )
        formatted = format_recall_for_prompt(
            result,
            include_debug=include_debug,
            l1_content_chars=320,
            l1_evidence_chars=420,
        )
        original_chars = len(formatted)
        truncated = bool(max_context_chars and max_context_chars > 0 and original_chars > max_context_chars)
        if truncated:
            formatted = formatted[:max_context_chars] + "\n...(truncated)"
        elapsed = (time.perf_counter() - started) * 1000
        debug = result.get("retrieval_debug", {}) if isinstance(result.get("retrieval_debug"), dict) else {}
        metrics = context_token_metrics(formatted)
        metrics.update(
            {
                "selected_l1_count": int(debug.get("selected_l1_count", len(result.get("long_term_l1", []))) or 0),
                "selected_l2_count": int(debug.get("selected_l2_count", 0) or 0),
                "selected_child_l2_count": int(debug.get("selected_child_l2_count", 0) or 0),
                "selected_l3_count": len(result.get("long_term_l3", []) or []),
                "omitted_event_count": int(debug.get("omitted_event_count", 0) or 0),
                "whether_large_l2_was_expanded_without_child_split": bool(
                    debug.get("large_l2_expanded_without_child_split", False)
                ),
                "prompt_budget_pass": not truncated,
                "retrieval_ms": round(elapsed, 3),
                "context_build_ms": 0.0,
                "generation_ms": 0.0,
                "total_ms": round(elapsed, 3),
            }
        )
        return {
            "strategy": "layered_memory",
            "query": query,
            "retrieval_mode": retrieval_mode,
            "use_llm_planner": not no_llm,
            "planner_model": effective_planner_model if not no_llm else "heuristic",
            "answer_model": model_name,
            "budget_profile": budget_profile,
            "plan": plan,
            "global_topic_map": result.get("global_topic_map", {}),
            "l1_evidence_seeds": result.get("long_term_l1", []),
            "l2_evolution_context": result.get("long_term_l2", []),
            "l3_navigation": result.get("long_term_l3", []),
            "retrieval_debug": debug,
            "formatted_prompt_context": formatted,
            "context": formatted,
            "truncated": truncated,
            "truncated_from_chars": original_chars if truncated else None,
            "metrics": metrics,
            "raw_recall_result": result,
        }
