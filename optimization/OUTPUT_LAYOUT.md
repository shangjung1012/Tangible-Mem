# Memory Output Layout

This project keeps generated memory artifacts separate from canonical runtime
artifacts until an explicit promotion decision is made.

## Canonical Runtime Artifacts

These paths are treated as read-only during experiments:

- `share_mem/tree.json`
- `share_mem/meetings/`
- `share_mem/l1_index.json`
- `share_mem/manifest.json`
- `long_term/l2/`
- `long_term/l3/`

Do not use them as output roots for probes, reruns, or dataset onboarding.

## Isolated Output Area

Use `memory_outputs/` for new dataset runs and future Grace reruns:

```text
memory_outputs/
  grace/
    runs/
      grace_full_<run_id>/
  icsi/
    runs/
      bmr_first360_<run_id>/
      bmr_full_<run_id>/
  synthetic/
    runs/
  promotion_candidates/
```

Every run root can contain:

```text
run_manifest.json
share_mem/
filtered_share_mem/
l2_l3/
validation/
reports/
api_calls/
orchestration_logs/
input_transcripts/
batch_status.json
```

`run_manifest.json` records source hashes and run configuration so a probe can be
audited later.

The run contents under `memory_outputs/` are local generated artifacts and are
ignored by git. Only `memory_outputs/.gitkeep` is tracked so the output area is
visible in a fresh checkout.

## ICSI Batch Example

```powershell
uv run python share_mem/run_icsi_batch.py `
  --transcript-dir meeting_recording/transcript/ISCI `
  --output-base memory_outputs `
  --run-id bmr012_016_first360_20260605 `
  --transcript-glob "Bmr*.txt" `
  --line-limit 360 `
  --max-files 5 `
  --timeout-seconds 7200 `
  --continue-on-failure
```

This writes to:

```text
memory_outputs/icsi/runs/bmr_first360_bmr012_016_first360_20260605/
```

It does not write to canonical `share_mem/`.

## Combining Completed ICSI Probe Batches

Use `optimization/combine_share_mem_runs.py` to create one effective share_mem
root from multiple filtered batch outputs:

```powershell
uv run python optimization/combine_share_mem_runs.py `
  --archive-import-manifest memory_outputs/icsi/archive_imports/import_manifest.json `
  --output-base memory_outputs `
  --dataset icsi `
  --run-kind bmr_first360_combined `
  --run-id bmr001_011_first360_20260605 `
  --clean
```

This writes:

```text
memory_outputs/icsi/runs/bmr_first360_combined_bmr001_011_first360_20260605/
  combine_manifest.json
  share_mem_effective/
    tree.json
    manifest.json
    l1_index.json
    meetings/
```

L2/L3 preview work should read the combined `share_mem_effective/` root.

For archive imports, the combine command reads only:

```text
memory_outputs/icsi/archive_imports/<batch>/filtered_share_mem/
```

The archived raw `share_mem/` folders are intentionally ignored. They preserve
the original extraction output, but the filtered view is the effective L1 surface
after ICSI sidecar gates. This matters for L2/L3 because source-data-only,
duplicate, or setup-noise L1 objects should not become durable topics unless a
reviewer explicitly accepts them later.

Run ICSI L2/L3 with the isolated optimization v2 pipeline, not canonical
`long_term/l2` or `long_term/l3`:

```powershell
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root memory_outputs/icsi/runs/bmr_first360_combined_bmr001_011_first360_20260605/share_mem_effective `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --out optimization/runs/icsi_bmr001_011_first360_l2_l3_20260605 `
  --mode deterministic `
  --clean

uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/icsi_bmr001_011_first360_l2_l3_20260605

uv run python optimization/long_term_v2/audit_topic_quality.py `
  --run-root optimization/runs/icsi_bmr001_011_first360_l2_l3_20260605 `
  --out optimization/runs/icsi_bmr001_011_first360_l2_l3_20260605/topic_quality
```

The effective L1 snapshot can live under `memory_outputs/`; the v2 topic output
still lives under `optimization/runs/` because the v2 writer enforces that
isolation boundary.

## Grace Rerun Dry Run

Generate the isolated Grace rebuild commands first:

```powershell
uv run python optimization/run_grace_memory_build.py `
  --output-base memory_outputs `
  --run-id grace_rebuild_20260605
```

This prints commands that would write Grace outputs to:

```text
memory_outputs/grace/runs/grace_full_grace_rebuild_20260605/
```

Use `--execute` only after reviewing the printed commands.

## Promotion Boundary

Outputs under `memory_outputs/` are not runtime artifacts. Promotion requires a
separate decision and validation report. Until then, app runtime should continue
using the existing canonical artifacts or an explicit shadow-mode adapter.
