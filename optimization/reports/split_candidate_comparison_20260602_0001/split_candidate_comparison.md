# Split Candidate Comparison

- generated: 2026-06-01T22:56:51Z
- decision: `keep_candidate_isolated; do_not_promote`

## Metrics

| run | severe | warnings | L3 parents | source needs_split | child needs_split | needs_merge |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0 | 3 | 1 | 14 | 0 | 1 |
| candidate | 0 | 3 | 2 | 13 | 0 | 1 |

## Focused Review
- accepted split: 3
- review-only: 11
- rejected: 0
- total tokens: 41378

## Candidate Application
- applied: 1
- skipped: 2
- applied `L2-agentic-pipeline` as `L3-agentic-pipeline-candidate-split` with child sizes {'agentic pipeline architecture': 27, 'agentic pipeline performance & evaluation': 16}
- skipped `L2-child-l2`: candidate_child_still_oversized [94, 137]
- skipped `L2-experiment-lab`: candidate_child_still_oversized [4, 213]

## Interpretation
- Focused split-review is useful as a proposal/review gate.
- Only one accepted split was materialized after deterministic size/separability gates.
- Candidate reduced source needs_split_review from 14 to 13 without increasing validation warnings.
- The skipped splits need child-level evidence or more granular proposal before materialization.
