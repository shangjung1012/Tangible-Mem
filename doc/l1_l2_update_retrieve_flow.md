# L1/L2 And Short-Term Memory Flow

Last updated: 2026-05-10

This is the canonical architecture note for the current memory implementation.
It covers the active L1/L2 long-term path, the current short-term path, and the
router that decides which memory side to retrieve at answer time.

## Current Sources Of Truth

- L1 evidence source: `share_mem/tree.json` and `share_mem/meetings/<meeting_id>.json`.
- L1 extraction code: `share_mem/l1/`.
- L2 active view: `long_term/l2/l2_index.json` and `long_term/l2/l2_view.json`.
- L3 promotion sidecar: `long_term/l3/l3_promotions.json`.
- Materialized L3 sidecar: `long_term/l3/l3_view.json` and
  `long_term/l3/l3_index.json`.
- Short-term memory state: `short_term/short_term_memory.json` plus snapshots in
  `short_term/snapshots/`.
- Agent memory router: `app/memory_router.py`.
- Unified retrieval entrypoint: `app/memory_context.py::retrieve_memory_context`.

Raw L1 evidence is immutable. Human review, quality edits, relation/activity
state, L2 grouping, and L3 promotion all live in generated views or sidecars.

## Update Flow

```text
meeting transcript
  -> share_mem/build_tree.py
  -> share_mem/l1/bridge.py
  -> share_mem/l1/multi_agent_pipeline.py
  -> share_mem/tree.json                         # canonical L1 evidence
  -> share_mem/l1_index.json, meetings/, sidecars
  -> long_term/build_l2_view.py
  -> long_term/l2/l2_index.json                  # L1 obj_id -> L2 topic
  -> long_term/l2/l2_view.json                   # compact L2 topic view
  -> long_term/l3/l3_promotions.json             # oversized L2 review sidecar
  -> long_term/l3/l3_view.json                   # materialized L3 + child L2 sidecar
  -> long_term/l3/l3_index.json                  # L1 obj_id -> child L2 assignment
  -> long_term/l3/l2_merge_review.json           # review-only tiny/weak/oversized child L2 follow-up
```

Build canonical L1:

```bash
uv run share_mem/build_tree.py \
  --transcript-dir meeting_recording/transcript/grace \
  --output-root share_mem \
  --mode multi-agent \
  --dataset-profile grace \
  --model gemini-2.5-pro \
  --taxonomy v2-memory-roles \
  --include-legacy-type \
  --clean
```

Build and validate active L2:

```bash
uv run long_term/cli.py build-l2-view \
  --share-mem-root share_mem \
  --output-root long_term/l2 \
  --mode deterministic \
  --clean

uv run long_term/cli.py validate-l2-view \
  --share-mem-root share_mem \
  --root long_term/l2 \
  --out long_term/l2/validation

uv run long_term/cli.py validate-l3-view \
  --share-mem-root share_mem \
  --l2-root long_term/l2 \
  --l3-root long_term/l3 \
  --out long_term/l3/validation
```

## L1 Extraction

The L1 pipeline is staged and evidence-grounded:

```text
transcript lines
  -> context windows
  -> segmentation
  -> boundary repair / coarsening
  -> idea units
  -> extraction packets
  -> typed L1 agents
  -> grounding
  -> conflict resolution
  -> verification
  -> reducer
  -> final L1 memory objects
```

Current canonical Grace L1 types are:

- `decision`
- `action_item`
- `open_issue`
- `proposal`
- `argument`
- `finding`
- `approach_change`

`legacy_type` is retained for compatibility checks only. It is not the active
memory ontology.

The output meeting node contains `meeting_id`, `meeting_date`, `source_file`,
and `memory_objects`. Each L1 object contains `obj_id`, `type`, `content`,
`evidence`, `importance`, and `related_topics`.

## L2 Topic View

`long_term/build_l2_view.py` reads L1 objects from `share_mem` and
deterministically decides whether a durable L1 object should be linked to an L2
topic.

The first implementation uses rules instead of Gemini:

- Administrative/local context is skipped.
- `related_topics` from L1 extraction are normalized into L2 candidates first.
- Content concept rules are then used as supporting evidence or as a correction
  when the topic seed is broad.
- Low-importance non-durable items can remain unlinked.
- High-importance unlinked items are surfaced for review.

L2 candidate normalization is deterministic:

1. lowercase the topic hint;
2. replace `_` and `-` with spaces;
3. remove punctuation and collapse whitespace;
4. reject generic labels such as `memory`, `system`, `data`, and L1 type-like
   labels such as `decision`, `todo`, or `proposal`;
5. map aliases to canonical L2 labels, for example `memory_retrieval` ->
   `memory retrieval`, `STM-LTM_integration` -> `stm ltm integration`, and
   `evaluation methodology` -> `memory evaluation strategy`;
6. deduplicate by canonical label while preserving the first L1 topic order.

Specific topic seeds normally win. Broad seeds such as `system architecture`,
`development workflow`, `RAG`, or `forgetting mechanism` may be refined by
content rules when the L1 content clearly names a more precise durable concept.

