# Long-Term Memory

`long_term/` owns the active long-term recall surface and generated L2/L3 views
over canonical L1 evidence from `share_mem/`.

Do not use `long_term/tree.json` as a current source of truth; the old temporal
pipeline is archived under `long_term/archive/legacy_temporal_l2_l3/`.

## Active Contract

- L1 source: `share_mem/tree.json` and `share_mem/meetings/<meeting_id>.json`.
- Recall: `long_term/recall.py`.
- Planner: `long_term/recall_planner.py`.
- L2 builder: `long_term/build_l2_view.py`.
- L2 validator: `long_term/validate_l2_view.py`.
- CLI: `long_term/cli.py`.

## Build And Validate L2

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
```

The current L2 implementation is deterministic and does not call Gemini. It
links durable L1 objects to long-term topics and may intentionally leave
low-value or isolated L1 objects unlinked.

L2 topics are built from L1 `related_topics` first, not from a fully hand-written
topic list. The builder normalizes topic hints by lowercasing, replacing
underscores/hyphens with spaces, removing punctuation, dropping generic or
type-like labels, mapping aliases to canonical L2 labels, and deduplicating by
canonical label. Content keyword rules only confirm or refine those seeds,
especially when the seed is broad.

L3 promotion is deterministic by default. To let Gemini assist only the L3
split stage, run:

```bash
uv run long_term/cli.py build-l2-view \
  --share-mem-root share_mem \
  --output-root long_term/l2 \
  --mode deterministic \
  --l3-mode llm-assisted \
  --l3-source-l2-id L2-memory-evaluation-strategy
```

## Generated Outputs

- `long_term/l2/l2_index.json`: `obj_id -> l2_id / l2_label / assignment`.
- `long_term/l2/l2_view.json`: compact L2 state, timeline digest, linked L1 ids.
- `long_term/l2/l2_updates/<meeting_id>.json`: per-meeting L2 assignment events.
- `long_term/l2/unlinked_l1_report.json`: skipped L1 objects and review queue.
- `long_term/l2/l2_assignment_review_report.json`: topic size and assignment review summary.
- `long_term/l2/validation/`: validation reports.
- `long_term/l3/l3_promotions.json`: oversized L2 promotion candidates.
- `long_term/l3/l3_view.json`: materialized L3 parents with child L2 nodes.
- `long_term/l3/l3_index.json`: `obj_id -> L3 / child L2` lookup.

## Recall Path

Long-term recall is bottom-up:

```text
query
  -> semantic L1 retrieval from share_mem/tree.json
  -> l2_index.json lookup by obj_id
  -> l2_view.json compact topic context
  -> optional l3_promotions.json review context
  -> optional l3_view.json materialized child L2 context
  -> formatted prompt context
```

Missing L2 assignments are non-fatal. Legacy temporal phase/profile expansion is
compatibility fallback only.

## L3 Promotion

L3 means overflow promotion above L2. If an L2 topic becomes too broad, it can
be promoted into an L3 parent and split into multiple child L2 topics.

The current L3 implementation is materialized as sidecars only:

- hard warning: `linked_l1_count >= 24`
- soft warning: `linked_l1_count >= 12` and `l1_share >= 0.30`
- promotion review sidecar: `long_term/l3/l3_promotions.json`
- materialized child L2 sidecars: `long_term/l3/l3_view.json` and
  `long_term/l3/l3_index.json`

This does not rewrite raw L1 evidence, `l2_index.json`, or `l2_view.json`.

The default materialization does not call an LLM. With
`--l3-mode llm-assisted`, Gemini is used only inside the L3 sidecar pipeline.
Large L2 topics that already have reviewed deterministic child splits keep
those splits; Gemini is called for oversized L2 topics that do not yet have
child L2 candidates. Use `--l3-source-l2-id` to limit the API call to one
oversized L2 during review:

1. propose child L2 taxonomy from that promoted L2's linked L1 compact evidence;
2. suggest `obj_id -> child_l2_id` assignments for those same L1 rows;
3. validate every assignment deterministically, falling back to
   `assignment_criteria` and marking low-confidence or invalid suggestions for
   manual review.

Even in LLM-assisted mode, raw L1 evidence, `l2_index.json`, and `l2_view.json`
are not rewritten.

## Current Generated State

- Source L1: 7 Grace meetings, 509 L1 objects.
- L2 view: 15 L2 topics, 477 linked L1 objects, 32 unlinked L1 objects.
- Validation: 0 severe issues; 0 manual-review warnings.
- Materialized L3: 2 parents, 6 child L2 topics, 184 assigned L1 objects, 0 unassigned L1 objects.
- Reviewed deterministic L3: `L3-transcript-segmentation-and-idea-unit-coverage`.
- LLM-assisted L3: `L3-memory-evaluation-strategy`.

## Archive Boundary

The old temporal L1/L2/L3 pipeline, old snapshots, and prototype viewers are
under `long_term/archive/`. They are historical reference only and are not
exposed through active CLI commands.
