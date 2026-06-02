# Optimization v2 Iteration Status - 2026-06-02 0001

## Global status

- Current certification: `optimization/reports/maturity_certification_split_pressure_20260602_0002`
- Certification status: `warning`
- Failing gates: 0
- Warning gates: `gate_12_promotion_decision`
- Promotion recommendation: `do_not_promote`
- Canonical mutation check: no tracked canonical diff after tests and scans

## What changed in this iteration

1. Added retrieval split-pressure diagnostics:
   - `optimization/long_term_v2/retrieval_split_pressure.py`
   - Ranks `needs_split_review` L2 topics by actual retrieval query hits.
   - Prevents blind splitting based only on event count.

2. Added synthetic pressure query generation:
   - `optimization/long_term_v2/make_retrieval_pressure_queries.py`
   - Generates v2-native diagnostic queries from oversized `needs_split_review` topics.
   - Outputs `retrieval_eval/pressure_queries.jsonl` and `pressure_queries_report.*` inside the run root.

3. Made retrieval eval reports auditable:
   - `optimization/long_term_v2/evaluate_retrieval.py` now records expected ids/labels and matched expected L1 ids per query.

4. Added L1 text-quality audit:
   - `optimization/long_term_v2/validate_view.py` records `validation/l1_input_audit.json.text_quality`.
   - Mojibake/private-use/replacement-char risks are warning-only, not build blockers.

## Synthetic split-pressure result

Run: `optimization/runs/synthetic_focused_split_candidate_dominance_20260602_0002`

- Generated diagnostic queries: 8
- avg_expected_obj_recall_at_context: 0.4375
- expected_l2_hit_rate: 1.0
- expected_l2_semantic_hit_rate: 1.0
- needs_split_topic_count: 13
- topics_with_retrieval_pressure_count: 8
- highest pressure topic: `L2-child-l2` with 231 events and 3 query hits
- source snapshot text-quality audit: 0 suspected mojibake objects

Interpretation:

- Topic-level retrieval works for the oversized synthetic topics.
- Broad topic queries do not recover every representative L1, so L1 recall is partial by design in this stress diagnostic.
- Split priority should now be retrieval-pressure-aware: split high-pressure topics first, leave zero-hit large topics as review/watch unless real queries hit them.
- The second-pass LLM split attempt did not safely split `L2-child-l2` or `L2-experiment-lab`; both candidate splits left oversized dominant children. Keeping them as review-only is the right conservative decision.

## Verification

- `uv run python -m unittest tests.test_optimization_long_term_v2` -> 58 tests OK
- `uv run python -m unittest discover -s tests` -> 558 tests OK
- Hardcode scan over `optimization/long_term_v2` -> no matches
- Secret scan over `optimization` and v2 tests -> no matches
- `git diff --name-only` -> no tracked file diff

## Next global step

Do not keep splitting L2 just because it is large. The next maturity work should be one of these, in order:

1. Build a small v2-native query set for synthetic and ICSI that reflects actual mentor/research-meeting questions, then rerun retrieval split pressure.
2. For high-pressure topics like `L2-child-l2`, ask the LLM for a richer multi-child taxonomy only if query pressure justifies it, and keep candidate application gated by child-size/separability.
3. Retrieval-pressure summary is now included in maturity certification as informational evidence, not as a pass/fail gate.
4. Only after repeated isolated runs stay stable should we discuss shadow-mode runtime adapter. No canonical promotion yet.
