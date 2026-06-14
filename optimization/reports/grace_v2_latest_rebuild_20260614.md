# Grace Optimization v2 Latest Rebuild - 2026-06-14

## Scope

This rebuild refreshes Grace L2/L3 using the isolated optimization v2 pipeline.
It does not rerun Grace L1 extraction and does not modify canonical
`share_mem/`, `long_term/l2`, or `long_term/l3` artifacts.

## Run Roots

- optimization run: `optimization/runs/grace_v2_latest_20260614`
- retrieval eval: `optimization/runs/grace_v2_latest_20260614/retrieval_eval/latest_commit`
- shadow QA report: `optimization/reports/grace_shadow_qa_grace_v2_latest_20260614`
- shadow answer-quality report: `optimization/reports/grace_shadow_answer_quality_grace_v2_latest_20260614`

## Build Summary

| Metric | Value |
|---|---:|
| source L1 count | 448 |
| semantic key count | 448 |
| L2 topic count | 49 |
| linked L1 count | 440 |
| unlinked L1 count | 8 |
| L3 parent count | 3 |
| L3 assigned L1 count | 71 |

## Validation

- severe issues: 0
- warnings: 2
- warning details:
  - `L2-debugging`: single-L1 topic
  - `L2-experimental-setup`: single-L1 topic

These are review warnings, not blocking validation failures.

## Retrieval Eval

| Metric | Value |
|---|---:|
| query count | 8 |
| avg expected L1 recall | 0.9219 |
| expected L2 exact hit rate | 0.25 |
| expected L2 semantic hit rate | 1.0 |
| expected L3 exact hit rate | 0.625 |
| expected L3 semantic hit rate | 1.0 |

Exact L2/L3 hit is lower because optimization v2 induces its own topic IDs
instead of copying canonical Grace topic IDs. Semantic topic hit is the relevant
compatibility signal for v2.

## Shadow QA

- decision: `shadow_qa_pass`
- query count: 8
- shadow trace ready: 8
- needs review: 0
- average context tokens:
  - canonical: 8608.125
  - optimization_v2: 8453.125
- average latency ms:
  - canonical: 258.1971
  - optimization_v2: 255.9265

## Shadow Answer Quality

- decision: `answer_quality_pass`
- query count: 8
- row count: 16
- reason codes: none
- average overall score:
  - canonical: 0.9643
  - optimization_v2: 0.9384
- source traceability:
  - canonical: 1.0
  - optimization_v2: 1.0
- hallucination risk:
  - canonical: 0.0
  - optimization_v2: 0.0

The optimization backend is slightly lower on topic evolution and completeness
in this scored smoke run, but still passes the configured shadow answer-quality
gate and keeps grounding/traceability intact.

## Canonical Safety

- Grace L1 was not rebuilt.
- Canonical `share_mem/`, `long_term/l2`, and `long_term/l3` were not modified.
- All generated artifacts are under `optimization/runs/` or
  `optimization/reports/`.
