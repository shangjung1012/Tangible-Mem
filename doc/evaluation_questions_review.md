# Evaluation Question Review

Last updated: 2026-05-09

## Overall Assessment

The 14 questions in `doc/evaluation_questions_0307_0506.md` are reasonable for
the current system because they test the intended memory behavior rather than
generic meeting summarization:

- short-term recent state (`VM-E01`, `VM-E02`, `VM-E05`);
- long-term topic evolution and decision rationale (`VM-E03`, `VM-E04`,
  `VM-E06`, `VM-E07`, `VM-E09`, `VM-E11`);
- hybrid short-term plus long-term routing (`VM-E08`, `VM-E10`, `VM-E12`,
  `VM-E14`);
- one stretch preprocessing assumption check (`VM-E13`).

The strongest demo questions are:

- `VM-E03`: transcript segmentation design evolution;
- `VM-E04`: why fixed 80-line plus verify/repair replaced adaptive segmentation;
- `VM-E06`: forgetting / fade-out evolution;
- `VM-E07`: why plain RAG or full transcript is not enough;
- `VM-E08`: evaluation baseline and metric design;
- `VM-E10`: why short-term and long-term update in parallel;
- `VM-E11`: why long-term memory moved toward L1/L2/L3;
- `VM-E14`: fade-out demo value and human control.

Use `VM-E01`, `VM-E02`, `VM-E05`, and `VM-E09` as quick sanity checks. Use
`VM-E13` as a stretch question; it is useful but less central to the project
claim.

## CSV Artifact

The normalized table is:

- `doc/evaluation_questions_0307_0506.csv`

It preserves the gold metadata and adds analysis columns:

- `demo_priority`
- `demo_note`
- `actual_route`
- `retrieved_l1_obj_ids`
- `agent_answer`
- `baseline_rag_answer`
- `baseline_transcript_answer`
- `correctness_score`
- `evidence_hit_score`
- `hallucination_flag`
- `memory_context_path`
- `judge_notes`

## Batch Runner

Run a small subset across structured memory, plain RAG, and full transcript
baseline:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python app/run_evaluation_questions.py \
  --ids VM-E03,VM-E07,VM-E11 \
  --output doc/evaluation_runs/demo_answers.csv
```

Run the first two questions:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python app/run_evaluation_questions.py \
  --limit 2 \
  --output doc/evaluation_runs/smoke_answers.csv
```

The runner writes retrieved contexts to `doc/evaluation_runs/contexts/` and
stores answers plus retrieved L1 ids in the output CSV. By default it runs all
three methods:

- `structured`: router plus short/long memory retrieval with L1/L2/L3 context;
- `rag`: embedding raw-transcript chunk retrieval without L2/L3;
- `transcript`: oracle full-transcript baseline using each row's
  `gold_meeting_ids`.

To run only one method:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python app/run_evaluation_questions.py \
  --methods structured \
  --output doc/evaluation_runs/structured_only.csv
```

## Baseline Recommendation

For a credible experiment, include baselines, but keep them script-level rather
than building a full app:

1. **Full transcript baseline**: give the raw relevant transcripts or a
   transcript-window retrieval result to the same answer model.
2. **Embedding RAG baseline**: retrieve chunks from raw transcripts using
   embedding similarity, without L1/L2/L3 sidecar expansion.
3. **Memory system**: current router plus short-term/long-term retrieval with
   L1 -> L2 -> L3 context.

This is enough to test whether the structured memory system improves answer
faithfulness, evidence coverage, and topic-evolution questions. A full product
baseline UI is not needed before the project demo.
