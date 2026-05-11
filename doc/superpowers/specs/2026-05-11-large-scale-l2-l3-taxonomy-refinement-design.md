# Large-Scale L2/L3 Taxonomy Refinement Design

Date: 2026-05-11

## Context

The current long-term memory stack is structurally stable:

- `share_mem/tree.json` and `share_mem/meetings/*.json` are the immutable L1 evidence sources.
- `long_term/l2/` is the active L2 topic view over L1.
- `long_term/l3/` is a sidecar promotion layer for oversized L2 topics.
- L3 is a topic-family/navigation layer, not the primary evidence source.
- Retrieval remains evidence-first: L1 evidence seeds first, then relevant L2/child-L2 evolution context, then L3 navigation context.

The latest synthetic LongMeet-50 run showed that the pipeline scales structurally, but the taxonomy is still too Grace-shaped in places. The important finding is not a broken schema. The issue is quality: large synthetic meetings expose broad L2 buckets and child-L2 splits that need more general taxonomy refinement.

## Current Evidence

### Grace baseline after the safe small fix

- L1 source: `share_mem/`
- Meetings: 7
- L1 objects: 448
- L2 topics: 16
- L2 linked L1: 411
- L2 unlinked L1: 37
- L2 validation: 0 severe, 3 warnings
- L3 validation: 0 severe, 3 warnings
- L3 assignment coverage: 0 unassigned, 0 duplicate, 0 invalid

Manual side-by-side check showed only one Grace L1 changed topic after the retrieval-baseline fix:

- `L1-0325-057`: `memory processing architecture` -> `retrieval baseline comparison`

That change is reasonable because the object is about full-context baseline / evaluation comparison.

### Synthetic LongMeet-50 result

- Source root: `share_mem_experiments/synthetic_longmeet_50_idea_units/`
- Meetings: 50
- L1 objects: 3198
- Avg objects per meeting: 63.96
- Schema/object validation: clean
- Object count is close to Grace average.

Baseline synthetic L2/L3 exposed broad topics:

- `transcript segmentation and idea-unit coverage`: 1065 events
- `l2 topic grouping`: 455 events
- `memory evaluation strategy`: 417 events
- `memory processing architecture`: 371 events
- `stm ltm integration`: 267 events

After the safe retrieval-baseline fix:

- Synthetic L2 topics: 9
- Synthetic linked L1: 3022
- Synthetic unlinked L1: 176
- L2 warnings decreased from 150 to 79
- Severe issues remained 0

The fix improved coverage without damaging Grace, but it did not solve all large-scale taxonomy issues.

## Problem Statement

Current L2/L3 behavior is safe and usable for Grace, but not yet general enough for large-scale or different meeting distributions.

The core risks are:

1. Some L2 labels are too broad and become catch-all buckets.
2. L3 materialization only exists for known large source L2s with reviewed child candidates.
3. Synthetic data reveals that new large L2s may need split review rather than forced automatic acceptance.
4. Overfitting taxonomy rules to synthetic could degrade Grace.
5. Overfitting taxonomy rules to Grace could make the system fail on larger meeting sets.

The refinement must therefore be side-by-side and evidence-gated. It should not directly overwrite canonical `share_mem/`, active `long_term/l2/`, or active `long_term/l3/` until it passes both Grace and synthetic gates.

## Design Principles

1. Preserve immutable L1.
   - Never edit `share_mem/tree.json` or `share_mem/meetings/*.json`.

2. Keep L2 as topic, not object type.
   - L2 labels should represent long-running design/research topics.
   - Labels like `decision`, `argument`, `open_issue`, or `design decision` are type-like and should not become topic labels.

3. Use L3 only for overcrowded L2 families.
   - L3 should emerge when an L2 is too large and needs child L2 navigation.
   - L3 should not become a singleton project profile.

4. Prefer side-by-side candidate outputs.
   - Build candidate L2/L3 into an experiment root.
   - Compare candidate vs active Grace.
   - Compare candidate vs synthetic.
   - Promote only after gates pass.

5. Do not optimize only warning count.
   - A warning can be acceptable if it is explainable.
   - Severe assignment problems, dropped important L1, or topic incoherence are blockers.

