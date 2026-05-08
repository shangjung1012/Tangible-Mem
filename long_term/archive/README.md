# Long-Term Archive

This folder keeps small reference artifacts from older long-term-memory experiments.
It is not part of the active runtime path.

Active code should stay in `long_term/` root modules. Historical docs that
belong to the old temporal pipeline can live in this archive.
Generated caches, SQLite working databases, pycache files, and per-run bridge snapshots
should not be archived here because they can be regenerated.

Current archive contents:

- `backup_pre_redesign/tree.json.bak`: compact pre-redesign tree backup.
- `redesign_preview/tree_source.json`: compact redesign preview source tree.
- `method_changes.json`: historical method-change reference output.
- `legacy_temporal_l2_l3/`: archived old temporal build/summarize pipeline,
  incremental baseline, old snapshots, and old temporal tree.

Large duplicated snapshot backups were removed from the repository. They remain
recoverable from git history if needed, but should not be kept in the working tree.
