# Long-Term Memory

`long_term/` is now the active surface for recall and the upcoming L2 view over
canonical `share_mem` L1 evidence.

Canonical L1 extraction lives in `share_mem/l1/`, and canonical Grace L1 outputs
live under `share_mem/`. Do not use `long_term/tree.json` as a current source of
truth; it has been archived with the old temporal pipeline.

## Active Contract

- L1 source: `share_mem/tree.json` and `share_mem/meetings/<meeting_id>.json`.
- Recall surface: `recall.py`, `recall_planner.py`, `schema.py`, `embedder.py`.
- Shared compatibility helpers: `importance.py`, `memory_activity.py`,
  `memory_relations.py`, `l1_quality.py`, `gemini_clients.py`, `io_utils.py`.
- Upcoming L2 commands:

```powershell
uv run long_term/cli.py build-l2-view --help
uv run long_term/cli.py validate-l2-view --help
```

The command names are reserved so partner work can target stable entrypoints.
The actual L2 builder/validator implementation will be added in the next L2
quality loop.

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
