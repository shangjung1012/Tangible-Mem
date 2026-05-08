# share_mem Checkpoint Status

Last updated: 2026-05-09

This file is the handoff note for collaborators integrating `share_mem` with
new `long_term` L2/L3 retrieval and `short_term` context loading.

## Current Status

- `share_mem/` is the canonical raw L1 evidence store for Grace work.
- `share_mem/tree.json` is the canonical aggregate L1 store.
- The current canonical Grace run uses v2 memory roles in `type` and keeps the
  old taxonomy in `legacy_type` for compatibility, diffing, and rollback checks.
- `share_mem/meetings/<meeting_id>.json` stores one immutable L1 meeting payload
  per meeting.
- `share_mem/l1_index.json` maps `obj_id` to meeting, type, content, evidence,
  importance, and topics for direct lookup.
- `share_mem/manifest.json` records meeting count, object count, meeting ids,
  source transcript directory, tree hash, and topic view status.
- `share_mem/topic_tree.json`, `share_mem/topic_updates/<meeting_id>.json`, and
  `share_mem/topic_index.json` are a sidecar topic-tree view, not a replacement
  for raw L1.
- `long_term/l2/` is the active generated L2 view over `share_mem` L1. It is
  meant for long-term retrieval context and does not require every L1 object to
  be linked.

## Stable Enough For Partner Work

These interfaces are intended to stay structurally stable:

- `tree.json`
  - `meetings[]`
  - `meeting_id`, `meeting_date`, `source_file`
  - `memory_objects[]`
  - `obj_id`, `type`, `content`, `evidence`, `importance`, `related_topics`
  - `legacy_type` is present in the current Grace v2 canonical output.
- `meetings/<meeting_id>.json`
  - Same meeting payload shape as an item in `tree.json`.
- `l1_index.json`
  - `obj_id -> { meeting_id, meeting_date, source_file, type, content, evidence, importance, topics }`.
- `manifest.json`
  - `meeting_count`, `object_count`, `meeting_ids`, `tree_hash`, `topic_view`.
- Python helpers in `share_mem.store`
  - `load_share_tree`
  - `iter_meetings`
  - `iter_l1_objects`
  - `build_l1_index`
  - `get_l1_object`
  - `load_recent_meetings`

Partner guidance:

- New `long_term` L2/L3 work should use `share_mem/tree.json`,
  `share_mem/meetings/`, or `share_mem.store.load_share_tree()` as the L1
  source.
- Retrieval should remain bottom-up: find relevant L1 first, then pull L2/L3
  or topic-tree context as sidecar context.
- `short_term` integration can start by using `load_recent_meetings(limit=3)`
  or equivalent reads from `share_mem/tree.json`.
- Do not mutate old L1 objects to represent updates. Add new L1 evidence and
  use sidecars/views to express evolution.
- New `long_term` L2 integration can use `long_term/l2/l2_index.json` for
  `obj_id -> L2 topic` lookup and `long_term/l2/l2_view.json` for compact
  upward context.
- The old temporal `long_term/tree.json`, snapshots, build-tree, bridge, and
  summarize pipeline are archived under
  `long_term/archive/legacy_temporal_l2_l3/`.

## Still Under Ultimate Quality Loop

These are likely to change in content or prompt behavior, but not expected to
force a core JSON format break:

- L1 extraction prompt wording and candidate quality.
- v2 type assignment distribution.
- `importance` calibration and matching gates.
- Topic-tree assignment quality.
- Topic labels and topic paths.
- `current_state` and `timeline_digest` wording in topic-tree nodes.
- L2 labels and deterministic assignment rules.
- Validator thresholds for large topics and expected concept links.

Current generated state:

- Grace meetings: 7 (`0307`, `0318`, `0325`, `0408`, `0422`, `0429`, `0506`).
- L1 objects: 545.
- Topic-tree sidecar: exists, with 54 topics and 545 topic events.
- Topic validation: 0 severe issues; current warnings are large-topic review
  diagnostics, not schema blockers.
- Long-term L2 topic view: exists under `long_term/l2/`, with 18 L2 topics, 467
  linked L1 objects, 78 intentionally unlinked low-review L1 objects, and 0
  severe validation issues. The only current warning is the explainable large
  `transcript segmentation and idea-unit coverage` topic.

These files should be treated as generated outputs:

- `share_mem/tree.json`
- `share_mem/meetings/*.json`
- `share_mem/l1_index.json`
- `share_mem/manifest.json`
- `share_mem/l1_quality_index.json`
- `share_mem/memory_activity_index.json`
- `share_mem/memory_relations_index.json`
- `share_mem/topic_updates/*.json`
- `share_mem/topic_tree.json`
- `share_mem/topic_index.json`
- `share_mem/research_logs/`
- `share_mem/topic_research_logs/`
- `share_mem/snapshots/`

## Topic-Tree Notes

- Use the term `topic-tree`.
- The topic-tree is a sidecar/view.
- `topic_updates/` is the append-only source of truth for the topic-tree view.
- `topic_tree.json` and `topic_index.json` are materialized outputs that can be
  rebuilt from `topic_updates/`.
- `topic_index.json` supports `obj_id -> topic path` lookup for future
  retrieval.

Current known quality work:

- Continue reviewing large topics for accidental over-merging.
- Continue checking prompt/content quality when new transcripts are added.
- Do not treat topic labels or topic paths as final ontology names yet.

## Useful Commands

Build canonical L1:

```powershell
uv run share_mem/build_tree.py --transcript-dir meeting_recording/transcript/grace --output-root share_mem --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --taxonomy v2-memory-roles --include-legacy-type --clean
```

Build topic-tree sidecar:

```powershell
uv run share_mem/build_topic_view.py --tree share_mem/tree.json --output-root share_mem --mode hybrid --model gemini-2.5-pro --clean-topic-view
```

Validate topic-tree sidecar:

```powershell
uv run share_mem/validate_topic_view.py --root share_mem --out share_mem/topic_validation
```

Build and validate long-term L2 view:

```powershell
uv run long_term/cli.py build-l2-view --share-mem-root share_mem --output-root long_term/l2 --mode deterministic --clean
uv run long_term/cli.py validate-l2-view --share-mem-root share_mem --root long_term/l2 --out long_term/l2/validation
```

Compare an experiment against canonical:

```powershell
uv run share_mem/compare_l1_runs.py --baseline share_mem/tree.json --candidate <experiment-root>/tree.json --out <experiment-root>/comparison
```

Run tests:

```powershell
uv run python -m unittest discover -s tests
```
