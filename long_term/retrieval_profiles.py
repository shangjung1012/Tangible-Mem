"""Named deterministic retrieval budget profiles.

Profiles are optional presets for evaluation and demos. They do not change the
default recall behavior unless a caller explicitly selects one.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_RETRIEVAL_BUDGET_PROFILE = "default"

RETRIEVAL_BUDGET_PROFILES: dict[str, dict[str, Any]] = {
    "default": {
        "top_k_raw": 30,
        "max_l1_seeds_for_prompt": 8,
        "max_global_topic_map_chars": 800,
        "max_relevant_l2_summaries": 3,
        "max_expanded_l2_topics": 2,
        "max_events_per_l2": 6,
        "max_events_per_child_l2": 8,
        "max_event_chars": 280,
        "prefer_materialized_l3": True,
        "topic_size_penalty": 0.05,
    },
    "deep_layered": {
        "top_k_raw": 60,
        "max_l1_seeds_for_prompt": 16,
        "max_global_topic_map_chars": 1200,
        "max_relevant_l2_summaries": 4,
        "max_expanded_l2_topics": 3,
        "max_events_per_l2": 10,
        "max_events_per_child_l2": 12,
        "max_event_chars": 420,
        "prefer_materialized_l3": True,
        "topic_size_penalty": 0.03,
    },
    # Good default for the 8-query Grace eval after L3 materialization:
    # preserves L1/L2/L3 hits while avoiding large timeline injection.
    "eval_best": {
        "top_k_raw": 20,
        "max_l1_seeds_for_prompt": 8,
        "max_global_topic_map_chars": 300,
        "max_relevant_l2_summaries": 1,
        "max_expanded_l2_topics": 1,
        "max_events_per_l2": 2,
        "max_events_per_child_l2": 2,
        "max_event_chars": 100,
        "prefer_materialized_l3": True,
        "topic_size_penalty": 0.05,
    },
    # Use for large synthetic or future larger corpora where context should stay
    # RAG-competitive without sacrificing recall. This is not a hard character
    # cap; guard it against both retrieval quality and RAG context size before
    # promoting it as a runtime default for any dataset.
    "large_corpus_tight": {
        "top_k_raw": 20,
        "max_l1_seeds_for_prompt": 8,
        "max_global_topic_map_chars": 220,
        "max_relevant_l2_summaries": 1,
        "max_expanded_l2_topics": 1,
        "max_events_per_l2": 1,
        "max_events_per_child_l2": 1,
        "max_event_chars": 80,
        "prefer_materialized_l3": True,
        "topic_size_penalty": 0.05,
    },
}

PROFILE_ALIASES = {
    "tight": "large_corpus_tight",
    "large": "large_corpus_tight",
    "deep": "deep_layered",
}


def profile_names() -> list[str]:
    return sorted(RETRIEVAL_BUDGET_PROFILES)


def get_retrieval_budget_profile(name: str | None) -> dict[str, Any]:
    key = (name or DEFAULT_RETRIEVAL_BUDGET_PROFILE).strip()
    key = PROFILE_ALIASES.get(key, key)
    if key not in RETRIEVAL_BUDGET_PROFILES:
        valid = ", ".join(profile_names() + sorted(PROFILE_ALIASES))
        raise ValueError(f"Unknown retrieval budget profile '{name}'. Valid profiles: {valid}")
    return deepcopy(RETRIEVAL_BUDGET_PROFILES[key])


def profile_to_grid(profile: dict[str, Any]) -> dict[str, list[Any]]:
    """Convert a single profile to the grid shape expected by eval runner."""
    return {key: [value] for key, value in profile.items()}
