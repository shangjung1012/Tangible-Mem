# Optimization TODO

This TODO tracks the remaining work needed to make optimization v2 cleanly
usable for TAICHI demos, partner handoff, and new-dataset L2/L3 experiments.

## P0: Demo / Paper Readiness

1. Freeze the final ICSI effective L1 root.
   - Confirm the final `share_mem_effective` or `filtered_share_mem` root used
     for ICSI L2/L3.
   - Record meeting count, L1 count, missing meeting IDs that are expected, and
     source hash summary.
   - Do not use raw archived `share_mem` roots for downstream ICSI L2/L3.

2. Keep one official ICSI v2 run for paper/demo references.
   - Current candidate: `optimization/runs/icsi_bmr_full_completed29_v2_20260614`.
   - Current comparison report:
     `optimization/reports/icsi_bmr_full_completed29_system_comparison_revised_20260614`.
   - If a newer final-completed run is generated, update `README.md`,
     `optimization/README.md`, `memory_observatory/README.md`, and
     `doc/taichi/artifact_index.md` together.

3. Finish Memory Observatory demo readiness.
   - Confirm the Demo Story tab is the intended TAICHI walkthrough surface.
   - Capture screenshots for Overview, Demo Story, Retrieval Trace, Topic
     Observatory, and sidecar feedback.
   - Ensure long metric values and formatted context do not overflow.

4. Build TAICHI section assets.
   - Section 3: design goals and system overview figure.
   - Section 4: implementation screenshots and interaction mechanisms.
   - Section 5: one polished use-case walkthrough.
   - Use `doc/taichi/` as the paper asset index and working outline.

## P1: Optimization v2 Explainability

1. Add or regenerate term decision audit.
   - For each candidate term, record accepted/rejected/downweighted and the
     rule/score reason.
   - This supports reviewer questions about phrase bonus, generic labels, and
     type-like filtering.

2. Add or regenerate L2 assignment audit.
   - For each L1, record assigned L2, confidence, source signals, and unlink or
     review-only reason.

3. Add or regenerate L3 split audit.
   - For each promoted parent L2, record threshold, split candidates, child
     labels, assignment counts, and split quality.
   - Make clear that child labels come from parent evidence terms/timeline
     summaries, not from a hand-written taxonomy.

4. Keep topic polish sidecar-only.
   - Label polish and split/merge decisions must write effective sidecars.
   - Do not mutate raw L1 or canonical L2/L3 artifacts.

## P2: Evaluation And Runtime

1. ICSI evaluation pack.
   - Keep the current 20-question no-LLM retrieval/evidence benchmark as a
     diagnostic, not final answer scoring.
   - Add a small human-auditable answer-quality set before claiming generated
     answer superiority.

2. Grace regression.
   - Keep Grace demo retrieval and shadow answer-quality smoke results available.
   - Do not rebuild canonical Grace unless explicitly requested.

3. Runtime shadow mode.
   - Use `LONG_TERM_BACKEND=optimization_v2` only with an approved exported run.
   - Preserve canonical fallback behavior.
   - Do not mark canonical replacement eligible until shadow QA and user
     approval both exist.

## Non-Goals

- Do not claim arbitrary-domain generality.
- Do not overwrite canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.
- Do not use discarded or wrong-project reports as evidence.
- Do not commit large raw run outputs unless a release/LFS plan is approved.
