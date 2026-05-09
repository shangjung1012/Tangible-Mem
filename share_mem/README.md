# Share Memory

`share_mem/` is the canonical L1 memory store for new work. It is built from
meeting transcripts with the canonical multi-agent L1 pipeline in
`share_mem/l1/`.

For collaborator handoff, see `share_mem/STATUS.md`. It records the stable
integration surfaces and the parts still under the ultimate quality loop.

## Rebuild

```bash
uv run share_mem/build_tree.py --transcript-dir meeting_recording/transcript/grace --output-root share_mem --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --taxonomy v2-memory-roles --include-legacy-type --clean
```

The command processes every `.txt` file under the transcript directory in
filename order. For the Grace set, `0307.txt` maps to meeting date
`2026-03-07`, `0429.txt` maps to `2026-04-29`, and so on.

Build flow:

```text
share_mem/build_tree.py
  -> share_mem.l1.bridge
  -> share_mem.l1.multi_agent_pipeline
  -> segmentation / boundary refinement / idea units / extraction packets
     / typed agents / grounding / verifier / reducer
  -> outputs under share_mem/
```

An extraction packet is a bounded working unit, not a memory layer: the pipeline
groups related idea units into a small packet so each typed L1 agent sees a
controlled scope before producing L1 candidates. The packet is intentionally
between idea units and candidates:

```text
segment -> idea unit -> extraction packet -> candidate -> L1 object
```

`long_term/` keeps the active recall surface and reserved L2 view entrypoints.
The old temporal pipeline and older import paths are archived under
`long_term/archive/legacy_temporal_l2_l3/`; the multi-agent L1 source of truth
is now under `share_mem/l1/`.

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

These files are generated and can be rebuilt:

- `tree.json`: aggregate L1 meeting store.
- `meetings/<meeting_id>.json`: one L1 meeting node per meeting.
- `l1_index.json`: lookup index keyed by `obj_id`.
- `manifest.json`: schema version, source directory, meeting IDs, counts, and hash.
- `snapshots/`: bridge snapshots from the share_mem L1 bridge.
- `l1_quality_index.json`, `memory_relations_index.json`, `memory_activity_index.json`: multi-agent sidecars next to `tree.json`.
- `legacy_type`: compatibility label for v2 runs, not canonical memory content.
- optional experiment-only `topic_updates/<meeting_id>.json`, `topic_tree.json`, and `topic_index.json` when `build_topic_view.py` is run.

`research_logs/` contains multi-agent stage artifacts and can be large. New
runs write `extraction_packets.json` for the bounded idea-unit packets consumed
by typed L1 agents; `extraction_batches.json` may also be present as a legacy
compatibility alias. Each run includes `prompts/`, `responses/`, and structured
`api_calls/` debug artifacts for LLM input/output inspection. Do not commit raw
prompts, responses, credential paths, API keys, or raw Codex JSONL.

## Reader API

Use `share_mem.store` for shared L1 reads:

- `load_share_tree()`
- `iter_meetings(tree)`
- `iter_l1_objects(tree)`
- `get_l1_object(obj_id)`
- `load_recent_meetings(limit=3)`

Short-term and long-term consumers should read through this API instead of
depending on the archived `long_term/archive/legacy_temporal_l2_l3/tree.json`
temporal artifact.
