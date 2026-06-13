# ICSI Full BMR Optimization v2 Eval Pipeline Usage

This note records the sidecar-only pipeline to run immediately after all full BMR
L1 jobs complete. It does not modify canonical `share_mem/`, `long_term/l2`, or
`long_term/l3`.

## What The Pipeline Does

1. Scans `memory_outputs/icsi/runs/` for completed full BMR `filtered_share_mem`
   roots.
2. Ignores first360/probe/debug/dry-run roots.
3. Selects one latest successful filtered meeting payload per expected BMR.
4. Builds a combined effective root:
   `memory_outputs/icsi/runs/<run_id>/share_mem_effective`.
5. Runs optimization v2 L2/L3 with `optimization/long_term_v2/profiles/isci_meeting.yaml`.
6. Runs validation, topic quality audit, v2-native query curation, and retrieval diagnostics.
7. Writes a single Markdown report under `optimization/reports/`.

Known absent ICSI BMR files are `Bmr004` and `Bmr017`; the expected full set is
`Bmr001-Bmr031` minus those two files.

## Final Command After All BMRs Finish

Use this without `--allow-missing` for the final run. It should fail if any
expected completed BMR is missing.

```powershell
uv run python optimization/long_term_v2/run_icsi_full_eval_pipeline.py `
  --runs-root memory_outputs/icsi/runs `
  --effective-output-root memory_outputs/icsi/runs/bmr_full_completed29_eval_20260614 `
  --optimization-run-root optimization/runs/icsi_bmr_full_completed29_v2_20260614 `
  --report-path optimization/reports/icsi_bmr_full_completed29_eval_20260614.md `
  --clean
```

## Current Preflight

Command used:

```powershell
uv run python optimization/long_term_v2/run_icsi_full_eval_pipeline.py `
  --runs-root memory_outputs/icsi/runs `
  --effective-output-root memory_outputs/icsi/runs/bmr_full_current25_eval_preflight_20260614 `
  --optimization-run-root optimization/runs/icsi_bmr_full_current25_v2_preflight_20260614 `
  --report-path optimization/reports/icsi_bmr_full_current25_preflight_20260614.md `
  --allow-missing `
  --clean
```

Preflight result:

- effective meetings: 25
- missing meetings: `Bmr028`, `Bmr029`, `Bmr030`, `Bmr031`
- effective L1 objects: 5484
- L2 topics: 464
- L3 parents: 57
- validation severe: 0
- validation warnings: 11
- topic audit severe: 0
- topic audit warnings: 621
- retrieval diagnostic queries: 12
- avg expected L1 recall at context: 0.4722
- semantic L2 hit: 1.0
- semantic L3 hit: 1.0

Interpretation: the final pipeline is operational. Remaining risk is not the
combination/build runner; it is full-scale L2/L3 topic polish, especially broad
L2 topics and oversized child L2 topics.

## Current L2/L3 Review Targets

Largest broad L2 topics in the 25-meeting preflight:

- `annotation protocol`
- `audio processing`
- `data collection`
- `acoustic modeling`
- `data quality`
- `annotation tool`
- `forced alignment`
- `corpus design`
- `recording setup`
- `access control`

Oversized child L2 topics in the 25-meeting preflight:

- `transcriber tool`
- `participant information form`
- `speech alignment model`
- `recording session`
- `audio file`
- `data collection printout`

These should be handled by sidecar label/split review. Do not hardcode
ICSI-specific topic names into the optimization v2 core.
