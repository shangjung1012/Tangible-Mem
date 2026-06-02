from __future__ import annotations

from typing import Any

from optimization.long_term_v2.induce_l2_topics import induce_l2_topics


def assign_l2_topics(
    *,
    tree: dict[str, Any],
    semantic_key_index: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Assign L1 evidence to induced L2 topics.

    This wrapper keeps the assignment interface explicit even though the first
    implementation performs induction and assignment in one deterministic pass.
    """
    return induce_l2_topics(
        tree=tree,
        semantic_key_index=semantic_key_index,
        profile=profile,
    )
