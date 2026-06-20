# Optimization v2

`optimization/` is the isolated workspace for the evidence-driven L2/L3 pipeline
used to evaluate new datasets and shadow-mode runtime behavior.

It must stay separate from canonical memory artifacts:

- do not write to `share_mem/`;
- do not overwrite `long_term/l2/` or `long_term/l3/`;
- do not treat an optimization run as canonical replacement unless a separate
  promotion decision explicitly says so.

## Current Status

Current working status for paper/demo preparation:

- `optimization v2` is the preferred L2/L3 builder for new datasets such as
  ICSI.
- Canonical `long_term/l2` and `long_term/l3` remain the legacy/Grace runtime
  baseline.
- Runtime can inspect exported v2 sidecars through `LONG_TERM_BACKEND`, but
  canonical replacement is not claimed.
- ICSI L2/L3 should use effective/filtered L1 roots, not raw archived
  `share_mem` roots.

Recent compact evidence:

- Grace v2 run: `optimization/runs/grace_v2_latest_20260614`
- Grace shadow QA: `optimization/reports/grace_shadow_qa_grace_v2_latest_20260614`
- Grace answer-quality smoke:
  `optimization/reports/grace_shadow_answer_quality_grace_v2_latest_20260614`
- ICSI v2 run: `optimization/runs/icsi_bmr_full_completed29_v2_20260614`
- ICSI revised retrieval comparison:
  `optimization/reports/icsi_bmr_full_completed29_system_comparison_revised_20260614`
- TAICHI implementation/decision catalog:
  `optimization/reports/optimization_v2_decision_catalog_20260615.pdf`

Discarded or wrong-project reports must not be used as evidence. In particular,
`optimization/reports/grace_l2_l3_ablation_20260614_speech494618_discarded/`
contains `DO_NOT_USE_wrong_project.txt`.

## What v2 Claims

Safe claims:

- L2 induction is profile-driven and evidence-driven.
- L3 promotion is adaptive by topic size and split quality, not a hand-written
  source-L2 child taxonomy.
- `related_topics` are optional source signals, not the only assignment source.
- Sidecar topic polish and feedback do not mutate raw L1 evidence.
- For ICSI, v2 avoids the Grace-specific ontology risk in the canonical
  long-term builder.

Do not claim:

- v2 is a final canonical replacement.
- v2 outperforms every RAG/full-context setup on final generated answers.
- L2/L3 topic induction is perfect or fully domain-general.
- ICSI held-out retrieval comparison is a paid answer-quality benchmark.

## Standard Commands

Build and validate Grace v2:

```powershell
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root share_mem `
  --profile optimization/long_term_v2/profiles/mentor_mentee.yaml `
  --out optimization/runs/grace_v2_latest_local `
  --mode deterministic `
  --clean

uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/grace_v2_latest_local
```

Build and validate ICSI v2 from an effective L1 root:

```powershell
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root memory_outputs/icsi/runs/<run>/share_mem_effective `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --out optimization/runs/icsi_v2_latest_local `
  --mode deterministic `
  --clean

uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/icsi_v2_latest_local
```

Export a v2 run for shadow runtime inspection:

```powershell
uv run python optimization/long_term_v2/export_runtime_view.py `
  --run-root optimization/runs/<approved-run> `
  --clean
```

Use a v2 runtime export:

```powershell
$env:LONG_TERM_BACKEND = "optimization_v2"
$env:OPTIMIZATION_V2_RUN_ROOT = "optimization/runs/<approved-run>"
```

Unset those variables to return to canonical runtime artifacts.

## TAICHI Relevance

For the TAICHI paper, optimization v2 should be framed as implementation support
for inspectable memory:

- it provides evidence-backed topic context for the Observatory;
- it produces sidecar artifacts that can be inspected and corrected;
- it lets the system show why an L1 seed expands into L2/L3 context;
- it supports new-dataset demonstrations without contaminating canonical Grace
  artifacts.

The paper should emphasize inspectability, traceability, and non-destructive
correction rather than algorithmic superiority.
