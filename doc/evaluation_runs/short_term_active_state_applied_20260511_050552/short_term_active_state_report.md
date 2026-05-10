# Short-Term Active-State Applied Validation

- Run id: `short_term_active_state_applied_20260511_050552`
- Baseline: `doc\evaluation_runs\short_term_ablation_20260511_020452\short_term_ablation_report.json`

## Summary

- `query_count`: `8`
- `top_k_default`: `4`
- `source_preview_limit_default`: `16`
- `avg_baseline_unit_source_recall`: `0.808`
- `avg_active_source_recall`: `0.3899`
- `avg_visible_gold_recall`: `0.3408`
- `recent_short_term_avg_visible_recall`: `0.8056`
- `avg_active_selected_source_count`: `51.12`
- `avg_legacy_total_selected_source_count`: `269.5`
- `avg_context_chars`: `3310.75`

## Per Query

### VM-E01
- visible_gold_recall: `0.75` hits: `L1-0506-001, L1-0506-002, L1-0506-003`
- active_source_recall: `1.0` hits: `L1-0506-001, L1-0506-002, L1-0506-003, L1-0506-006`
- active_selected_source_count: `68` vs legacy selected source count `358`
- top units: S001(active, active=30, total=230), S006(active, active=30, total=120), S023(active, active=6, total=6), S019(active, active=2, total=2)

### VM-E02
- visible_gold_recall: `1.0` hits: `L1-0506-005, L1-0506-007, L1-0506-008, L1-0506-009, L1-0506-010`
- active_source_recall: `1.0` hits: `L1-0506-005, L1-0506-007, L1-0506-008, L1-0506-009, L1-0506-010`
- active_selected_source_count: `60` vs legacy selected source count `350`
- top units: S001(active, active=30, total=230), S006(active, active=30, total=120)

### VM-E05
- visible_gold_recall: `0.6667` hits: `L1-0506-036, L1-0506-041`
- active_source_recall: `0.6667` hits: `L1-0506-036, L1-0506-041`
- active_selected_source_count: `13` vs legacy selected source count `13`
- top units: S021(active, active=4, total=4), S020(active, active=2, total=2), S022(active, active=1, total=1), S023(active, active=6, total=6)

### VM-E08
- visible_gold_recall: `0.1667` hits: `L1-0429-013`
- active_source_recall: `0.1667` hits: `L1-0429-013`
- active_selected_source_count: `70` vs legacy selected source count `360`
- top units: S006(active, active=30, total=120), S001(active, active=30, total=230), S021(active, active=4, total=4), S023(active, active=6, total=6)

### VM-E10
- visible_gold_recall: `0.0` hits: `none`
- active_source_recall: `0.0` hits: `none`
- active_selected_source_count: `92` vs legacy selected source count `479`
- top units: S001(active, active=30, total=230), S006(active, active=30, total=120), S004(active, active=30, total=127), S020(active, active=2, total=2)

### VM-E12
- visible_gold_recall: `0.0` hits: `none`
- active_source_recall: `0.0` hits: `none`
- active_selected_source_count: `39` vs legacy selected source count `239`
- top units: S001(active, active=30, total=230), S020(active, active=2, total=2), S022(active, active=1, total=1), S023(active, active=6, total=6)

### VM-E13
- visible_gold_recall: `0.0` hits: `none`
- active_source_recall: `0.0` hits: `none`
- active_selected_source_count: `1` vs legacy selected source count `1`
- top units: S017(active, active=1, total=1)

### VM-E14
- visible_gold_recall: `0.1429` hits: `L1-0429-017`
- active_source_recall: `0.2857` hits: `L1-0429-017, L1-0506-033`
- active_selected_source_count: `66` vs legacy selected source count `356`
- top units: S001(active, active=30, total=230), S006(active, active=30, total=120), S019(active, active=2, total=2), S021(active, active=4, total=4)
