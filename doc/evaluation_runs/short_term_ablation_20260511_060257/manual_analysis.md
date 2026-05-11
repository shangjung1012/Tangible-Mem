# Short-Term Ablation Manual Analysis

Run: `short_term_ablation_20260511_060257`

This run compares three forced variants on eight short-term or hybrid questions:

- `short_only`: short-term context only.
- `long_only`: long-term L1/L2/L3 context only.
- `short_plus_long`: app-style budget split between short-term and long-term.

All variants used `gemini-2.5-pro` for answer generation and a `4000` character
context budget per variant.

## Aggregate Result

| variant | avg gold recall | avg context tokens | truncation rate |
|---|---:|---:|---:|
| `short_only` | 0.3408 | 845.8 | 0.875 |
| `long_only` | 0.2375 | 1607.6 | 1.0 |
| `short_plus_long` | 0.3021 | 1231.4 | 1.0 |

The metric result says short-term helps, but the answer-level result is more
nuanced. Short-term is strongest for current-state questions about recent 0506
work. It is weak for historical design questions and can add noise when broad
S-units are selected.

## Manual Verdict

Short-term should remain a supplement, not the primary evidence layer.

It is useful when the question asks for current active state, recent unresolved
issues, or the latest working framing. It should not be expected to answer
cross-meeting history by itself. Long-term remains the better source for
evidence-grounded evolution and old decisions.

The best production behavior is still `short_plus_long`, but only when the
budget split leaves enough room for long-term evidence. In this run,
`short_plus_long` often underperformed because both sections were truncated.

## Per-Question Notes

### VM-E01: Current transcript segmentation pipeline

`short_only` and `short_plus_long` both recovered the main recent pipeline:
Context Planner -> Segment Agent -> idea-unit candidates -> L1 memory. `long_only`
was also good, but short-term added compact current-state framing.

Verdict: short-term helps.

### VM-E02: Current segmentation risks

`short_only` hit all gold L1 ids and correctly surfaced repair, incomplete
fragments, coverage, and evaluation framing. `long_only` gave a more detailed
topic-tree explanation of adaptive segmentation, gap, coverage, and repair.
`short_plus_long` was the best answer overall because it combined both.

Verdict: short-term helps, hybrid is best.

### VM-E05: Importance / activation / recency / relevance

`short_only` was strong because S021 is a specific current-state unit. It gave
the correct distinction between static importance and dynamic activation /
recency / relevance. `long_only` gave richer historical evolution, and
`short_plus_long` was the most complete.

Verdict: short-term helps, hybrid is best.

### VM-E08: Evaluation plan evolution

`short_only` only captured the 0429 current evaluation framework and missed the
0318 paper-review side. `long_only` captured the cross-meeting evolution better.
`short_plus_long` was useful but still lost some gold evidence because the
context was truncated.

Verdict: long-term is primary; short-term is only supplementary.

### VM-E10: STM/LTM update relationship

`short_only` answered mostly about transcript segmentation and could not explain
the STM/LTM relationship. `long_only` gave the clearest answer about independent
updates, abandoned STM-to-LTM transfer, and the differences between STM and LTM.
`short_plus_long` included more context but mixed in older conflicting details.

Verdict: long-term wins.

### VM-E12: Update vs retrieve

`short_only` explained recent update mechanics and labels but did not recover
the older update-first to retrieval-focus design shift. `long_only` was better
for this cross-meeting history. `short_plus_long` was acceptable but truncated.

Verdict: long-term wins.

### VM-E13: Speaker diarization

All variants correctly said current context is insufficient or that speaker
diarization is not in the active short-term surface. This is acceptable:
speaker diarization is an old preprocessing issue and should not be forced into
short-term current state.

Verdict: short-term correctly does not over-answer.

### VM-E14: Fade-out and old memory retrieval

`short_only` did not have enough fade-out detail. `long_only` and
`short_plus_long` correctly explained inactive/fade-out memory, explicit
retrieval, and why this differs from ordinary RAG.

Verdict: long-term is primary; short-term can add demo framing only.

## Issues Found

1. The `4000` char budget is too tight for `short_plus_long` on hybrid questions.
   Both sections are often truncated, so the combined variant may lose the exact
   gold L1 ids even when each layer can retrieve useful context separately.

2. Broad short-term units still create noise. S001 and S006 are useful summaries,
   but they contain many source L1 ids and can dominate unrelated memory queries.

3. Short-term retrieval is stronger after query-ranked source previews, but it
   still needs better unit granularity. The fix should be in the short-term
   update/merge layer, not only retrieval scoring.

4. For explicitly historical questions, the router should keep long-term
   dominant. Short-term should be capped as recent-state framing.

## Recommendation

Keep the current direction:

- short-term = compact active/recent state
- long-term = evidence-grounded history and topic evolution
- hybrid = default for recent plus historical questions

Next improvement should be budget-aware hybrid formatting:

- reserve enough space for long-term L1 evidence on hybrid questions;
- reduce short-term to top 1-2 relevant S-units when the query has strong
  historical/evolution wording;
- keep full short-term context only for clearly current-state questions.
