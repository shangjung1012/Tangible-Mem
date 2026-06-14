# ICSI Topic Polish And Evaluation Plan

This plan is intentionally narrow. It improves the already-delivered full BMR
optimization-v2 sidecar artifacts without rerunning L1 and without modifying
canonical Grace artifacts.

## Inputs

- Final effective L1 root:
  `memory_outputs/icsi/runs/bmr_full_completed29_eval_20260614/share_mem_effective`
- Final optimization v2 run:
  `optimization/runs/icsi_bmr_full_completed29_v2_20260614`

## Goal 1: L2/L3 Topic Polish

The raw final run has structurally valid topics, but its raw L3 children still
include broad or awkward child labels. The next step is not to rewrite L2/L3
logic. Instead, add sidecar polish:

1. Induce corpus-level L3 theme families from evidence-backed L2 topics.
2. Write `l3/corpus_theme_view.json` and `l3/corpus_theme_index.json`.
3. Keep raw `l2/l2_view.json`, raw `l3/l3_view.json`, and raw L1 unchanged.
4. Let `load_effective_topic_surface()` prefer the corpus-theme L3 sidecar.
5. Export runtime-compatible sidecars after the effective surface is available.

Success criteria:

- Corpus-theme L3 has non-generic labels.
- Each accepted L3 theme references existing L2 ids and representative L1 ids.
- No raw L1/L2/L3 mutation.
- Retrieval/eval reports explicitly state `l3_surface_source = corpus_theme_l3`.

## Goal 2: Formal ICSI Evaluation Design

ICSI has no official QA set, so self-authored questions are weak if presented as
gold. The more defensible protocol is held-out future-meeting evaluation:

1. Use earlier meetings as the answerable evidence pool.
2. Use later meetings only to derive questions and identify what future context
   should have been anticipated.
3. Save every question with:
   - source evidence L1 ids from earlier meetings
   - held-out trigger L1 ids from later meetings
   - expected L2 labels
   - scoring rubric
   - provenance notes
4. Mark the output as candidate/manual-review-required until a human approves it.

Default split:

- source evidence: BMR meetings through `Bmr023`
- held-out trigger meetings: `Bmr024` and later

Question types:

- `evidence_lookup`
- `topic_evolution`
- `decision_rationale`
- `next_meeting_carryover`
- `corpus_process`

Success criteria:

- Questions are derived from topics that appear both before and after the split.
- `expected_obj_ids` for retrieval scoring point only to source-side L1.
- Held-out L1 is recorded separately as `heldout_trigger_obj_ids`.
- Markdown review pack includes concrete L1 excerpts for manual approval.
- Retrieval diagnostic can run against source-only `share_mem`.

## Non-Goals

- Do not rerun ICSI L1.
- Do not compare against mem0/AMem in this step.
- Do not claim the generated questions are final benchmark gold until manual
  review signs off.
- Do not move optimization v2 into canonical runtime by default.
