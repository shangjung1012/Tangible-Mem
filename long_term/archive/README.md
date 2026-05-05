# Long-Term Archive

This folder keeps small reference artifacts from older long-term-memory experiments.
It is not part of the active runtime path.

Active code should stay in `long_term/` root modules or `long_term/docs/`.
Generated caches, SQLite working databases, pycache files, and per-run bridge snapshots
should not be archived here because they can be regenerated.

Current archive contents:

- `backup_pre_redesign/tree.json.bak`: compact pre-redesign tree backup.
- `redesign_preview/tree_source.json`: compact redesign preview source tree.
- `method_changes.json`: historical method-change reference output.

Large duplicated snapshot backups were removed from the repository. They remain
recoverable from git history if needed, but should not be kept in the working tree.
