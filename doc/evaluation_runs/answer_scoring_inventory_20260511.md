# Answer Scoring Inventory - 2026-05-11

## Existing Artifacts

- `doc/evaluation_runs/all_questions_three_methods_all_transcripts.csv`
  - Generation-stage answers for 14 evaluation questions.
- `doc/evaluation_runs/all_questions_three_methods_scored.csv`
  - First-pass judge results for Structured, RAG, and Full transcript answers.
- `doc/evaluation_runs/per_question_method_type_scores_v2.csv`
  - Cleaner v2 answer/evidence quality scores with shared metrics and type-specific metrics.
- `doc/evaluation_runs/cost_quality_summary.csv`
  - Aggregated correctness, score, and token cost summary.
- `doc/evaluation_runs/method_category_summary.csv`
  - Category-level breakdown by method and answer type.
- `doc/evaluation_runs/token_analysis.md`
  - Token accounting for generation and judge stages.
- `app/score_evaluation_answers.py`
  - Legacy judge script that scores generated answers into `all_questions_three_methods_scored.csv`.
- `app/score_evaluation_answers_v2.py`
  - V2 judge script that writes `per_question_method_type_scores_v2.csv`.
- `memory_observatory/export_scoring_csv.py`
  - Converts `memory_observatory/runs/<run_id>/results.json` into the v2 judge CSV shape.

## Current Scored Result

The existing scored dataset has 14 questions and evaluates each method twice:
`Answer` and `Evidence`, for 84 judged rows total in the v2 score file.

### V2 Quality Scores

| Method | Rows | Yes | Yes Rate | Avg Final Quality |
|---|---:|---:|---:|---:|
| Full Transcript | 28 | 27 | 96.4% | 4.814 |
| Structured | 28 | 19 | 67.9% | 4.193 |
| RAG | 28 | 7 | 25.0% | 3.264 |

### Cost / Quality Summary

| Method | Rows | Correct | Correct Rate | Avg Score | Avg Context Tokens | Total Tokens |
|---|---:|---:|---:|---:|---:|---:|
| Structured | 28 | 19 | 67.9% | 3.94 | 4,201.6 | 184,503 |
| RAG | 28 | 10 | 35.7% | 2.82 | 4,482.1 | 185,399 |
| Full transcript | 28 | 28 | 100.0% | 4.86 | 80,956.8 | 2,341,603 |

## Interpretation

- Structured memory clearly beats RAG on answer quality in this scored run:
  67.9% vs 25.0% v2 yes-rate, with similar total token cost.
- Full transcript still wins quality, but at roughly 12.7x the total tokens of
  Structured memory in the existing scored dataset.
- The strongest Structured categories are `decision_reasoning` and
  `conflict_or_update`.
- The weakest Structured categories are cross-meeting evidence completeness and
  topic-synthesis cases that require the earliest meeting in an evolution chain.

## Important Caveat

This is not yet the score for the latest `memory_observatory` run or the current
`large_corpus_tight` retrieval profile. It is an older app-evaluation scored
dataset. It is still useful as evidence that the structured memory approach can
beat RAG at comparable cost, but the latest 6000-character budget and current
L2/L3 retrieval profile need a fresh answer-level run before claiming current
answer-quality numbers.

## Latest Observatory Answer-Only Score

Run:

- `memory_observatory/runs/observatory_20260511_141739`
- query file: `doc/evaluation_questions_0307_0506.csv`
- strategies: Full Context, RAG, Layered Memory
- answer generation: Gemini Pro
- planner: no-LLM heuristic
- local prompt budget: 6000 chars
- judge output: `observatory_scores_v2.csv`
- scoring mode: Answer only

| Method | Rows | Yes | Yes Rate | Avg Final Quality | Avg Context Tokens | Avg Total Tokens | Avg Total ms | Truncation Rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Structured | 14 | 7 | 50.0% | 3.982 | 3,051.4 | 5,110.1 | 21,118.4 | 0.0% |
| RAG | 14 | 5 | 35.7% | 3.626 | 3,825.7 | 5,456.4 | 23,881.0 | 100.0% |
| Full Transcript | 14 | 6 | 42.9% | 3.500 | 3,866.6 | 5,118.9 | 19,560.8 | 100.0% |

Interpretation for this run:

- Under the 6000-character local prompt budget, Structured / Layered Memory
  has the best answer-only judge score and the lowest average context tokens.
- RAG and Full Transcript were both truncated in all 14 queries, so this is a
  bounded-prompt comparison, not an unlimited full-transcript comparison.
- Structured is strongest on cross-meeting topic evolution and decision-update
  questions where L2/L3 context is selected correctly, such as VM-E03, VM-E07,
  VM-E09, and VM-E14.
- Structured still fails important evolution questions VM-E08, VM-E10, and
  VM-E12. The failure mode is usually missing a specific cross-meeting bridge,
  not hallucination.

## Recommended Next Step

Use the existing judge rubric and scripts as the scoring basis, but run a fresh
scoring pass against the latest Observatory comparison output:

1. Generate answers with:
   `memory_observatory/run_experiment.py --generate-answers`.
2. Convert the run's `results.json` into the same row shape expected by the v2
   scoring schema:
   `uv run python memory_observatory/export_scoring_csv.py --run memory_observatory/runs/<run_id> --out memory_observatory/runs/<run_id>/observatory_scoring_input.csv`.
3. Run the v2 judge on answer rows:
   `uv run python app/score_evaluation_answers_v2.py --input memory_observatory/runs/<run_id>/observatory_scoring_input.csv --output memory_observatory/runs/<run_id>/observatory_scores_v2.csv --types answer`.
4. Compare answer quality, evidence quality, token cost, and latency for:
   Full Context, RAG, and Layered Memory.

The retrieval-only run `observatory_20260511_132827` exports successfully, but
its summary reports 8 missing answers and 8 missing expected answers. The older
answer run `observatory_20260510_213847` has answers for all three strategies
but also lacks expected answers in its query file, so it should not be used as a
valid judge run until gold expected answers are attached.
