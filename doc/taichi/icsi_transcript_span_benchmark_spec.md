# ICSI Transcript-Span Grounded Benchmark Spec

This document defines the evaluation redesign for Tangible Mem on the ICSI BMR meetings. The goal is to avoid using AI-generated L1 objects as the gold standard. L1 objects are useful retrieval artifacts, but the primary benchmark evidence must be auditable against the original transcript.

## Why L1 Cannot Be Primary Gold

Generated L1 objects are produced by our own pipeline. If a benchmark asks whether a system retrieves a generated L1 object and then treats that L1 object as the gold evidence, the benchmark can become circular:

- The system is rewarded for matching its own compression of the transcript.
- Errors in L1 extraction can become invisible if the same L1 is used as both artifact and gold.
- Competing systems that retrieve raw transcript spans may be unfairly penalized if they do not match our L1 identifiers.

Therefore, for ICSI, L1 ids are allowed only as optional diagnostic alignment. The primary gold evidence is a transcript span with a human-written evidence brief.

## Benchmark Task

Use a held-out future-meeting carryover design.

1. Split BMR meetings into past meetings and held-out future meetings.
2. Inspect a future meeting for a carryover trigger: a point where participants revisit a topic, decision, rationale, unresolved issue, technical setup, or data concern that should have been remembered from earlier meetings.
3. Write a question from the perspective of preparing for or understanding that future discussion.
4. Annotate the past transcript spans that support the answer.
5. Optionally map the transcript spans to generated L1 ids and topic labels for diagnostic analysis only.

This tests whether a memory system can recover relevant past context before a later meeting discussion, without treating our generated memory objects as the only valid answer source.

## Query Schema

```json
{
  "query_id": "icsi-carryover-001",
  "query": "Before the later audio-processing discussion, what earlier context about close microphones and beamforming should the system remember?",
  "query_type": "carryover_context",
  "held_out_meeting_id": "BmrXXX",
  "trigger_span": {
    "meeting_id": "BmrXXX",
    "source_file": "BmrXXX.txt",
    "line_start": 120,
    "line_end": 145,
    "brief": "Future meeting revisits whether close microphones or beamforming should be emphasized."
  },
  "gold_transcript_spans": [
    {
      "meeting_id": "BmrYYY",
      "source_file": "BmrYYY.txt",
      "line_start": 210,
      "line_end": 236,
      "brief": "Past discussion explains why close microphones were preferred over relying only on delay-and-sum beamforming."
    }
  ],
  "optional_alignment": {
    "expected_l1_ids": [],
    "expected_l2_labels": [],
    "expected_l3_labels": []
  },
  "notes": "L1 and topic labels are diagnostic alignment targets, not primary gold evidence."
}
```

## Primary Metrics

### Transcript Evidence Recall

Measures whether retrieved context covers the human-annotated transcript spans or a human-approved equivalent span.

Recommended scoring:

- `1.0`: retrieved context directly includes the gold span or a clearly equivalent overlapping span.
- `0.5`: retrieved context includes the same discussion but misses the most important lines.
- `0.0`: retrieved context does not include the supporting transcript evidence.

For multi-span questions, average over gold spans.

### Answer Correctness

Measures whether the final answer accurately uses the retrieved evidence to answer the carryover question.

Suggested rubric dimensions:

- factual correctness
- completeness
- evidence grounding
- source traceability
- hallucination risk
- topic evolution, only for evolution/rationale questions

### Source Traceability

Measures whether the answer can point back to concrete meeting evidence:

- transcript meeting id
- line range or timestamp span
- short source brief

## Secondary Diagnostics

### L1 Alignment Recall

Measures whether retrieved L1 objects overlap with optional human-mapped L1 ids. This is useful for diagnosing whether our L1 compression captured the transcript evidence, but it is not the primary gold.

### Expected L2/L3 Hit

Measures whether the retrieved topic context semantically matches expected topic labels or topic families. This checks whether the memory hierarchy helps navigation, but L2/L3 hits should not override missing transcript evidence.

### Context Cost

Record estimated input tokens, total tokens, and truncation for each strategy:

- full transcript / full context
- RAG baseline
- Tangible Mem layered retrieval
- any external memory baseline

## Annotation Workflow

1. Select held-out future BMR meetings.
2. Read the future transcript and mark carryover triggers.
3. For each trigger, search earlier transcripts for supporting spans.
4. Write a short evidence brief for each source span.
5. Write a query that asks what the system should remember before or during the future discussion.
6. Optionally map spans to generated L1 objects and topic labels.
7. Have a second reviewer check whether the gold spans are sufficient and not overly broad.

## Fairness Rules

- Do not require competitors to retrieve Tangible Mem L1 ids.
- Do not count an L1 match as correct unless it can be traced back to the gold transcript span.
- Do not let an L2/L3 topic hit compensate for missing source evidence.
- If multiple transcript spans support the same answer, allow human-approved equivalent spans.
- Keep held-out trigger spans separate from past gold spans; the future trigger explains the query but should not be used as past evidence.

## Relationship To Existing ICSI Diagnostics

Existing ICSI evaluation packs that use expected L1 ids should be treated as engineering diagnostics. They are useful for debugging whether Tangible Mem retrieves its own effective L1 artifacts, but they are not sufficient for public-corpus evidence claims.

For TAICHI paper claims, the safer wording is:

- Supported now: Tangible Mem has an internal Grace benchmark and ICSI retrieval diagnostics.
- Planned benchmark path: ICSI transcript-span grounded evaluation.
- Not yet supported: user-facing correction improves memory quality in a controlled study.

## Current V1 Seed Artifact

The current annotation-ready seed artifact was generated with:

```powershell
uv run python optimization/long_term_v2/icsi_transcript_span_benchmark.py `
  --transcript-root meeting_recording/transcript/ISCI `
  --out optimization/reports/icsi_transcript_span_benchmark_v1_20260622 `
  --source-through-meeting-id Bmr023 `
  --max-questions 12 `
  --clean
```

Outputs:

- `optimization/reports/icsi_transcript_span_benchmark_v1_20260622/transcript_span_queries.jsonl`
- `optimization/reports/icsi_transcript_span_benchmark_v1_20260622/transcript_span_benchmark_report.json`
- `optimization/reports/icsi_transcript_span_benchmark_v1_20260622/transcript_span_benchmark.md`

The artifact is intentionally marked `annotation_ready_needs_human_review`.
It should be treated as a starting point for annotation, not as final gold.
