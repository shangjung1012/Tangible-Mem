# Short-Term Ablation Manual Analysis

Run: `short_term_ablation_20260511_020452`

Input:

- Memory: `short_term/short_term_memory.json`
- Questions: `doc/evaluation_questions_0307_0506.csv`
- Selected questions: `VM-E01`, `VM-E02`, `VM-E05`, `VM-E08`, `VM-E10`, `VM-E12`, `VM-E13`, `VM-E14`

## Executive Summary

The current short-term retriever is useful as a compact "current working state"
surface, but the current unit granularity is too broad for evidence-grounded
retrieval.

The headline metric is misleading:

- `current_top6` unit-source recall is high: `0.808`.
- But source precision is very low: `0.0087`.
- The selected context pulls an average of `378.375` unique source L1 ids through
  only a few broad S-units.
- Actual visible gold L1 recall in the formatted prompt is only about `0.146`
  with the current formatter, because each S-unit displays only the first 8
  `source_obj_ids`.

So the current short-term path often finds the right broad unit, but it does not
reliably expose the specific evidence ids inside the prompt.

## Best Current Variant

`current_top6` is still the best existing variant if the goal is broad recall:

- avg gold recall: `0.808`
- short-term-only avg recall: `0.75`
- hybrid expected avg recall: `0.8661`
- top1 hit rate: `0.875`

However, this comes from oversized units:

- `S001`: 230 source L1 ids
- `S004`: 127 source L1 ids
- `S006`: 120 source L1 ids

These units are too large to be considered clean evidence-level short-term
memory.

## Feature Ablation Findings

1. `types` currently add almost no measurable value.
   - `current_top6` and `no_types` are identical on all aggregate metrics.
   - This suggests `types` are not driving ranking in the current query set.

2. The freshness boost is also not decisive.
   - `current_top6` and `no_freshness` have the same recall and precision.
   - Current ranking is dominated by text overlap, not missed-meeting count.

3. `related_topics` matter for hybrid/cross-meeting queries.
   - Removing them drops overall recall from `0.808` to `0.619`.
   - Hybrid expected recall drops from `0.8661` to `0.4881`.
   - Keep `related_topics` in scoring.

4. `title_only` is too weak.
   - It reduces context size substantially, but recall drops to `0.5104`.
   - It misses `VM-E12`, `VM-E13`, and `VM-E14` entirely.

5. A simple source-count specificity penalty is too aggressive.
   - `specificity_penalty_0_2` drops recall to `0.3453`.
   - It avoids large units, but loses the correct broad topic units.
   - Do not solve overbroad short-term memory only by penalizing large units.

## Formatter / Evidence Visibility Issue

The current formatter prints only the first 8 `source_obj_ids` for each selected
unit. For large units, those ids are often old or unrelated to the query.

Measured visible-gold recall with the actual formatted context:

- `VM-E01`: `0.25`
- `VM-E02`: `0.0`
- `VM-E05`: `0.6667`
- `VM-E08`: `0.0`
- `VM-E10`: `0.0`
- `VM-E12`: `0.25`
- `VM-E13`: `0.0`
- `VM-E14`: `0.0`

Average visible recall: about `0.146`.

This is the biggest short-term retrieval weakness found in this ablation.

## Source Preview Ablation

I tested source-preview alternatives without changing code:

- current first 8 ids per unit: avg visible recall about `0.177`
- newest 8 ids per unit: avg visible recall about `0.174`
- query-ranked 8 source ids per unit: avg visible recall about `0.275`
- query-ranked 24 source ids per unit: avg visible recall about `0.3896`
- query-ranked 40 source ids per unit: avg visible recall about `0.4313`

Query-ranked source preview helps, but does not fully fix the issue because the
underlying units are still too broad.

## Per-Question Notes

### VM-E01

The right broad unit is `S001`, and it contains most gold ids. But `L1-0506-001`,
`L1-0506-002`, and `L1-0506-003` are hidden inside a 230-id source list and do
not appear in the current prompt preview. The answer can still be supported by
the S001 summary, but evidence traceability is weak.

### VM-E02

`S001` contains all gold ids for the unresolved segmentation issues. The
formatted prompt exposes none of them. This is a false sense of evidence recall.

### VM-E05

This is the strongest short-term case. `S021` is specific and only has 4 source
ids, so the prompt exposes real evidence about importance, activation, and
decay. The remaining gold ids are split across `S023` and `S001`.

### VM-E08

`S006` is relevant to evaluation, but it has 120 source ids. The unit is useful
for broad current evaluation state, but weak for precise evidence grounding.
This should lean on long-term L1/L2 rather than short-term alone.

### VM-E10

The query asks about short-term and long-term update relationship. `S001` hits
the gold source ids, but `S006` and `S004` also rank high because they contain
broad memory/system terms. The short-term context is noisy here.

### VM-E12

The question is really a long-term design-history question with some current
state. Short-term alone should not be expected to fully answer it.

### VM-E13

Current short-term retrieval fails, but this is acceptable behavior. Speaker
diarization is an older preprocessing assumption, not a current active
short-term item. It belongs in long-term.

### VM-E14

Fade-out and demo value are hybrid/long-term questions. Short-term gives some
current framing but not enough precise evidence.

## Recommendation

Do not change the scoring formula yet. The largest problem is not the ranking
weights. It is short-term unit granularity plus source evidence preview.

Recommended next fixes:

1. Keep `related_topics` in scoring.
2. Do not add a generic source-count penalty yet.
3. Change formatter/source preview to select query-relevant source L1 ids, not
   the first 8 ids.
4. Add `source_count` and `visible_source_count` diagnostics to the formatted
   context or structured output.
5. Add a warning when selected unit `source_count > 80`.
6. In the next short-term update pipeline revision, split broad units like
   `S001`, `S004`, and `S006` into smaller active-state units.
7. Keep short-term as compact current state; use long-term L1/L2 for evidence
   grounding on historical or cross-meeting questions.

## Verdict

Short-term is directionally useful, but not mature enough as an evidence
retrieval layer by itself.

It is currently strongest as a high-level current-state supplement. For
evidence-grounded answers, the system should continue to rely on long-term L1
evidence and L2/L3 context, while short-term contributes compact recent framing.
