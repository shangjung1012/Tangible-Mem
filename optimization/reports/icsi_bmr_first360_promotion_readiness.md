# ICSI BMR First360 Optimization v2 Promotion Readiness

Generated after the candidate4 -> candidate5 side-by-side review pass.

## Scope

This report covers the 30-file ICSI BMR first360 effective L1 root and the
optimization v2 candidate run:

- baseline: `optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4`
- candidate: `optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609`
- effective L1 source: `memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective`

No canonical `share_mem/`, `long_term/l2`, or `long_term/l3` artifacts were
modified.

## Candidate4 Baseline

The active L2 agent spot-check found:

- reviewed items: `25`
- severe issues: `0`
- warning issues: `10`
- key warnings:
  - `L2-annotation-tool`: needs L3/split review
  - `L2-data-collection`: needs L3/split review
  - `L2-participant-consent`: label review
  - `L2-ti-digit`: label review
  - `L2-meeting-agenda`, `L2-annotation-process`, `L2-system-performance`: manual decision

Baseline freeze:

- `optimization/reports/icsi_bmr_first360_candidate4_baseline_freeze.json`

## Candidate5 Changes

Candidate5 is an isolated candidate run. It applied only label refinements:

- `L2-participant-consent`: `participant consent` -> `status background metadata`
- `L2-ti-digit`: `ti digit` -> `ti digit dataset`

Candidate5 did not materialize split candidates. The focused split proposal
report produced candidate children, but the labels still require human review.
The application step intentionally skipped `sidecar_review_required` split
proposals to avoid artificial child L2 topics.

Split proposal artifacts:

- `optimization/reports/icsi_bmr_first360_active_l2_split_candidates/active_l2_split_candidates.json`
- `optimization/reports/icsi_bmr_first360_active_l2_split_candidates/active_l2_split_candidates.md`

## Validation Result

Candidate5 validation:

- severe issues: `0`
- warnings: `0`
- L2 topics: `139` raw / `134` effective active
- L3 parents: `56`
- L3 assigned L1: `986`
- runtime export canonical mutation flag: `false`

Runtime export:

- `optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609/runtime`

## Retrieval Comparison

Candidate5 did not regress from candidate4:

- average expected L1 recall delta: `0.0`
- expected L2 hit delta: `0.0`
- expected L2 semantic hit delta: `0.0`
- expected L3 hit delta: `0.0`
- expected L3 semantic hit delta: `0.0`

Comparison decision:

- `candidate_kept_isolated`

Report:

- `optimization/reports/icsi_bmr_first360_candidate5_comparison/effective_topic_run_comparison.json`
- `optimization/reports/icsi_bmr_first360_candidate5_comparison/effective_topic_run_comparison.md`

## Answer-Quality Proxy

The no-LLM retrieval-quality proxy found candidate5 not worse than candidate4:

- candidate4 proxy score: `0.9128`
- candidate5 proxy score: `0.9128`
- score delta: `0.0`
- decision: `candidate_not_worse`

This is not full answer scoring. It estimates answer quality from retrieval
recall, semantic topic hits, and source traceability. Full-context and RAG
comparison should still be done before making final claims.

Report:

- `optimization/reports/icsi_bmr_first360_answer_quality/icsi_answer_quality_proxy.json`
- `optimization/reports/icsi_bmr_first360_answer_quality/icsi_answer_quality_proxy.md`

## Remaining Issues

Candidate5 is better as a label-clarity candidate, but it is not a full
promotion candidate yet.

Remaining warnings:

- `L2-annotation-tool` still needs focused L3/split review. Deterministic split
  candidates produced child labels such as `shape file`, `multi channel`, and
  `new segmentation procedure`; these are plausible but not mature enough for
  automatic materialization.
- `L2-data-collection` still needs focused L3/split review. Deterministic split
  candidates contained weak labels such as `graduate student`, `head mounted`,
  and `wired wireless`; this should be reviewed by a human or a focused LLM
  split-review pass before applying.
- `L2-meeting-agenda`, `L2-annotation-process`, and `L2-system-performance`
  still need explicit human decisions.

## Promotion Decision

Decision: `candidate5_kept_isolated`

Reasoning:

- Candidate5 improves two misleading labels.
- Candidate5 has no validation regression.
- Candidate5 retrieval metrics are unchanged from candidate4.
- Candidate5 runtime export is available for shadow-mode inspection.
- Candidate5 does not solve the split warnings, because split candidates remain
  review-required.
- Full answer-quality comparison against full context and RAG has not been run
  yet.

Optimization v2 should remain isolated. It is appropriate for continued ICSI
L2/L3 development and shadow-mode experiments, but it should not replace the
canonical runtime yet.
