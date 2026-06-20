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
        "top_k_raw": 80,
        "max_l1_seeds_for_prompt": 32,
        "max_global_topic_map_chars": 1200,
        "max_relevant_l2_summaries": 5,
        "max_expanded_l2_topics": 3,
        "max_sibling_child_l2_topics": 2,
        "max_events_per_l2": 10,
        "max_events_per_child_l2": 20,
        "max_events_per_sibling_child_l2": 3,
        "max_event_chars": 420,
        "prefer_materialized_l3": True,
        "topic_size_penalty": 0.03,
    },
    # Balanced preset for evolution/history questions. It leaves room for
    # cross-meeting L1 evidence and several L2/child-L2 slices without using the
    # much larger deep_layered context.
    "evolution_balanced": {
        "top_k_raw": 120,
        "max_l1_seeds_for_prompt": 16,
        "max_global_topic_map_chars": 800,
        "max_relevant_l2_summaries": 4,
        "max_expanded_l2_topics": 3,
        "max_events_per_l2": 4,
        "max_events_per_child_l2": 6,
        "max_event_chars": 180,
        "prefer_materialized_l3": True,
        "topic_size_penalty": 0.04,
    },
    # Good default for the 8-query Grace eval after L3 materialization and
    # hybrid L1 retrieval: keeps more L1 evidence seeds while staying below the
    # legacy 6000-char prompt-budget guard on all current demo queries.
    "eval_best": {
        "top_k_raw": 30,
        "max_l1_seeds_for_prompt": 12,
        "max_global_topic_map_chars": 300,
        "max_relevant_l2_summaries": 1,
        "max_expanded_l2_topics": 1,
        "max_events_per_l2": 2,
        "max_events_per_child_l2": 2,
        "max_event_chars": 100,
        "prefer_materialized_l3": True,
        "topic_size_penalty": 0.05,
    },
    # Runtime-oriented default for the app and Observatory trace. It is wider
    # than eval_best so answer quality is not dominated by token saving, but it
    # still keeps a bounded L1/L2/L3 slice instead of degenerating into full
    # context.
    "generous_layered": {
        "top_k_raw": 60,
        "max_l1_seeds_for_prompt": 24,
        "max_global_topic_map_chars": 600,
        "max_relevant_l2_summaries": 2,
        "max_expanded_l2_topics": 2,
        "max_sibling_child_l2_topics": 2,
        "max_events_per_l2": 4,
        "max_events_per_child_l2": 8,
        "max_events_per_sibling_child_l2": 3,
        "max_event_chars": 220,
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
    # Demo-oriented trace profile for Memory Observatory. It keeps the same
    # small topic fan-out as large_corpus_tight, but gives the selected timeline
    # event enough room to explain the actual method or decision being shown.
    "observatory_trace": {
        "top_k_raw": 20,
        "max_l1_seeds_for_prompt": 8,
        "max_global_topic_map_chars": 220,
        "max_relevant_l2_summaries": 1,
        "max_expanded_l2_topics": 1,
        "max_events_per_l2": 1,
        "max_events_per_child_l2": 1,
        "max_event_chars": 240,
        "prefer_materialized_l3": True,
        "topic_size_penalty": 0.05,
    },
    # Paper/screenshot-oriented Observatory profile. It keeps the same
    # evidence-first retrieval contract as the compact demo profile, but widens
    # L1 and L2/L3 context enough for reviewers to inspect actual topic
    # evolution in screenshots.
    "observatory_paper_trace": {
        "top_k_raw": 80,
        "max_l1_seeds_for_prompt": 20,
        "max_global_topic_map_chars": 900,
        "max_relevant_l2_summaries": 3,
        "max_expanded_l2_topics": 2,
        "max_sibling_child_l2_topics": 2,
        "max_events_per_l2": 4,
        "max_events_per_child_l2": 6,
        "max_events_per_sibling_child_l2": 3,
        "max_event_chars": 260,
        "prefer_materialized_l3": True,
        "topic_size_penalty": 0.05,
    },
}

PROFILE_ALIASES = {
    "tight": "large_corpus_tight",
    "large": "large_corpus_tight",
    "trace": "observatory_trace",
    "demo": "observatory_trace",
    "paper": "observatory_paper_trace",
    "deep": "deep_layered",
    "generous": "generous_layered",
    "runtime": "generous_layered",
    "evolution": "evolution_balanced",
    "balanced": "evolution_balanced",
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
