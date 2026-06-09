# Optimization V2 Promotion Gate Report

- promotion decision: `do_not_promote`
- blocking reasons: answer_quality_not_pass, longer_icsi_not_pass_or_accepted
- warning reasons: label_polish_review_needed

## Gate Inputs

- `shadow_report_count`: `2`
- `answer_quality_report_count`: `2`
- `label_polish_decision`: `label_polish_review_needed`
- `longer_icsi_decision`: `blocked_missing_input`
- `tests_passed`: `True`
- `scans_passed`: `True`
- `canonical_mutation`: `False`

## Boundary

- `promotion_candidate` is not automatic canonical promotion.
- Canonical runtime remains unchanged until explicit user approval.
- Rollback remains config-only because this report does not move generated artifacts.