6. Retrieval quality matters more than pretty taxonomy.
   - The goal is better evidence-first retrieval and clearer evolution context.
   - A split that makes retrieval worse should not be promoted even if topic sizes look better.

## Non-Goals

- Do not rerun L1 extraction.
- Do not change `share_mem` schema.
- Do not directly rewrite canonical generated L2/L3 artifacts during experimentation.
- Do not use synthetic-only rules that make Grace worse.
- Do not require all L1 objects to link to L2. Some low-value or isolated L1 can remain unlinked.

## Proposed Side-by-Side Workflow

Create a taxonomy experiment root:

```powershell
long_term/eval/taxonomy_refinement_<timestamp>/
  grace/
    l2/
    l3/
    validation/
  synthetic_longmeet_50_idea_units/
    l2/
    l3/
    validation/
  comparison/
    grace_active_vs_candidate.json
    grace_active_vs_candidate.md
    synthetic_before_after.json
    synthetic_before_after.md
  manual_review/
    changed_grace_assignments.json
    large_topic_review_queue.json
    child_l2_split_review_queue.json
  taxonomy_refinement_report.json
  taxonomy_refinement_report.md
```

Run candidate builds without touching active artifacts:

```powershell
uv run long_term/cli.py build-l2-view `
  --share-mem-root share_mem `
  --output-root long_term/eval/taxonomy_refinement_<timestamp>/grace/l2 `
  --mode deterministic `
  --clean

uv run long_term/cli.py validate-l2-view `
  --share-mem-root share_mem `
  --root long_term/eval/taxonomy_refinement_<timestamp>/grace/l2 `
  --out long_term/eval/taxonomy_refinement_<timestamp>/grace/l2/validation

uv run long_term/cli.py validate-l3-view `
  --share-mem-root share_mem `
  --l2-root long_term/eval/taxonomy_refinement_<timestamp>/grace/l2 `
  --l3-root long_term/eval/taxonomy_refinement_<timestamp>/grace/l2/../l3 `
  --out long_term/eval/taxonomy_refinement_<timestamp>/grace/l3/validation
```

Repeat the same for:

```powershell
share_mem_experiments/synthetic_longmeet_50_idea_units
```

## Candidate Taxonomy Refinement Areas

### 1. Generalize large L2 source detection

Current risk: only reviewed source L2 IDs get good child L2 materialization.

Proposed refinement:

- Keep existing reviewed child taxonomies.
- Add diagnostics that identify large unknown L2s by:
  - event count
  - share of all linked L1
  - repeated related topic clusters
  - high lexical subtopic diversity
  - meeting spread
- Do not automatically split unknown L2 unless confidence is high.
- Output unknown large L2 into manual split review sidecar.

### 2. Add candidate child L2 proposal sidecar

For unknown large L2s, generate a sidecar-only split proposal:

```json
{
  "schema_version": 1,
  "source_l2_id": "...",
  "source_l2_label": "...",
  "event_count": 417,
  "proposal_mode": "deterministic",
  "candidate_child_l2": [
    {
      "candidate_child_l2_id": "...",
      "label": "...",
      "assignment_criteria": ["..."],
      "estimated_event_count": 42,
      "representative_obj_ids": ["..."],
      "confidence": 0.68
    }
  ],
  "manual_review_required": true
}
```

This proposal is not canonical. It becomes canonical only after manual acceptance.

### 3. Improve generic memory buckets

Watch labels:

- `memory processing architecture`
- `memory evaluation strategy`
- `stm ltm integration`
- `l2 topic grouping`
- `transcript segmentation and idea-unit coverage`

These can be valid, but they become risky when:

- event count is high,
- timeline spans many meetings,
- representative keywords split into multiple unrelated clusters,
- retrieval expands the topic and omits important matched side branches.

### 4. Preserve retrieval-baseline comparison as durable topic

The safe small fix should remain:

- Full context baseline
- Traditional RAG baseline
- Layered memory comparison
- Token / latency / cost
- Answer quality / traceability

This topic should not be folded into generic memory architecture.

## Validation Gates

### Grace gate

Candidate must satisfy:

- L2 severe issues: 0
- L3 severe issues: 0
- L3 unassigned promoted L1: 0
- L3 duplicate promoted L1: 0
- L3 invalid index entries: 0
- Linked L1 count must not decrease materially.
- High-importance L1 must not be dropped from relevant L2 retrieval.
- Changed L2 assignment count must be manually reviewed.
- Any changed assignment must be explainable.

Hard fail:

- A Grace L1 about MEMO/RAG evaluation moves into an unrelated topic.
- Transcript segmentation / idea unit topics lose their child L2 navigation.
- Retrieval eval average expected object recall drops below current baseline.

### Synthetic gate

Candidate must satisfy:

- L2 severe issues: 0
- L3 severe issues: 0
- Synthetic input schema remains untouched.
- Large generic L2 warnings should decrease or become more explainable.
- Unknown large L2s should produce split review proposals rather than silently staying broad.
- Child L2 over 35 events should be flagged.
- Child L2 under 3 events should be flagged for merge review, not automatically merged.

### Retrieval gate

Run:

```powershell
uv run python long_term/evaluate_retrieval.py `
  --queries long_term/eval/long_term_retrieval_queries.jsonl `
  --out long_term/eval `
  --no-llm `
  --retrieval-mode lexical