Generated L2 files:

- `long_term/l2/l2_index.json`: `obj_id -> l2_id / l2_label / assignment`.
- `long_term/l2/l2_view.json`: compact topic state, timeline digest, linked L1 ids.
- `long_term/l2/unlinked_l1_report.json`: skipped L1 objects and review queue.
- `long_term/l2/l2_assignment_review_report.json`: topic size and review summary.
- `long_term/l2/validation/`: validation reports.

## L3 Promotion Sidecar

L3 is defined as overflow promotion above L2: when one L2 topic becomes too
broad, that L2 can be promoted into an L3 parent and split into two or more
child L2 topics.

The current implementation is sidecar-only. It does not rewrite `l2_index.json`,
`l2_view.json`, or raw L1 evidence.

Promotion candidate rules:

- hard warning: `linked_l1_count >= 24`, reason `too_many_l1_nodes`.
- soft warning: `linked_l1_count >= 12` and `l1_share >= 0.30`, reason
  `dominant_topic_share`.

Promotion candidates are written to `long_term/l3/l3_promotions.json`. A
candidate with enough suggested child L2 topics is marked `promotion_candidate`;
otherwise it is `needs_split_review`.

Materialized L3 output is written separately:

- `long_term/l3/l3_view.json`: L3 parent plus child L2 nodes.
- `long_term/l3/l3_index.json`: `obj_id -> l3_id / child_l2_id` assignment.
- `long_term/l3/l2_merge_review.json`: tiny/weak/oversized child L2 follow-up queue.
- `long_term/l3/validation/`: split coverage, scale-aware child size, prompt
  budget, and merge review reports.

The materializer only promotes candidates that already have at least two child
L2 definitions. By default, it assigns every old L2 timeline item to exactly
one child L2 using deterministic `assignment_criteria`; unmatched items are
assigned by a balanced fallback so no L1 is lost. The current generated
materialization is:

Validation separates two large-child cases. A coherent long-running child L2 is
marked `large_coherent_needs_retrieval_slice`, which means retrieval should
slice its timeline instead of injecting it whole. A large low-coherence child L2
is marked `large_low_coherence_needs_split_review` and remains in manual review
because it may be a mixed assignment or missing taxonomy split.

```text
L3-transcript-segmentation-and-idea-unit-coverage
  L2-fixed-vs-dynamic-chunking: 18 L1
  L2-window-and-boundary-selection: 14 L1
  L2-tool-calling-transcript-reading: 9 L1
  L2-idea-unit-generation: 31 L1
  L2-missing-line-coverage: 10 L1
  L2-repair-and-coarsening: 9 L1
  L2-cross-window-continuity: 9 L1
  L2-evidence-grounding-and-line-coverage: 9 L1
```

LLM status for L3:

- The default build path does not call an LLM.
- `--l3-mode llm-assisted` adds two Gemini-assisted sidecar stages:
  1. `build_child_taxonomy_prompt()` asks Gemini to propose child L2 taxonomy
     from the promoted L2's linked L1 compact evidence when that oversized L2
     does not already have a reviewed child split. `--l3-source-l2-id` can
     limit this API step to a specific oversized L2 during review.
  2. `build_child_assignment_prompt()` asks Gemini to suggest one
     `obj_id -> child_l2_id` assignment per linked L1.
- Deterministic validation still owns the final output: unknown child ids,
  missing assignments, and low-confidence suggestions fall back to local
  `assignment_criteria` and are marked for manual review.
- Raw L1 evidence remains immutable in both modes.
- Tiny child L2 nodes are never merged automatically and are not automatically
  wrong. They may represent emerging or niche topics. `l2_merge_review.json`
  records `watch_until_more_evidence` when sibling similarity is low,
  `merge_candidate` / `merge_review` when sibling similarity is high, and
  `split_review` when a child L2 is still too large. Accepted merges should be
  represented as sidecar changes in a later step.

## Short-Term Memory

The current checked-in short-term implementation updates a compact JSON memory
from the latest `share_mem` snapshot:

```text
share_mem snapshot
  -> short_term/update_memory.py
  -> load latest meeting
  -> select candidate short-term units
  -> Gemini or injected merge decider
  -> merge_existing / create_new
  -> short_term/short_term_memory.json
  -> short_term/snapshots/<meeting_id>.json
```

Short-term units track current working context rather than full history:

- `unit_id`
- `title`
- `summary`
- `current_state`
- `role` (`current_status`, `active_decision`, `next_action`, `open_issue`,
  `recent_change`, or `pending_validation`)
- `status` (`active`, `stale`, `pending`, `resolved`, or `superseded`)
- `types`
- `related_topics`
- `source_obj_ids`
- `active_source_obj_ids`
- `historical_source_obj_ids`
- `created_meeting_id`
- `last_updated_meeting_id`
- `last_seen_meeting_index`
- `missed_meeting_count`
- `update_history`

