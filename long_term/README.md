# Long-Term Memory

`long_term/` is now the active surface for recall and the L2 view over
canonical `share_mem` L1 evidence.

Canonical L1 extraction lives in `share_mem/l1/`, and canonical Grace L1 outputs
live under `share_mem/`. Do not use `long_term/tree.json` as a current source of
truth; it has been archived with the old temporal pipeline.

## Active Contract

- L1 source: `share_mem/tree.json` and `share_mem/meetings/<meeting_id>.json`.
- Recall surface: `recall.py`, `recall_planner.py`, `schema.py`, `embedder.py`.
- Shared compatibility helpers: `importance.py`, `memory_activity.py`,
  `memory_relations.py`, `l1_quality.py`, `gemini_clients.py`, `io_utils.py`.
- L2 view commands:

```powershell
uv run long_term/cli.py build-l2-view --share-mem-root share_mem --output-root long_term/l2 --mode deterministic --clean
uv run long_term/cli.py validate-l2-view --share-mem-root share_mem --root long_term/l2 --out long_term/l2/validation
uv run long_term/cli.py build-l2-view --help
uv run long_term/cli.py validate-l2-view --help
```

The first L2 implementation is deterministic and does not call Gemini. It reads
clean immutable L1 objects from `share_mem`, links only L1 objects with a durable
long-term direction, and writes generated L2 artifacts under `long_term/l2/`.

Generated L2 outputs:

- `long_term/l2/l2_view.json`: materialized L2 directions with compact state,
  timeline digest, linked L1 object ids, and meeting ids.
- `long_term/l2/l2_index.json`: `obj_id -> l2_id / l2_label / assignment`
  lookup for retrieval.
- `long_term/l2/l2_updates/<meeting_id>.json`: per-meeting append-only L2
  assignment events.
- `long_term/l2/unlinked_l1_report.json`: L1 objects intentionally not linked
  to L2, plus a review queue for high-importance misses.
- `long_term/l2/validation/`: validator reports and manual review queue.

## Archived Legacy Pipeline

The old temporal L1/L2/L3 pipeline, incremental baseline, old snapshots, and old
temporal tree are archived under:

```text
long_term/archive/legacy_temporal_l2_l3/
```

That archive is historical reference only. Active code should not import from it
unless a test is explicitly covering legacy behavior.

Archived commands include:

- `bridge`
- `summarize`
- `build-tree`
- `rebuild-snapshots`
- `smoke-todo`
- `eval-injection`

Running one of those through `long_term/cli.py` now prints an archive notice
instead of dispatching the old workflow.

## Current Direction

The next L2 layer should read clean immutable L1 objects from `share_mem` and
group only the L1 evidence that deserves long-term abstraction. It does not need
to link every L1 object. Unlinked low-value or isolated L1 objects should be
reported for review rather than forced into an L2 node.

Current generated Grace state:

- Source L1: 7 Grace meetings, 545 L1 objects.
- L2 view: 17 L2 directions, 428 linked L1 objects, 117 intentionally
  unlinked low-review L1 objects.
- Validation: 0 severe issues. Current warnings are large-topic diagnostics for
  broad long-running directions, not schema blockers.
