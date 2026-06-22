# Tangible Mem Claim Boundary And Evaluation Update

This note records the concrete system and paper-facing changes made after the
claim-boundary review. It is intended as an internal handoff for writing and
review, not as paper prose.

## System Name And Claim Boundary

- System name: Tangible Mem.
- Main UI component: Memory Observatory interface.
- Main capability claim: inspectable and correctable hierarchical memory.
- Avoid unqualified "editable" claims. Use "correctable" or "editable
  effective memory view through sidecar corrections."

The core evidence boundary remains:

- Raw transcript evidence remains immutable.
- Raw L1 provenance remains immutable.
- L2/L3 are derived topic context and navigation layers.
- Sidecars change the effective memory view, not the raw evidence.

## Correctable Memory Surface

Implemented sidecar records now cover:

- importance override
- effective-summary correction
- validity flag
- topic-link review

These are exposed in the Memory Observatory `Correction Review` tab and through
FastAPI endpoints. The current ICSI demo dataset remains read-only for screenshot
and paper artifact stability; the implemented write path is available for the
Grace dataset and any future writable dataset config.

Paper implication:

- It is fair to say Tangible Mem implements non-destructive correction pathways.
- It is not fair to say a user study has shown that these corrections improve
  memory quality.

## ICSI Transcript-Span Benchmark

The ICSI benchmark path now has an executable seed builder:

```powershell
uv run python optimization/long_term_v2/icsi_transcript_span_benchmark.py `
  --transcript-root meeting_recording/transcript/ISCI `
  --out optimization/reports/icsi_transcript_span_benchmark_v1_20260622 `
  --source-through-meeting-id Bmr023 `
  --max-questions 12 `
  --clean
```

Current generated artifact:

- `optimization/reports/icsi_transcript_span_benchmark_v1_20260622/transcript_span_queries.jsonl`
- `optimization/reports/icsi_transcript_span_benchmark_v1_20260622/transcript_span_benchmark_report.json`
- `optimization/reports/icsi_transcript_span_benchmark_v1_20260622/transcript_span_benchmark.md`

Important boundary:

- The generated rows are annotation-ready seeds.
- They are not completed human gold.
- Primary gold is transcript span evidence.
- Generated L1 ids are diagnostic alignment only.

Paper implication:

- It is fair to describe this as the planned public-corpus evaluation path.
- It is not fair to report these seeds as final benchmark results until human
  review approves trigger spans, source spans, and evidence briefs.

## User Study Package

Prepared artifacts:

- `doc/taichi/user_study_pilot_protocol.md`
- `doc/taichi/user_study_task_packet.md`
- `doc/taichi/user_study_scoring_sheet.csv`

Paper implication:

- It is fair to say a pilot protocol has been prepared.
- It is not fair to say the user study has been completed.

## Section-Level Paper Changes

Section 3 should emphasize:

- research-meeting memory failures involve decisions, rationale, unresolved
  issues, and topic evolution;
- L1/L2/L3/sidecar have different evidence status;
- sidecar correction is correction of the effective view, not source rewriting.

Section 4 should emphasize:

- Memory Observatory exposes retrieval traces and topic state for inspection;
- Correction Review writes append-only sidecars;
- raw evidence and raw L1 provenance remain unchanged.

Section 5 should use the ICSI walkthrough as a demonstration of inspection and
traceability, not as completed user-study evidence.

Section 6 should separate:

- existing Grace and ICSI technical diagnostics;
- transcript-span ICSI benchmark path;
- planned user study.
