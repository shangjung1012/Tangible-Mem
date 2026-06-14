# ICSI Topic Polish And Evaluation Summary

## Scope

This report summarizes the convergence work for the full 29-meeting ICSI BMR effective L1 root.

- L1 source: `memory_outputs/icsi/runs/bmr_full_completed29_eval_20260614/share_mem_effective`
- Optimization v2 run: `optimization/runs/icsi_bmr_full_completed29_v2_20260614`
- Held-out eval pack: `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614`

All work is sidecar-only. It does not modify canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.

## Topic Polish Result

The raw optimization v2 run still has many detailed L2 topics and 65 deterministic L3 parents. For demo and review, this is too fragmented. I ran the corpus-theme L3 sidecar induction to add a higher-level navigation layer without rewriting raw L2/L3.

Corpus-theme L3 sidecar:

- accepted corpus themes: `6`
- rejected themes: `0`
- invalid themes: `0`
- duplicate L1 assignment count: `0`
- runtime export L3 count after polish: `6`

Accepted themes:

1. `annotation and transcription workflow`
2. `corpus design and data management`
3. `audio acquisition and signal processing`
4. `asr modeling and evaluation`
5. `speech and interaction analysis`
6. `project planning and management`

This is the intended ICSI-level topic surface: it is corpus-derived and does not force Grace-specific topics such as memory evaluation, transcript segmentation, manager-agent, or topic lifecycle.

Primary files:

- `optimization/runs/icsi_bmr_full_completed29_v2_20260614/l3/corpus_theme_view.json`
- `optimization/runs/icsi_bmr_full_completed29_v2_20260614/l3/corpus_theme_index.json`
- `optimization/runs/icsi_bmr_full_completed29_v2_20260614/l3/corpus_theme_summary.json`
- `optimization/runs/icsi_bmr_full_completed29_v2_20260614/runtime/`

## Held-Out Evaluation Design

The ICSI corpus does not provide official QA pairs like LOCOMO. To make evaluation more credible than self-written arbitrary questions, I generated a held-out future-meeting eval pack:

- Source-side evidence: BMR meetings through `Bmr023`
- Held-out trigger meetings: BMR meetings after `Bmr023`
- Answer evidence must come only from the source-side share_mem snapshot
- Held-out L1 objects are used only to justify that the topic later mattered
- Every question remains `candidate_manual_review_required`

This design approximates a realistic memory use case: given past meetings, can the memory system recover the context that later meetings make relevant?

## Query Set

Generated candidate questions:

- total queries: `20`
- candidate source/held-out topics considered: `145`
- source-side meetings: `21`
- source-side L1 objects: `4715`

Query types are balanced:

- `evidence_lookup`: `4`
- `topic_evolution`: `4`
- `decision_rationale`: `4`
- `next_meeting_carryover`: `4`
- `corpus_process`: `4`

The 20 topic labels are distinct after weak-label filtering. Examples:

- `resource allocation`
- `disk space`
- `audio processing`
- `speech recognition`
- `annotation tool`
- `acoustic modeling`
- `audio quality`
- `meeting agenda`
- `meeting recorder`
- `far field`
- `error analysis`
- `experimental setup`
- `conversational speech`
- `forced alignment`

Weak labels such as `go ahead`, `team decided`, `next week`, `backed up`, and `hub five` are filtered out of the formal eval pack. They may still exist in raw L2, but they are not suitable as benchmark questions without manual relabeling.

Primary files:

- `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/heldout_eval_queries.jsonl`
- `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/heldout_eval_pack.md`
- `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/heldout_eval_pack_report.json`
- `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/source_share_mem/`

## Retrieval Diagnostic

I ran optimization v2 retrieval against the held-out eval pack using only the source-side share_mem snapshot.

Result:

- query count: `20`
- top-k L1: `80`
- average expected L1 recall: `0.7875`
- expected L2 hit rate: `1.0`
- expected L2 semantic hit rate: `1.0`
- expected L3 hit rate: `1.0`
- expected L3 semantic hit rate: `1.0`
- active L2 count: `530`
- active L3 surface: `corpus_theme_l3`

Interpretation:

- Topic retrieval is strong: L2/L3 hits are perfect on this candidate set.
- Evidence retrieval is usable but not perfect: some labels, such as `audio processing`, `annotation tool`, `far field`, and `audio file`, still have low exact-L1 recall.
- This is acceptable for a candidate benchmark, because low-recall rows expose real failure cases instead of hiding them.

Primary files:

- `optimization/runs/icsi_bmr_full_completed29_v2_20260614/retrieval_eval/heldout_future_eval/retrieval_eval_report.json`
- `optimization/runs/icsi_bmr_full_completed29_v2_20260614/retrieval_eval/heldout_future_eval/retrieval_eval_report.md`

## How To Use This For Comparisons

The next fair comparison should use the same 20 held-out questions and the same source-side evidence boundary.

Strategies:

1. Optimization v2 layered memory
   - Use `optimization/runs/icsi_bmr_full_completed29_v2_20260614/runtime/`.
   - Use the source-side share_mem root in the eval pack.

2. Traditional RAG
   - Index only `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/source_share_mem/`.
   - Do not index held-out meetings.

3. Full transcript / full context
   - Provide only source-side meetings through `Bmr023`.
   - Do not provide Bmr024+.

4. mem0 / AMem-style tool
   - Load only source-side meeting memories.
   - Ask the same 20 questions.
   - Score with the same rubric and expected evidence list.

Scoring dimensions should be:

- factual correctness
- evidence grounding
- topic evolution
- completeness
- conciseness
- hallucination risk
- source traceability
- temporal-boundary compliance

## Current Status

This is ready as a candidate ICSI evaluation pack and topic-polished optimization v2 surface. It is not yet a final benchmark until a human reviews the 20 questions and approves or edits them.

Recommended next step:

1. Manually review `heldout_eval_pack.md`.
2. Mark each question as accepted, revised, or rejected.
3. Then run answer-quality comparison across optimization v2, RAG, full context, and any external memory tool.
