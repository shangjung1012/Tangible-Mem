# Project Folder Map

這份文件整理目前 repo 主要資料夾的責任邊界，避免把 canonical memory、generated artifacts、local experiments 混在一起處理。

## Active Application Code

- `app/`: chat app memory routing, context assembly, and system prompt integration.
- `short_term/`: short-term memory implementation.
- `long_term/`: active L2/L3 topic retrieval surface and validation tooling.
- `memory_observatory/`: Memory Observatory UI, retrieval trace, feedback editor, and comparison experiment tooling.
- `tests/`: unit and integration tests.

## Canonical / Important Data

- `share_mem/`: shared L1 memory base. `tree.json`, `meetings/*.json`, `l1_index.json`, and `manifest.json` should be treated as canonical generated artifacts for the current shared-L1 workflow.
- `long_term/l2/`: active L2 topic view artifacts.
- `long_term/l3/`: L3 promotion sidecars, materialized child L2 view, merge review, and validation reports.
- `meeting_recording/`: transcript source data used to rebuild memory artifacts.

Do not manually edit raw L1 evidence or generated memory artifacts unless the task explicitly asks for regeneration or promotion.

## Experiment / Generated Outputs

- `memory_observatory/runs/`: observatory comparison runs. Keep runs needed for demos or review; archive/delete only after confirming they are no longer referenced.
- `share_mem_experiments/`: local L1/type/topic experiments and comparison checkpoints. These are not canonical unless explicitly promoted.
- `share_mem/research_logs/`, `share_mem/snapshots/`: generated extraction logs and recovery snapshots.

Current note: `memory_observatory/runs/.gitignore` ignores new run folders by default, but several older observatory run folders are already tracked in Git. Treat this as intentional demo evidence unless there is an explicit cleanup decision to remove tracked generated runs from version control.

Current note: `meeting_recording/recording/grace/*.m4a` contains tracked audio files, including files larger than 20 MB. Do not remove them casually because they may be part of the reproducible transcript source history, but they are the main tracked large-file footprint in the repo.

## Local / Historical Archive

- `archive/local_temp/`: local root-level temp files moved out of the project root. These files are kept for traceability and can be deleted later after review.

Current archived temp files:

- `archive/local_temp/20260510/04_08_bridge_test_results.json`
- `archive/local_temp/20260510/agents.md`
- `archive/local_temp/20260510/test_bridge.py`

## Root Files

- `codex.md`: canonical handoff / current project state notes.
- `README.md`: top-level project entrypoint.
- `pyproject.toml`, `uv.lock`: Python project config and lockfile.
- `.env.example`: example environment configuration.
- `.env`: local credentials/config only; do not commit or expose.

## Cleanup Policy

1. Prefer archiving over deleting when a file may contain experiment evidence.
2. Do not move canonical generated artifacts across module boundaries.
3. Do not edit `share_mem/tree.json`, `share_mem/meetings/*`, or L2/L3 generated views by hand.
4. Before cleaning long-running generated outputs, verify no background rebuild process is still writing them.
5. Keep demo runs until the corresponding report or screenshot no longer depends on them.
