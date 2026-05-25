# Share Memory

`share_mem/` is the canonical L1 evidence store. It is shared by short-term
memory, long-term L2/L3 retrieval, and evaluation code.

## Active Contract

- Canonical aggregate: `share_mem/tree.json`.
- Per-meeting payloads: `share_mem/meetings/<meeting_id>.json`.
- Direct lookup index: `share_mem/l1_index.json`.
- Build entrypoint: `share_mem/build_tree.py`.
- L1 extraction code: `share_mem/l1/`.
- Reader API: `share_mem.store`.

Raw L1 evidence is immutable. Do not directly edit existing evidence objects in
`tree.json` or `meetings/`; use generated sidecars or replayable correction
artifacts for review decisions.

## Rebuild

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

The builder processes `.txt` transcripts in filename order. For the Grace set,
`0307.txt` maps to `2026-03-07`, `0429.txt` maps to `2026-04-29`, and so on.

## L1 Pipeline

```text
share_mem/build_tree.py
  -> share_mem.l1.bridge
  -> share_mem.l1.multi_agent_pipeline
  -> context windows
  -> segmentation / boundary refinement
  -> idea units
  -> extraction packets
  -> typed agents
  -> grounding / verifier / reducer
  -> share_mem/tree.json
```

Use "extraction packet" in collaborator-facing explanations. It means the
bounded group of idea units passed to typed L1 agents before they emit
candidates.

Current canonical Grace L1 types:

- `decision`
- `action_item`
- `open_issue`
- `proposal`
- `argument`
- `finding`
- `approach_change`

Current canonical Grace L1 language policy:

- `content`: Traditional Chinese human-facing memory summary, preserving stable
  English technical anchors such as RAG, L1/L2/L3, API, topic lifecycle,
  manager-agent, full context, and short-term / long-term memory.
- `related_topics`: English machine-facing topic keys for deterministic L2/L3
  grouping and retrieval.
- `evidence`: source-faithful transcript excerpt; do not translate evidence just
  to satisfy the `content` language policy.

## L1 Type v2

The current canonical Grace `share_mem/` output uses the v2 memory-role
taxonomy: `decision`, `action_item`, `open_issue`, `proposal`, `argument`,
`finding`, and `approach_change`. It also keeps `legacy_type` for compatibility
diffing against the old taxonomy: `decision`, `todo`, `method_change`,
`result`, `open_question`, and `argument`.

To evaluate prompt or taxonomy changes without overwriting canonical output,
write to an experiment root:

```bash
uv run share_mem/build_tree.py --output-root share_mem_experiments/type_v2_legacy_<timestamp> --taxonomy v2-memory-roles --include-legacy-type --transcript-dir meeting_recording/transcript/grace --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --clean
```

`legacy_type` is migration/debug metadata. It is not canonical memory content.

After an experiment run, compare it with the current baseline:

```bash
uv run share_mem/compare_l1_runs.py --baseline share_mem/tree.json --candidate share_mem_experiments/type_v2_legacy_<timestamp>/tree.json --out share_mem_experiments/type_v2_legacy_<timestamp>/comparison
```

This writes `comparison_report.md`, `comparison_report.json`, and
`manual_review_queue.json`. Promote nothing from the experiment unless the
manual queue and per-meeting gates have been reviewed.

## ICSI Batch Orchestration

Do not run ICSI as one long `build_tree.py` batch. ICSI transcripts are longer
and the multi-agent pipeline can exceed an interactive timeout before the
aggregate `tree.json`, `manifest.json`, and indexes are complete. Use the
per-file orchestrator instead:

```bash
uv run python share_mem/run_icsi_batch.py \
  --transcript-dir meeting_recording/transcript/ISCI \
  --output-root share_mem_experiments/icsi_l1_batch_<timestamp> \
  --transcript-glob "Bmr*.txt" \
  --line-limit 360 \
  --timeout-seconds 7200 \
  --clean
```

The orchestrator processes one transcript or subset at a time, refreshes
`share_mem`-style indexes after each successful file, then writes ICSI review
sidecars under `<output-root>/validation/after_<meeting_id>/`. If a file fails
or times out, the batch status is written and later files are not started unless
`--continue-on-failure` is explicitly set.

Generated orchestration outputs:

