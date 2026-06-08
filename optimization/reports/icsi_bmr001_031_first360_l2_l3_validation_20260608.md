# ICSI BMR first360 Optimization v2 L2/L3 Validation - 2026-06-08

## Scope

- Input effective share memory root:
  `memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective`
- This workspace currently contains 29 effective meetings and 1425 L1 objects, not a full 30-meeting root.
- Missing IDs in the `Bmr001..Bmr031` range are `Bmr004` and `Bmr017`.
- Canonical `share_mem/`, `long_term/l2`, and `long_term/l3` were not modified.

## Best Candidate

Best isolated optimization run:

`optimization/runs/icsi_bmr001_031_first360_l2_l3_weaklabel_llm_candidate4_20260608`

Summary:

- L1 count: 1425
- L2 topic count: 139
- Linked L1: 1395
- Unlinked L1: 30
- L3 parent count: 65
- L3 assigned L1: 1081
- Validation: severe 0, warnings 0
- Topic audit: severe 0, warnings 6, manual review items 6

Comparison to the original 29-meeting optimization baseline:

| Run | Broad L2 Review Count | Function/Weak Label Count | Score Delta | Regressions |
|---|---:|---:|---:|---|
| baseline `icsi_bmr001_031_first360_l2_l3_20260608` | 84 | 0 | 0 | - |
| weak-label deterministic fixed | 84 | 0 | 0 | - |
| LLM candidate 1 | 14 | 0 | +140 | - |
| LLM candidate 2 | 5 | 0 | +158 | - |
| LLM candidate 3 | 4 | 0 | +160 | - |
| LLM candidate 4 | 3 | 0 | +162 | - |

## Remaining Review Items

The remaining review items are intentionally not auto-promoted:

- `L2-annotation-procedure`
  - Split proposal produced child sizes 11 and 2.
  - The 2-L1 child is too small, so the apply gate rejected materialization.
- `L2-go-ahead`
  - LLM review disposition: `incoherent_no_durable_topic`.
  - The label is a discourse/action marker; linked L1 objects cover unrelated decisions and plans.
- `L2-system-performance`
  - LLM review disposition: `incoherent_no_durable_topic`.
  - Linked L1 objects discuss unrelated systems: ASR adaptation, text retrieval speed, UI loading, and Tcl execution speed.

## Generic Repairs Added

- Weak conversation phrases such as `gonna`, `read`, `allow`, `basically`, and `handle` are blocked from becoming durable L2/L3 labels.
- Focused LLM split review now requires review-only disposition:
  - `coherent_no_split`
  - `incoherent_no_durable_topic`
  - `needs_manual_review`
- Topic audit can distinguish a coherent small topic from an incoherent non-durable bucket.
- These are profile-level quality controls, not Grace/BMR-specific ontology rules.

## Verification Commands

```powershell
uv run python -m unittest tests.test_optimization_l2_l3_scaling tests.test_optimization_long_term_v2
uv run python -m unittest discover -s tests
```

Observed result:

- Targeted optimization tests: 85 tests OK
- Full suite: 611 tests OK

## Re-run Commands

Build deterministic base:

```powershell
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --out optimization/runs/icsi_bmr001_031_first360_l2_l3_weaklabel_fixed_20260608 `
  --mode deterministic `
  --clean
```

Validate and audit:

```powershell
uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_l2_l3_weaklabel_fixed_20260608

uv run python optimization/long_term_v2/audit_topic_quality.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_l2_l3_weaklabel_fixed_20260608 `
  --out optimization/runs/icsi_bmr001_031_first360_l2_l3_weaklabel_fixed_20260608/topic_quality
```

Focused split review and candidate application:

```powershell
uv run python optimization/long_term_v2/llm_split_review.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_l2_l3_weaklabel_fixed_20260608 `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --review-source optimization/runs/icsi_bmr001_031_first360_l2_l3_weaklabel_fixed_20260608/topic_quality/manual_topic_review_queue.json `
  --model gemini-2.5-pro `
  --sample-limit 8 `
  --max-sources-per-call 20

uv run python optimization/long_term_v2/apply_split_review_candidates.py `
  --source-run-root optimization/runs/icsi_bmr001_031_first360_l2_l3_weaklabel_fixed_20260608 `
  --out-root optimization/runs/icsi_bmr001_031_first360_l2_l3_weaklabel_llm_candidate_20260608 `
  --clean
```

## Current Decision

This result is safe as an isolated optimization candidate. It should not yet replace canonical runtime outputs until the actual 30-meeting root is present in this workspace and passes the same build, validation, audit, and comparison loop.
