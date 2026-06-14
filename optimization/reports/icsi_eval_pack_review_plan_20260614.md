# ICSI Held-Out Eval Pack Review Plan

## Goal

Convert the generated 20-question ICSI held-out future-meeting eval pack into a smaller, auditable candidate benchmark by marking each question as accepted, revise, or reject.

## Inputs

- Eval pack: `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/heldout_eval_queries.jsonl`
- Human-readable pack: `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/heldout_eval_pack.md`
- Source-only evidence root: `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/source_share_mem`
- Retrieval diagnostic: `optimization/runs/icsi_bmr_full_completed29_v2_20260614/retrieval_eval/heldout_future_eval/retrieval_eval_report.json`

## Review Criteria

Each candidate question is reviewed on four dimensions:

1. **Answerability**
   - The source-side evidence through `Bmr023` must contain enough information to answer.
   - Held-out evidence after `Bmr023` is only a trigger, not answer evidence.

2. **Label Quality**
   - The expected L2 label should be a durable topic, not a filler phrase, discourse marker, type-like label, or overly generic bucket.

3. **Retrieval Readiness**
   - Strong candidate: expected L1 recall >= `0.75`.
   - Usable with caution: expected L1 recall between `0.5` and `0.75`.
   - Needs revision: expected L1 recall below `0.5`, unless the query is intentionally difficult and the topic hit is still useful.

4. **Benchmark Value**
   - Keep a mix of evidence lookup, evolution, rationale, carryover, and corpus/process questions.
   - Prefer questions that are realistic for a future-meeting memory assistant.

## Output

The review writes:

- `review_decisions.jsonl`
- `approved_heldout_eval_queries.jsonl`
- `final_eval_pack_review_report.json`
- `final_eval_pack_review_report.md`

## Decision Policy

- `accept`: keep as-is for candidate answer-quality comparison.
- `revise`: keep as a useful topic but rewrite or narrow before final scoring.
- `reject`: remove from the approved query subset.

This is an agent pre-review, not final human approval. Professor-facing claims still require human review.
