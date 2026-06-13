# ICSI BMR Full Optimization v2 Evaluation Pipeline

This is a sidecar-only pipeline output. It reads filtered effective L1 roots and does not modify canonical `share_mem/` or `long_term/` artifacts.

## Inputs

- effective meetings: 29
- effective L1 objects: 6233
- missing expected meetings: none
- combined effective root: `memory_outputs\icsi\runs\bmr_full_completed29_eval_20260614\share_mem_effective`

## Optimization v2 Build

- run root: `optimization\runs\icsi_bmr_full_completed29_v2_20260614`
- L1 count: 6233
- L2 topics: 530
- L3 parents: 65
- linked L1: 6203
- unlinked L1: 30

## Validation

- severe: 0
- warnings: 9
- topic audit severe: 0
- topic audit warnings: 703
- topic manual review items: 703

## Retrieval Diagnostic

- generated native queries: 12
- avg expected L1 recall: 0.4861
- expected L2 semantic hit: 1.0
- expected L3 semantic hit: 1.0

## Next Review Targets

Inspect large or broad L2/L3 topics before claiming final ICSI benchmark quality. This runner intentionally prepares the evidence and diagnostics, but does not auto-promote generated topics.
