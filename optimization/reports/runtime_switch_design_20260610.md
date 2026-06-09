# Optimization V2 Runtime Switch And Rollback Design

## Decision

Optimization v2 should enter runtime only through an explicit opt-in adapter, not by moving or rewriting canonical artifacts.

Default behavior remains canonical:

- `share_mem/tree.json` remains the raw L1 evidence source.
- `long_term/l2` and `long_term/l3` remain the current production long-term view.
- `optimization/runs/<run_id>` remains an isolated candidate output.

## Switch Mechanism

Use existing runtime path resolution instead of copying files:

```text
LONG_TERM_BACKEND=optimization_v2
OPTIMIZATION_V2_RUN_ROOT=optimization/runs/<approved_run_id>
```

Expected behavior:

1. If `LONG_TERM_BACKEND` is unset, runtime uses canonical long-term artifacts.
2. If `LONG_TERM_BACKEND=optimization_v2`, runtime reads L2/L3 from `OPTIMIZATION_V2_RUN_ROOT`.
3. If the optimization run root is missing, incomplete, or invalid, runtime must fall back to canonical and report `fallback_reason`.
4. Shadow QA must verify the resolved backend before any demo or answer-quality run.

## Rollback

Rollback is a config-only action:

```text
Remove LONG_TERM_BACKEND
Remove OPTIMIZATION_V2_RUN_ROOT
```

No generated artifacts need to be deleted. Canonical `long_term/l2` and `long_term/l3` are not overwritten during the switch, so rollback does not require file restoration.

## Required Verification Before Enabling

- Shadow trace QA passes for the target dataset.
- Answer quality report passes or has an explicit accepted diagnostic boundary.
- Label polish review has no unresolved severe items for the active demo surface.
- Longer-scope ICSI validation either passes or is explicitly blocked by missing input and accepted as a scope boundary.
- Full tests pass.
- Hardcode scan passes.
- Secret scan passes.
- Git diff confirms no canonical mutation.

## Smoke Commands

Runtime path readiness:

```powershell
uv run python optimization/long_term_v2/shadow_mode_qa.py `
  --optimization-run-root optimization/runs/<approved-run> `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --out optimization/runs/<approved-run>_shadow_qa `
  --summary-out optimization/reports/<approved-run>_shadow_qa `
  --retrieval-mode lexical `
  --max-context-chars 16000
```

Answer-quality comparison:

```powershell
uv run python optimization/long_term_v2/shadow_answer_quality.py `
  --shadow-qa-report optimization/reports/<approved-run>_shadow_qa/summary.json `
  --out optimization/reports/<approved-run>_shadow_answer_quality `
  --raw-out optimization/runs/<approved-run>_shadow_answer_quality `
  --generate-answers `
  --model gemini-2.5-pro `
  --judge-model gemini-2.5-pro
```

Rollback verification:

```powershell
Remove-Item Env:LONG_TERM_BACKEND -ErrorAction SilentlyContinue
Remove-Item Env:OPTIMIZATION_V2_RUN_ROOT -ErrorAction SilentlyContinue
uv run python optimization/long_term_v2/shadow_mode_qa.py `
  --optimization-run-root optimization/runs/<approved-run> `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --out optimization/runs/<approved-run>_rollback_probe `
  --summary-out optimization/reports/<approved-run>_rollback_probe `
  --max-queries 1
```

## Promotion Boundary

`promotion_candidate` means optimization v2 is ready for controlled opt-in or shadow mode. It does not mean canonical replacement.

Canonical replacement requires a separate user-approved promotion step.
