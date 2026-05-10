# Short-Term Ablation Report

- Run id: `short_term_ablation_20260511_020452`
- Memory version: `7`
- Last updated meeting: `0506`
- Unit count: `10`
- Questions: `8` (VM-E01, VM-E02, VM-E05, VM-E08, VM-E10, VM-E12, VM-E13, VM-E14)

## Variant Summary

| variant | recall | precision | top1 hit | avg sources | avg chars | stale units | short-only recall | hybrid recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `current_top6` | 0.808 | 0.0087 | 0.875 | 378.375 | 3681.375 | 1.0 | 0.75 | 0.8661 |
| `no_types` | 0.808 | 0.0087 | 0.875 | 378.375 | 3681.375 | 1.0 | 0.75 | 0.8661 |
| `no_freshness` | 0.808 | 0.0087 | 0.875 | 378.375 | 3674.875 | 1.0 | 0.75 | 0.8661 |
| `recent_only` | 0.7173 | 0.0094 | 0.875 | 298.625 | 3123.375 | 0.0 | 0.75 | 0.6845 |
| `no_related_topics` | 0.619 | 0.0104 | 0.625 | 228.25 | 2969.5 | 0.375 | 0.75 | 0.4881 |
| `title_summary_only` | 0.619 | 0.0104 | 0.625 | 228.25 | 2969.5 | 0.375 | 0.75 | 0.4881 |
| `current_top3` | 0.6027 | 0.0257 | 0.875 | 266.25 | 2061.75 | 0.25 | 0.5208 | 0.6845 |
| `title_only` | 0.5104 | 0.0117 | 0.625 | 132.0 | 1041.0 | 0.0 | 0.6042 | 0.4167 |
| `recent_plus_specificity` | 0.4703 | 0.0274 | 0.25 | 138.625 | 2426.375 | 0.0 | 0.4167 | 0.5238 |
| `specificity_penalty_0_2` | 0.3453 | 0.0086 | 0.25 | 141.875 | 2658.75 | 0.5 | 0.4167 | 0.2738 |

## Current Top6 Per Query

| qid | recall | precision | top1 | selected units | source count | chars |
|---|---:|---:|---|---|---:|---:|
| VM-E01 | 1.0 | 0.0082 | S001 | S001(230), S006(120), S023(6), S019(2), S004(127) | 485 | 4459 |
| VM-E02 | 1.0 | 0.0143 | S001 | S001(230), S006(120) | 350 | 1725 |
| VM-E05 | 1.0 | 0.0081 | S021 | S021(4), S020(2), S022(1), S023(6), S004(127), S001(230) | 370 | 4889 |
| VM-E08 | 1.0 | 0.0123 | S006 | S006(120), S001(230), S021(4), S023(6), S004(127) | 487 | 4923 |
| VM-E10 | 1.0 | 0.0083 | S001 | S001(230), S006(120), S004(127), S020(2), S021(4), S022(1) | 484 | 4707 |
| VM-E12 | 0.75 | 0.0082 | S001 | S001(230), S020(2), S022(1), S023(6), S004(127) | 366 | 3771 |
| VM-E13 | 0.0 | 0.0 | S017 | S017(1) | 1 | 382 |
| VM-E14 | 0.7143 | 0.0103 | S001 | S001(230), S006(120), S019(2), S021(4), S004(127), S017(1) | 484 | 4595 |

## Notes

- Recall is measured by whether selected short-term units include the question gold L1 ids in `source_obj_ids`.
- Precision is gold hits divided by all unique `source_obj_ids` brought into context; it exposes overly broad short-term units.
- Hybrid questions are included to test whether short-term contributes to mixed recent/history queries, but they should not be interpreted as short-term-only responsibilities.