# Second-Pass Split Review: Top 3 Synthetic L2

- generated: 2026-06-01T23:14:59Z
- decision: `no_second_pass_materialization; keep review-only for these sources`
- reviewed sources: L2-child-l2, L2-decision-history, L2-experiment-lab
- accepted split proposals: 2
- review-only: 1
- rejected: 0
- applied splits: 0
- skipped splits: 2
- validation: severe=0 warnings=3
- total tokens: 16005

## Skipped Splits
- `L2-child-l2`: candidate_child_still_oversized [155, 76]
- `L2-decision-history`: candidate_child_still_oversized [178, 30]

## Interpretation
- Second-pass top3 review reduced an earlier over-splitting risk: L2-experiment-lab became review_only.
- The proposed rationale-vs-implementation splits for L2-child-l2 and L2-decision-history still leave oversized child candidates, so they should not be materialized.
- For synthetic data, many large L2s appear to reflect repeated template dimensions rather than naturally separable durable subtopics.
- Next work should evaluate retrieval pressure before attempting more splits; do not split just to reduce counts.