```

Candidate must not regress:

- expected object recall
- expected L2 hit
- expected L3 hit
- prompt budget pass rate
- large L2 expanded without child split

## Manual Review Protocol

Review these queues before promotion:

1. Changed Grace assignments
   - Check old L2, new L2, object content, evidence, related topics.
   - Accept only if the new topic is more precise.

2. Large L2 review queue
   - Decide whether it is a real topic family or a taxonomy gap.

3. Child L2 split review queue
   - Check whether child labels are meaningful and not type-like.
   - Check whether child L1 samples are coherent.

4. Retrieval trace samples
   - Use at least the existing 8 eval questions.
   - Add synthetic stress queries for large meeting-scale behavior.

## Metrics to Report

For both Grace and synthetic:

- meeting_count
- l1_count
- l2_count
- linked_l1_count
- unlinked_l1_count
- l3_parent_count
- child_l2_count
- l2 severe/warning count
- l3 severe/warning count
- largest L2 topics
- largest child L2 topics
- tiny child L2 count
- changed Grace assignment count
- lost Grace linked L1 count
- gained Grace linked L1 count
- retrieval eval best params
- retrieval eval recall/hit metrics

## Files Likely to Change in a Future Implementation

Implementation should be limited to:

- `long_term/build_l2_view.py`
- `long_term/l3_promotion.py`
- `long_term/validate_l3_view.py`
- `long_term/evaluate_retrieval.py` only if candidate metrics need extra reporting
- `tests/test_l2_view.py`
- `tests/test_l3_promotion.py`
- optional new tests for taxonomy side-by-side comparison
- new experiment reports under `long_term/eval/taxonomy_refinement_<timestamp>/`

Files that should not be changed by the refinement:

- `share_mem/tree.json`
- `share_mem/meetings/*.json`
- canonical `long_term/l2/*` until promotion is approved
- canonical `long_term/l3/*` until promotion is approved

## Promotion Criteria

Only promote candidate taxonomy changes to active `long_term/l2` and `long_term/l3` when:

1. Grace gates pass.
2. Synthetic gates pass.
3. Retrieval gates pass.
4. Manual changed-assignment review has no unresolved severe issue.
5. The improvement is clear enough to justify the taxonomy change.

Promotion means:

1. Apply code/rule changes.
2. Rebuild active Grace L2/L3.
3. Run L2/L3 validation.
4. Run retrieval eval.
5. Run full test suite.
6. Commit and push only the scoped changes and intentional generated artifacts.

## Open Questions

1. Should unknown large L2 split proposals use only deterministic lexical clustering, or allow optional LLM-assisted proposal generation?
2. Should synthetic stress queries become part of the default retrieval eval, or stay under a synthetic-specific eval file?
3. Should child L2 upper bound remain 35 for all datasets, or scale with meeting count?
4. Should unlinked L1 thresholds be dataset-relative rather than fixed?

## Recommended Next Step

Start a dedicated side-by-side taxonomy refinement branch or worktree. First implement reporting only:

1. Changed assignment comparator.
2. Unknown large L2 split proposal sidecar.
3. Synthetic stress retrieval queries.

Then run Grace and synthetic side by side before changing any active taxonomy rule.
