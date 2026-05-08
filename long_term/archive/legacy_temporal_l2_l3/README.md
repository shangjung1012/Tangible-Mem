# Legacy Temporal L2/L3 Archive

This directory stores the old temporal `long_term` pipeline for historical
reference.

Archived here:

- old temporal build and summarize entrypoints: `bridge.py`, `build_tree.py`,
  `summarize.py`, `rebuild_snapshots.py`
- old incremental baseline: `gemini_incremental_extractor.py`,
  `incremental_store.py`, `dataset_profiles.py`, `transcript_utils.py`
- old compatibility aliases for the previous `long_term/multi_agent_*.py`
  import paths
- old documentation, scripts, snapshots, and `tree.json`

Current work should not treat this directory as the active runtime path. New L2
work should read canonical clean L1 evidence from `share_mem/` and write new
generated artifacts under `long_term/l2/`.