- `<output-root>/share_mem/tree.json`: experiment-only aggregate L1 tree.
- `<output-root>/share_mem/meetings/*.json`: per-meeting experiment payloads.
- `<output-root>/validation/after_<meeting_id>/icsi_l1_review_gate.json`: ICSI
  sidecar review/drop gate.
- `<output-root>/batch_status.json`: resumable per-file status with command,
  source hash, stdout/stderr paths, duration, and validation summaries.

Use `--resume` to skip a previously successful transcript when its source hash
has not changed. This runner must not target canonical `share_mem/`; it rejects
that output root.

## Experimental Topic-Tree View

The first `share_mem` topic-tree builder remains available for experiments and
tests, but it is not the active long-term topic layer. The active L2 topic view
now lives under `long_term/l2/` and is built directly from clean immutable L1
evidence.

The experimental topic-tree is an append-only view over canonical L1 evidence.
It does not replace or rewrite `tree.json` or `meetings/<meeting_id>.json`.

Build it after the L1 store is stable:

```bash
uv run share_mem/build_topic_view.py --tree share_mem/tree.json --mode hybrid --model gemini-2.5-pro
```

Useful options:

- `--dry-run`: list meetings and output paths without writing files.
- `--resume`: skip meeting updates whose source hash still matches.
- `--clean-topic-view`: remove topic-tree generated outputs before rebuilding.
- `--force-meeting <meeting_id>`: rebuild a specific meeting update when its
  source hash changed.

Data flow:

```text
share_mem/tree.json
  -> share_mem/build_topic_view.py
  -> topic_updates/<meeting_id>.json append-only deltas
  -> topic_tree.json and topic_index.json materialized by replay
```

When this experimental view is built, `topic_tree.json` is a rebuildable cache
and the source of truth for topic evolution is `topic_updates/`. These root
outputs are not required for the current canonical Grace handoff; check
`manifest.json` `topic_view.exists` before depending on them.

In `--mode hybrid`, the builder first creates deterministic candidates from
related topics, `related_obj_ids`, `memory_relations_index.json`, lexical
overlap, and compact existing topic state. A Gemini assigner then chooses
`assign_existing`, `new_l2`, or `new_l3` within that bounded candidate context
and writes a compact state summary. Unit tests use a fake assigner so they do
not depend on external credentials.

When rebuilding from `--force-meeting`, existing updates before that meeting
are replayed in order, but future updates are not visible to the assignment
step. Later meeting updates are rebuilt against the corrected running state.

## Generated Outputs

Generated and rebuildable files include:

- `tree.json`: aggregate L1 meeting store.
- `meetings/<meeting_id>.json`: one L1 meeting node per meeting.
- `l1_index.json`: lookup index keyed by `obj_id`.
- `manifest.json`: schema version, source directory, meeting IDs, counts, and hash.
- `snapshots/`: bridge snapshots from the share_mem L1 bridge.
- `l1_quality_index.json`, `memory_relations_index.json`, `memory_activity_index.json`: multi-agent sidecars next to `tree.json`.
- `legacy_type`: compatibility label for v2 runs, not canonical memory content.
- optional experiment-only `topic_updates/<meeting_id>.json`, `topic_tree.json`, and `topic_index.json` when `build_topic_view.py` is run.
- `research_logs/`: multi-agent prompts, responses, and structured API-call logs.

`research_logs/` can be large and may contain raw prompts/responses or local
paths. Do not commit sensitive logs, API keys, credentials, or raw Codex
histories.

## Reader API

Use `share_mem.store` instead of reading the archived long-term tree:

- `load_share_tree()`
- `iter_meetings(tree)`
- `iter_l1_objects(tree)`
- `build_l1_index(tree)`
- `get_l1_object(obj_id)`
- `load_recent_meetings(limit=3)`

Short-term and long-term consumers should read through this API instead of
depending on the archived `long_term/archive/legacy_temporal_l2_l3/tree.json`
temporal artifact.

Long-term L2 uses this store as its L1 source. Short-term memory can use this
store or share_mem snapshots to build compact recent working memory.

## Current Generated State

- Grace meetings: 7 (`0307`, `0318`, `0325`, `0408`, `0422`, `0429`, `0506`).
- L1 objects: 448 in the current canonical Grace state.
- Language check: no pure-English `content` objects; `related_topics` remain
  English topic keys.
- Active long-term L2 view: `long_term/l2/`.
- Active short-term JSON state: `short_term/short_term_memory.json`.
