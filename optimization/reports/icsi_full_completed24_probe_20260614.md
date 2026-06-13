# ICSI Full BMR Completed-24 Provisional Probe

Generated: 2026-06-14

## Scope

This is a provisional sidecar-only probe using the BMR full-transcript runs that had succeeded at the time of the check.
It does not modify canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.

Included effective L1 roots:

- `memory_outputs/icsi/runs/bmr_full_icsi_l1_bmr_full_20260610/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr002_full_icsiaccount2_20260612/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr003_full_project5fcceccd_20260612/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr006_full_icsirun_20260612/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr007_full_projectc37a_20260612/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr011_full_icsirun2_retry2_20260612/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr013_full_icsiaccount2_20260613/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr014_full_kind499219_20260613/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr015_full_kind499219_20260613/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr016_full_icsirun_smoke_20260611/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr016_031_full_parallel_20260611_actual/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr024_full_icsirun3_retry2_20260612/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr025_full_icsiaccount2_20260613/filtered_share_mem`
- `memory_outputs/icsi/runs/bmr026_full_icsiaccount2_20260613/filtered_share_mem`

Combined effective root:

```text
memory_outputs/icsi/runs/bmr_full_completed24_eval_probe_20260614/share_mem_effective
```

Optimization v2 run:

```text
optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614
```

## Pipeline Results

Effective L1:

- meetings: `24`
- L1 objects: `5278`

Optimization v2 deterministic build:

- L1 input count: `5278`
- semantic key count: `5278`
- L2 topics: `444`
- linked L1: `5244`
- unlinked L1: `34`
- L3 parents: `56`
- L3-assigned L1: `2298`

Validation:

- severe issues: `0`
- warnings: `8`
- warning types:
  - `oversized_child_l2`: `5`
  - `tiny_child_l2`: `3`

Topic audit:

- severe issues: `0`
- warnings: `594`
- major warning types:
  - `broad_l2_mixed_signatures`: `293`
  - `needs_topic_review`: `293`
  - `oversized_child_l2`: `5`
  - `tiny_child_l2`: `3`

Interpretation: the full-scale v2 build is structurally valid, but many large L2 topics still require focused topic review or split refinement before this can be used as a final ICSI benchmark.

## Retrieval Diagnostic

Generated 12 v2-native diagnostic queries from the largest L2 topics.

Retrieval eval output:

```text
optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614/optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614/retrieval_eval/native_eval/retrieval_eval_report.json
```

Summary:

- query count: `12`
- top-k L1: `60`
- average expected L1 recall: `0.5139`
- expected L2 hit rate: `1.0`
- expected L2 semantic hit rate: `1.0`
- expected L3 hit rate: `1.0`
- expected L3 semantic hit rate: `1.0`

Interpretation: topic-level routing is working, but L1 recall on large-topic diagnostic queries is only moderate. This supports the need for split review and query-specific evidence selection before running final answer-quality comparisons.

## Immediate Lessons

1. The optimization v2 pipeline scales to at least 5278 ICSI effective L1 objects without severe validation failures.
2. The L2/L3 surface is not yet polished enough for a final comparison against mem0 or AMem.
3. The most important next repair is not generic deterministic filtering; it is focused topic review/splitting for broad L2 topics such as:
   - `annotation protocol`
   - `audio processing`
   - `data collection`
   - `acoustic modeling`
   - `data quality`
4. A final ICSI benchmark should wait for all full BMR runs, then rebuild the combined effective root and rerun this same probe.

## Commands Used

Combine effective roots:

```powershell
uv run python optimization/combine_share_mem_runs.py `
  --source-root memory_outputs/icsi/runs/bmr_full_icsi_l1_bmr_full_20260610/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr002_full_icsiaccount2_20260612/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr003_full_project5fcceccd_20260612/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr006_full_icsirun_20260612/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr007_full_projectc37a_20260612/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr011_full_icsirun2_retry2_20260612/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr013_full_icsiaccount2_20260613/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr014_full_kind499219_20260613/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr015_full_kind499219_20260613/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr016_full_icsirun_smoke_20260611/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr016_031_full_parallel_20260611_actual/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr024_full_icsirun3_retry2_20260612/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr025_full_icsiaccount2_20260613/filtered_share_mem `
  --source-root memory_outputs/icsi/runs/bmr026_full_icsiaccount2_20260613/filtered_share_mem `
  --output-root memory_outputs/icsi/runs/bmr_full_completed24_eval_probe_20260614 `
  --clean
```

Build v2:

```powershell
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root memory_outputs/icsi/runs/bmr_full_completed24_eval_probe_20260614/share_mem_effective `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --out optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614 `
  --mode deterministic `
  --clean
```

Validate and audit:

```powershell
uv run python optimization/long_term_v2/validate_view.py --run-root optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614
uv run python optimization/long_term_v2/audit_topic_quality.py --run-root optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614
```

Diagnostic retrieval:

```powershell
uv run python optimization/long_term_v2/curate_v2_native_queries.py `
  --run-root optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614 `
  --topic-source largest `
  --max-queries 12

uv run python optimization/long_term_v2/evaluate_retrieval.py `
  --run-root optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614 `
  --queries optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614/retrieval_eval/v2_native_queries.jsonl `
  --share-mem-root memory_outputs/icsi/runs/bmr_full_completed24_eval_probe_20260614/share_mem_effective `
  --out optimization/runs/icsi_bmr_full_completed24_v2_probe_20260614/retrieval_eval/native_eval
```