`source_obj_ids` remains the full lineage. `active_source_obj_ids` is the
bounded recent evidence slice intended for prompt display. Older lineage moves
to `historical_source_obj_ids` so short-term memory stays a current-state view
instead of becoming another long-term topic history.

When a unit is not touched by a new meeting, `missed_meeting_count` increases.
Units missed for two meetings are dropped. This keeps short-term focused on
recent status, active TODOs, owners, and near-term progress.

Short-term retrieval now has a deterministic module:

```python
short_term.retrieval.short_term_context.retrieve_short_term_context(
    query,
    api_key,
    retrieval_mode="hybrid",
    top_k=4,
    max_context_chars=...
)
```

It reads `short_term/short_term_memory.json`, ranks active `S###` units by
query overlap against `title`, `summary`, `types`, and `related_topics`, lightly
prefers fresher units through `missed_meeting_count`, and formats compact
context with query-ranked active source L1 previews. If a checked-in legacy
unit does not yet have explicit `active_source_obj_ids`, retrieval derives a
recent active source slice from the last three `meeting_history_ids` instead of
showing the full historical source list. `app/memory_context.py::retrieve_short_term_context_adapter`
calls this module directly.

## Retrieve Flow

The agent should call `get_memory_context(query)` by default.

```text
user question
  -> app/tools/memory_tools.py::get_memory_context
  -> app/memory_context.py::retrieve_memory_context
  -> app/memory_router.py::plan_memory_retrieval
  -> short_term, long_term, both, or none
  -> formatted context
  -> agent answer
```

Routing is deterministic for now, but meeting-memory queries keep long-term
context on by default:

- queries with recent-status hints retrieve both short-term and long-term;
- historical, rationale, architecture, method evolution, and topic questions
  retrieve long-term;
- non-meeting questions retrieve none.

Long-term retrieval starts from hybrid L1 search over `share_mem/tree.json`:
lexical hits are always available, semantic hits are fused when an embedding
client is configured, and lexical fallback is used when offline.
Every long-term retrieval also includes a compact global topic map, then expands
only a small number of L2 / child L2 contexts from the selected L1 seeds:

```text
L1 hit obj_id
  -> compact global topic map from l3_view + unpromoted l2_view labels
  -> long_term/l3/l3_index.json if the seed is in a promoted topic
  -> materialized child L2 context
  -> otherwise long_term/l2/l2_index.json and l2_view.json fallback
  -> compact evolution slice, not full large-topic timeline
```

For rationale, evolution, architecture, design, and tradeoff queries, retrieval
may also include a small same-parent L3 sibling child-L2 slice. This is a
retrieval-time supplement only: it does not reassign L1, does not cross L3
families, and does not run for local factual queries. The sibling cap is part
of the selected retrieval budget profile, so large-corpus tight runs can keep it
disabled while the app/Observatory `generous_layered` profile can expose the
topic-family context needed for explanation.

Missing L2 assignments are non-fatal; the system can still answer from L1.
Legacy temporal phase/profile expansion is fallback only.

Prompt sections are ordered evidence-first:

```text
=== Global Topic Map ===
=== L1 Evidence Seeds ===
=== L2 / Child-L2 Evolution Context ===
=== Retrieval Debug ===        # debug only
```

The global topic map is navigation context only. Concrete facts should be
grounded in L1 evidence; L2/child L2 supplies cross-meeting evolution; L3 is a
topic family layer.

Generated L2 and child-L2 nodes now include deterministic topic-state metadata
(`current_state`, `evolution_summary`, `latest_position`, `key_rationale`,
`open_tensions`, and `representative_l1_ids`). These are rebuildable sidecar
caches generated from each topic timeline, not raw evidence edits. If a
summary conflicts with L1 evidence, L1 wins.

Retrieval evaluation has an offline deterministic mode for repeatable parameter
checks:

```bash
uv run python long_term/evaluate_retrieval.py \
  --queries long_term/eval/long_term_retrieval_queries.jsonl \
  --out long_term/eval \
  --no-llm \
  --retrieval-mode hybrid
```

In this mode `--no-llm` uses a heuristic recall plan and does not call the
Gemini planner or final answer LLM. `--retrieval-mode hybrid` may use semantic
embeddings if a client is available; use `--retrieval-mode lexical` for a fully
offline smoke test.
`strict_gold_obj_ids` can preserve older exact seed expectations while
`expected_obj_ids` records the current acceptable L1 evidence set used for
regression scoring.

## Demo-Safe Questions

Use questions that match stable L2 topics:

- "long-term memory retrieval 現在是怎麼運作的？"
- "STM 和 LTM 的整合目前是怎麼設計的？"
- "我們之前為什麼要把 transcript 拆成 segment / idea units？"
- "memory evaluation strategy 之前討論過哪些方向？"
- "L1 到 L2 的分群現在是怎麼決定的？"

Avoid broad questions such as "請完整說明整個研究架構從一開始到現在所有演進"
until large L2 topics are materialized into reviewed L3/child-L2 taxonomies.
