# Optimization v2 Active L2 Review Decisions Plan

## Summary

This work formalizes the ICSI 30-file active L2 review into a small, repeatable
sidecar step. The goal is to record which active topics look coherent, which
labels need human review, and which suppressed topics should remain excluded.

This is deliberately not a topic-assignment policy change. It does not mutate
raw L1 evidence, active L2/L3 outputs, canonical `share_mem/`, or canonical
`long_term/`.

## Scope

- Add a finalizer for `manual_review_active_l2/active_l2_manual_review.json`.
- Accept JSONL decisions from a reviewer or from an explicitly labeled agent
  spot-check file.
- Validate decision labels, severities, and item ids against the review queue.
- Summarize warnings/severe issues and emit JSON/Markdown reports.
- Generate a first ICSI 30-file agent spot-check report from the existing
  candidate4 run.

## Non-Goals

- Do not add BMR-specific hardcoded L2/L3 rules.
- Do not suppress, relabel, merge, or split topics automatically.
- Do not promote optimization v2 to canonical runtime.
- Do not write generated results under canonical `share_mem/` or `long_term/`.

## Review Decisions

Allowed decisions:

- `correct`
- `correct_suppressed`
- `needs_label_review`
- `too_broad_watch`
- `should_suppress`
- `needs_l3_split`
- `needs_manual_decision`

Allowed severity:

- `none`
- `warning`
- `severe`

The first report should treat label uncertainty as `warning`, not `severe`,
unless the representative L1 evidence shows a clear topic collapse or wrong
assignment.

## Validation

- Every decision must reference an item from the review queue.
- Active L2 decisions must reference `top_largest_active_l2`.
- Suppressed decisions must reference `suppressed_l2`.
- Invalid decision/severity labels must fail.
- Severe issues must make the report status `fail`.
- Warnings keep the report status `warning`.
- Zero decisions is `warning`, because no review has actually happened.

## Acceptance Criteria

- Unit tests cover invalid decisions, unknown item ids, and summary counts.
- The generated ICSI report is explicit that it is an agent spot-check, not a
  final human review.
- The report identifies follow-up targets without changing assignment logic.
- Existing optimization and memory-output isolation remains intact.
