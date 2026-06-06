# Optimization TODO

## Dataset Onboarding Pipeline

Status: planned.

Output contract: use `memory_outputs/` for new dataset runs and future Grace
reruns. See `optimization/OUTPUT_LAYOUT.md`.

Goal: turn new mentor-mentee / research-meeting dataset adaptation into a
repeatable system workflow instead of one-off prompt editing.

Current working assumption:

- New datasets should start with a dataset profile, not a forked pipeline.
- A profile should describe transcript structure, language, noise policy,
  durability policy, chunk/window defaults, and validation thresholds.
- Small probe runs are required before full extraction because L1 extraction is
  expensive and profile settings are rarely correct on the first try.
- Dataset-specific cleanup should be sidecar-first. Raw L1 evidence should stay
  immutable; filtered/effective views can be produced for L2/L3 experiments.
- For ICSI BMR archive imports, L2/L3 must read the effective filtered view:
  `memory_outputs/icsi/archive_imports/<batch>/filtered_share_mem/`.
  Do not build ICSI L2/L3 from the archived raw `share_mem/` folders.

Proposed workflow:

1. Create or select a dataset profile.
2. Run a small probe, such as 3-5 files or first N transcript lines.
3. Produce L1 quality, coverage, duplicate, setup/source-data, and importance
   reports.
4. Produce suggested profile changes from validation results.
5. Let a reviewer accept, reject, or edit suggested changes.
6. Re-run the probe and compare against the previous run.
7. Expand to a medium batch only after L1 gates are stable.
8. Build optimization v2 L2/L3 from the filtered/effective L1 sidecar. For
   multi-batch ICSI work, first merge archive `filtered_share_mem/` roots into a
   combined `share_mem_effective/`, then run `optimization/long_term_v2`.
9. Validate L2/L3 topic quality and retrieval behavior.
10. Only after repeated stable runs, consider shadow-mode runtime use.

Desired command shape:

```powershell
uv run python optimization/onboard_dataset.py `
  --transcript-dir meeting_recording/transcript/ISCI `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --probe-files 5 `
  --line-limit 360 `
  --out optimization/runs/isci_onboarding_001
```

Expected outputs:

- `profile_calibration_report.json/md`
- `l1_quality_report.json/md`
- `l1_review_gate.json/md`
- `suggested_profile_changes.json/md`
- `effective_share_mem/`
- `l2_l3_preview/`
- `onboarding_decision_report.json/md`

Open design questions:

- How much automatic profile editing is acceptable before human review?
- Which validation failures should block the next batch versus only enter
  manual review?
- How should the system estimate expected runtime and API cost before a probe?
- How should probe results compare across runs without relying on fixed topic
  IDs?
- When should a dataset-specific sidecar gate be promoted into a reusable
  profile rule?

Non-goals for now:

- Do not claim arbitrary-domain generality.
- Do not overwrite canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.
- Do not use canonical `long_term/l2` or `long_term/l3` for ICSI L2/L3 previews;
  that legacy builder still carries Grace topic ontology risk.
- Do not auto-promote optimization v2 outputs into runtime without explicit
  approval.
