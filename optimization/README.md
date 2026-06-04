# Optimization Experiments

This directory is an isolated workspace for candidate memory-pipeline changes.

The code and generated artifacts under `optimization/` are intentionally kept
separate from the canonical memory artifacts:

- Do not write to `share_mem/`.
- Do not write to `long_term/l2/` or `long_term/l3/`.
- Do not connect these outputs to runtime retrieval unless a later promotion
  decision explicitly does so.

The first candidate pipeline is `optimization/long_term_v2/`. It reads immutable
L1 evidence from an existing `share_mem` root and writes side-by-side L2/L3
outputs under `optimization/runs/<run_id>/`.

## Current Maturity Repair Status

Latest reviewed deterministic Grace run:

```text
optimization/runs/grace_v2_det_rescue_20260529_065827
```

Latest maturity certification:

```text
optimization/reports/maturity_certification_delivery_20260603_0001
```

Current status: mature enough for isolated/shadow-mode evaluation, not promoted
to canonical runtime artifacts. The structural gates pass, including isolation,
Grace-specific-hardcode scan, L1 audit, semantic keys, L2/L3 validation,
retrieval quality, answer-quality scoring, ICSI robustness, related-topics
ablation, LLM proposal validation, focused split review, split-candidate
application, and the cross-dataset maturity suite. Promotion remains blocked by
policy until repeated isolated runs stay stable and the user explicitly approves
promotion discussion.

Key properties:

- L2 induction is profile-driven and evidence-driven; it does not use the
  canonical Grace L2 label map.
- L3 promotion is adaptive by topic size and does not use a hand-written source
  L2 child taxonomy.
- `related_topics` are optional source signals, not the sole assignment source.
- Retrieval-eval token equivalents are only a compatibility layer for comparing
  v2 labels against older canonical eval labels; they are not used to build L2
  or L3.
- v2-native query diagnostics are now available under
  `optimization/long_term_v2/curate_v2_native_queries.py`; split work should be
  prioritized by retrieval pressure, not raw L2 size alone.

Professor-facing delivery report:

```text
optimization/reports/professor_delivery_20260603_0001/professor_delivery_report.md
```

This report is the preferred handoff artifact for a progress update. It
summarizes the current maturity status, answer-quality comparison, cross-dataset
checks, split-review evidence, remaining risks, and a short demo flow. It says
the system is deliverable for isolated/shadow-mode evaluation, but must not be
promoted to canonical artifacts yet.

## Shadow Runtime Export

Optimization v2 can now be exported into a runtime-compatible sidecar under the
same isolated run root. This is a shadow-mode bridge only: it lets the app read
v2 L2/L3 sidecars for comparison without copying them into canonical
`long_term/l2` or `long_term/l3`.

```powershell
uv run python optimization/long_term_v2/export_runtime_view.py `
  --run-root optimization/runs/grace_v2_det_rescue_20260529_065827 `
  --clean
```

To exercise that exported view in local retrieval:

```powershell
$env:LONG_TERM_BACKEND = "optimization_v2"
$env:OPTIMIZATION_V2_RUN_ROOT = "optimization/runs/grace_v2_det_rescue_20260529_065827"
```

Unset those environment variables to return to canonical runtime artifacts.
The app falls back to canonical if the v2 runtime export is missing or
incomplete.

Rebuild command:

```powershell
uv run python optimization/long_term_v2/build_view.py --share-mem-root share_mem --profile optimization/long_term_v2/profiles/mentor_mentee.yaml --out optimization/runs/grace_v2_20260528_001 --mode deterministic --clean
uv run python optimization/long_term_v2/validate_view.py --run-root optimization/runs/grace_v2_20260528_001
uv run python optimization/long_term_v2/compare_with_baseline.py --run-root optimization/runs/grace_v2_20260528_001 --baseline-l2-root long_term/l2 --baseline-l3-root long_term/l3 --share-mem-root share_mem
uv run python optimization/long_term_v2/evaluate_retrieval.py --run-root optimization/runs/grace_v2_20260528_001 --queries long_term/eval/long_term_retrieval_queries.jsonl --share-mem-root share_mem
```

Maturity repair commands:

```powershell
uv run python optimization/long_term_v2/validate_llm_proposals.py `
  --run-root optimization/runs/grace_v2_llm_20260529_033006 `
  --profile optimization/long_term_v2/profiles/mentor_mentee.yaml

uv run python optimization/long_term_v2/run_maturity_suite.py `
  --suite-root optimization/runs/maturity_suite_<timestamp> `
  --datasets-json <dataset-configs.json> `
  --clean

uv run python optimization/long_term_v2/maturity_certification.py `
  --grace-run-root optimization/runs/grace_v2_det_20260529_033006 `
  --grace-llm-run-root optimization/runs/grace_v2_llm_20260529_033006 `
  --icsi-run-root optimization/runs/icsi_v2_det_20260529_033006 `
  --ablation-run-root optimization/runs/grace_v2_no_related_det_20260529_033006 `
  --suite-root optimization/runs/maturity_suite_20260529_044200 `
  --core-root optimization/long_term_v2 `
  --out optimization/reports/maturity_certification_<timestamp>
```

Professor delivery report command:

```powershell
uv run python optimization/long_term_v2/make_professor_delivery_report.py `
  --certification-report optimization/reports/maturity_certification_delivery_20260603_0001/maturity_certification_report.json `
  --v2-native-diagnostics optimization/reports/v2_native_query_diagnostics_20260603_0001.json `
  --out optimization/reports/professor_delivery_20260603_0001
```
