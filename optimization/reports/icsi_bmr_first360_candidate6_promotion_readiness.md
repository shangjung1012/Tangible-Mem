# ICSI BMR First360 Candidate6 Promotion Readiness

Generated after the focused LLM split-review pass for the 30-file ICSI BMR
first360 effective L1 corpus.

## Scope

- baseline candidate: `optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609`
- new candidate: `optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609`
- effective L1 source: `memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective`
- split review sources:
  - `L2-annotation-tool`
  - `L2-data-collection`

No canonical `share_mem/`, `long_term/l2`, or `long_term/l3` artifacts were
modified.

## Focused LLM Split Review Result

The focused split-review pass used the existing optimization v2 LLM proposal
path and deterministic validation gates. The LLM did not directly mutate the
runtime view; proposals were applied only to the isolated candidate6 run after
passing source-scope, label, representative-L1, separability, and child-size
checks.

Applied splits:

- `L2-annotation-tool` -> `L3-annotation-tool-candidate-split`
  - `multi-channel waveform display`: 28 L1
  - `tool performance and workflow`: 15 L1
  - `tool integration and data processing`: 7 L1
- `L2-data-collection` -> `L3-data-collection-candidate-split`
  - `recording equipment and setup`: 30 L1
  - `data collection planning and design`: 15 L1

Split application:

- applied split count: `2`
- skipped split count: `0`

## Validation

Candidate6 validation:

- severe issues: `0`
- warnings: `0`
- L2 topics: `139`
- L3 parents: `56`
- L3 assigned L1: `986`
- runtime export: `optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609/runtime`
- runtime L2 count: `134`
- runtime L3 count: `56`

Validation report:

- `optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609/validation/l2_validation_report.json`
- `optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609/validation/l3_validation_report.json`

## Retrieval Comparison

Candidate6 did not regress from candidate5:

- `avg_expected_obj_recall_at_context`: `0.0` delta
- `expected_l2_hit_rate`: `0.0` delta
- `expected_l2_semantic_hit_rate`: `0.0` delta
- `expected_l3_hit_rate`: `0.0` delta
- `expected_l3_semantic_hit_rate`: `0.0` delta

Comparison decision:

- `candidate_shadow_ready`

Report:

- `optimization/reports/icsi_bmr_first360_candidate6_comparison/effective_topic_run_comparison.json`
- `optimization/reports/icsi_bmr_first360_candidate6_comparison/effective_topic_run_comparison.md`

## Answer-Quality Proxy

The no-LLM retrieval-quality proxy found candidate6 not worse than candidate5:

- candidate5 proxy score: `0.9128`
- candidate6 proxy score: `0.9128`
- score delta: `0.0`
- decision: `candidate_not_worse`

This is still a proxy, not final LLM answer scoring. It estimates answer quality
from retrieval recall, semantic topic hits, and source traceability.

Report:

- `optimization/reports/icsi_bmr_first360_candidate6_answer_quality/icsi_answer_quality_proxy.json`
- `optimization/reports/icsi_bmr_first360_candidate6_answer_quality/icsi_answer_quality_proxy.md`

## Promotion Decision

Decision: `candidate6_shadow_ready_for_icsi_bmr_first360`

Reasoning:

- The two remaining broad active L2 topics received evidence-backed child L2
  splits.
- The split was produced through the generic LLM split-review path, not a
  BMR-specific deterministic label map.
- Candidate6 has validation severe `0` and warning `0`.
- Retrieval metrics did not regress.
- Answer-quality proxy did not regress.
- Runtime/canonical replacement is still blocked until full answer-quality
  comparison against canonical layered memory, traditional RAG, and full
  context is completed.

## Remaining Work Before Canonical Replacement

- Run full LLM answer-quality comparison for ICSI:
  - canonical layered memory
  - optimization v2 candidate6
  - traditional RAG
  - full context
- Run the same focused split-review flow on at least one non-ICSI dataset or
  Grace-compatible run to confirm the split path does not overfit ICSI.
- Add a shadow-mode runtime adapter decision document before wiring v2 into the
  active app runtime.

Optimization v2 candidate6 is suitable for ICSI BMR first360 shadow-mode
inspection, but it should not replace the canonical runtime automatically.
