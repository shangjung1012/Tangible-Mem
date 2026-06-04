# Canonical L2/L3 Builder Inventory

Generated during the archive-boundary review on 2026-06-05.

This inventory separates current runtime dependencies from legacy builder code
that has been archived after optimization v2 became runtime-selectable in
shadow mode.

## Runtime Dependencies To Keep Active For Now

- `long_term/recall.py`
  - Used by `app/memory_context.py`, `long_term/evaluate_retrieval.py`,
    Observatory retrieval traces, and recall tests.
  - Reads `share_mem/tree.json`, `long_term/l2/*`, and `long_term/l3/*`.
- `long_term/retrieval_profiles.py`
  - Used by app, eval, and Observatory recall paths.
- `long_term/current_state_context.py`
  - Used by app memory context for current implementation state.
- `long_term/recall_planner.py`
  - Still imported by app/eval/Observatory, even though no-LLM heuristic
    planning is the default path.
- `long_term/l2/`
  - Current canonical Grace L2 fallback sidecar.
- `long_term/l3/`
  - Current canonical Grace L3 fallback sidecar.
- `long_term/eval/`
  - Current retrieval-eval queries and baseline reports.

## Archived Builder And Validation Implementation

The implementation files now live in this archive. Root-level modules with the
same names remain as thin compatibility wrappers so old CLI commands and tests
still import successfully.

- `build_l2_view.py`
- `validate_l2_view.py`
- `validate_l3_view.py`
- `l3_promotion.py`
- `taxonomy_refinement.py`
- `topic_state.py`

## Known Reference Points

- `long_term/cli.py` dispatches `build-l2-view`, `validate-l2-view`, and
  `validate-l3-view` to root-level compatibility wrappers.
- `app/memory_context.py` defaults to canonical paths under `long_term/l2` and
  `long_term/l3`, but can select an exported optimization v2 runtime through
  `LONG_TERM_BACKEND=optimization_v2`.
- `memory_observatory/services/retrieval_trace.py` currently defaults to the
  canonical `long_term` sidecars unless fixture paths are passed explicitly.
- `tests/test_l2_view.py`, `tests/test_l3_promotion.py`,
  `tests/test_l3_validation.py`, and `tests/test_l2_taxonomy_refinement.py`
  import canonical builder wrapper modules directly.

## Next Safe Phase

Keep canonical sidecars as fallback and use exported optimization v2 runtime
sidecars for shadow comparisons. Do not delete the wrappers or canonical
sidecars until repeated optimization v2 runs pass promotion gates and the user
explicitly approves promotion discussion.
