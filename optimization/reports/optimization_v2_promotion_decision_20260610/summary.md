# Optimization V2 Promotion Gate Report

- promotion decision: `new_dataset_default_l2_l3`
- new dataset default L2/L3: `True`
- runtime shadow ready: `True`
- canonical replacement eligible: `False`
- legacy archive allowed: `False`
- blocking reasons: none
- warning reasons: longer_scope_not_available

## Gate Inputs

- `shadow_report_count`: `2`
- `answer_quality_report_count`: `2`
- `label_polish_decision`: `label_polish_finalized`
- `longer_icsi_decision`: `blocked_missing_input`
- `tests_passed`: `True`
- `scans_passed`: `True`
- `canonical_mutation`: `False`

## Boundary

- `new_dataset_default_l2_l3` means v2 can be the default L2/L3 pipeline for new datasets.
- `canonical_replacement_eligible` remains false until longer-scope validation and explicit user approval.
- `legacy_archive_allowed` remains false until canonical replacement is eligible.
- Canonical runtime remains unchanged until explicit user approval.
- Rollback remains config-only because this report does not move generated artifacts.
