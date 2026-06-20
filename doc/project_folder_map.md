# Project Folder Map

This document defines the current responsibility boundaries in the repository.
Use it to avoid mixing canonical memory evidence, generated topic views, demo
assets, and local experiment outputs.

## Active Application Code

- `app/`: chat app memory routing, context assembly, and system prompt integration.
- `short_term/`: short-term memory implementation.
- `long_term/`: canonical generated L2/L3 topic retrieval surface and validation tooling.
- `memory_observatory/`: Memory Observatory UI, retrieval trace, feedback editor, and comparison experiment tooling.
- `optimization/long_term_v2/`: isolated candidate L2/L3 pipeline for new datasets and shadow-mode evaluation.
- `tests/`: unit and integration tests.

## Canonical / Important Data

- `share_mem/`: shared canonical L1 memory base. `tree.json`,
  `meetings/*.json`, `l1_index.json`, and `manifest.json` are evidence
  artifacts for the current shared-L1 workflow.
- `long_term/l2/`: canonical/legacy generated L2 topic view artifacts.
- `long_term/l3/`: canonical/legacy L3 promotion sidecars, materialized child-L2
  view, merge review, and validation reports.
- `meeting_recording/`: transcript and recording source data used to rebuild
  memory artifacts.

Do not manually edit raw L1 evidence or canonical generated memory artifacts
unless the task explicitly asks for regeneration or promotion.

## Optimization And New Dataset Outputs

- `optimization/runs/`: isolated optimization v2 run roots. These are sidecar
  outputs and should not be copied into `long_term/l2` or `long_term/l3`.
- `optimization/reports/`: compact reports, validation summaries, TAICHI-ready
  interpretation files, and decision catalogs.
- `memory_outputs/`: large dataset runs such as ICSI extraction outputs. For
  downstream ICSI L2/L3, prefer `share_mem_effective` or `filtered_share_mem`
  roots over raw archived `share_mem` roots.
- `share_mem_experiments/`: older local L1/type/topic experiments and comparison
  checkpoints. These are not canonical unless explicitly promoted.

Current policy: optimization v2 is the preferred L2/L3 builder for new datasets,
but it is not an automatic replacement for canonical runtime artifacts.

## Demo And Paper Assets

- `memory_observatory/static/`: production/demo UI assets for the Observatory.
- `memory_observatory/static/presentation.*`: presentation-capture surface for
  TAICHI/demo screenshots when present.
- `docs/presentation_diagrams/`: static diagrams and rendered previews for
  slides or paper figures.
- `doc/taichi/`: TAICHI paper section plans, artifact index, walkthrough script,
  and readiness checklists.

Keep demo assets documented. Do not commit large raw run folders simply because a
screenshot or report depends on them; commit the compact report or figure
instead.

## Generated Logs And Legacy Artifacts

- `memory_observatory/runs/`: Observatory comparison runs. New run folders are
  ignored by git; keep only intentionally preserved demo evidence.
- `share_mem/research_logs/`, `share_mem/snapshots/`: extraction logs and
  recovery snapshots.
- `long_term/archive/`: historical temporal L2/L3 and prototype code.
- `archive/local_temp/`: local temp files preserved for traceability.

## Root Files

- `codex.md`: canonical handoff / current project state notes.
- `README.md`: top-level project entrypoint.
- `pyproject.toml`, `uv.lock`: Python project config and lockfile.
- `.env.example`: example environment configuration.
- `.env`: local credentials/config only; do not commit or expose.

## Cleanup Rules

1. Prefer archiving over deleting when a file may contain experiment evidence.
2. Do not move canonical generated artifacts across module boundaries.
3. Do not edit `share_mem/tree.json`, `share_mem/meetings/*`, or L2/L3 generated views by hand.
4. Before cleaning long-running generated outputs, verify no background rebuild process is still writing them.
5. Keep demo runs only when the corresponding report, screenshot, or paper figure still depends on them.
6. Mark discarded reports explicitly, such as `DO_NOT_USE_*`, and exclude them from paper evidence.
