# Canonical L2/L3 Builder Legacy Boundary

This folder marks the archive boundary for the current canonical `long_term`
L2/L3 builder. The large Grace-tuned implementation now lives here behind
thin compatibility wrappers in `long_term/`.

The root-level modules such as `long_term/build_l2_view.py` and
`long_term/validate_l2_view.py` are wrappers so existing CLI commands, tests,
and rollback workflows keep working. The app runtime still reads canonical
Grace sidecars from `long_term/l2/` and `long_term/l3/` by default.

## Why This Exists

`optimization/long_term_v2/` is now the preferred candidate pipeline for new
datasets and profile-driven L2/L3 induction. It avoids the Grace-specific
canonical label behavior that can leak into datasets such as ICSI.

The current canonical builder remains useful as:

- the Grace runtime fallback;
- a regression baseline for optimization v2;
- a historical reference for how the first active L2/L3 view was generated.

It should not be used as the primary L2/L3 path for new datasets unless a
reviewer explicitly wants to compare against the old Grace-tuned behavior.

## Archived Implementation Files

- `build_l2_view.py`
- `validate_l2_view.py`
- `validate_l3_view.py`
- `l3_promotion.py`
- `taxonomy_refinement.py`
- `topic_state.py`

## Still Active Outside This Archive

- `long_term/recall.py`
- `long_term/retrieval_profiles.py`
- `long_term/current_state_context.py`
- `long_term/recall_planner.py`
- `long_term/cli.py`
- `long_term/l2/`
- `long_term/l3/`
- `long_term/eval/`

These remain active because they are the current runtime fallback and baseline
comparison surface.

## Runtime Selection

Optimization v2 can be tested in shadow mode by exporting a runtime-compatible
view under an isolated v2 run root and setting:

```powershell
$env:LONG_TERM_BACKEND = "optimization_v2"
$env:OPTIMIZATION_V2_RUN_ROOT = "optimization/runs/<run-id>"
```

Unsetting those variables returns to canonical. If the v2 runtime export is
missing or incomplete, the app falls back to canonical automatically.

## Access

Use the root-level wrappers or `long_term/cli.py` for compatibility. Direct
imports from this archive are intended for historical inspection only. New
dataset L2/L3 work should prefer `optimization/long_term_v2/` unless a reviewer
explicitly wants to compare against the legacy Grace-tuned builder.
