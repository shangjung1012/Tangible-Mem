# Final Memory Observatory Experiment

This folder freezes the final scored comparison run for the current layered-memory version.

Source run copied from:

```text
memory_observatory/runs/observatory_20260512_000837
```

## Experiment Setup

- Query set: `doc/evaluation_questions_0307_0506.csv`
- Query count: 14
- Compared strategies:
  - `full_context`
  - `rag_baseline`
  - `layered_memory`
- Retrieval mode: `hybrid`
- Planner: heuristic / no LLM planner
- Answer model: `gemini-2.5-pro`
- Judge model: `gemini-2.5-pro`
- Full context scope: `all`
- Full context truncation: disabled
- Full context token cap: disabled
- RAG top-k: 12
- RAG token cap: disabled
- Layered memory budget profile: `generous_layered`

Original experiment command:

```powershell
uv run python memory_observatory/run_experiment.py `
  --queries doc/evaluation_questions_0307_0506.csv `
  --out memory_observatory/runs `
  --strategies full_context,rag_baseline,layered_memory `
  --retrieval-mode hybrid `
  --no-llm `
  --generate-answers `
  --model gemini-2.5-pro `
  --budget-profile generous_layered `
  --full-context-scope all `
  --max-context-chars 0 `
  --rag-top-k 12 `
  --full-context-max-tokens 0 `
  --rag-max-context-tokens 0 `
  --baseline-token-multiplier 0
```

Scoring command:

```powershell
uv run python memory_observatory/export_scoring_csv.py `
  --run memory_observatory/runs/observatory_20260512_000837 `
  --out memory_observatory/runs/observatory_20260512_000837/observatory_scoring_input.csv

uv run python app/score_evaluation_answers_v2.py `
  --input memory_observatory/runs/observatory_20260512_000837/observatory_scoring_input.csv `
  --output memory_observatory/runs/observatory_20260512_000837/observatory_scores_v2.csv `
  --types answer `
  --model gemini-2.5-pro
```

The first answer-generation pass hit `429 RESOURCE_EXHAUSTED` on 27 answer calls. Those failed answers were regenerated from the already-built contexts, then the scorer was rerun. The final `observatory_scores_v2.csv` has 42 scored rows and no answer-generation failure rows.

## Average Scores

| Method | Final | Factuality | Completeness | Evidence | Type-specific |
|---|---:|---:|---:|---:|---:|
| Full Context | 4.894 | 4.929 | 4.714 | 5.000 | 4.857 |
| RAG Baseline | 4.507 | 4.357 | 4.000 | 4.929 | 4.357 |
| Layered Memory | 4.789 | 4.857 | 4.429 | 5.000 | 4.714 |

## Average Token and Time

| Method | Avg input tokens | Avg total tokens | Avg total ms | Truncation rate |
|---|---:|---:|---:|---:|
| Full Context | 77,562 | 81,069 | 46,656 | 0.000 |
| RAG Baseline | 18,108 | 21,284 | 33,002 | 0.000 |
| Layered Memory | 10,937 | 14,115 | 34,774 | 0.000 |

## Score Deltas

- Layered Memory minus Full Context: `-0.105`
- Layered Memory minus RAG Baseline: `+0.282`
- Full Context minus RAG Baseline: `+0.387`

## Interpretation

Full Context is the highest-scoring upper bound when given all transcript context with no token cap. Layered Memory is slightly below Full Context, but uses far fewer tokens and beats the RAG baseline. The main remaining weakness is cross-meeting starting-point coverage: for example, evaluation-strategy questions that need both the 0318 paper-review starting point and the later 0429 convergence can still miss the earliest context.

## Artifact Guide

- `results.json`: full structured experiment results, including strategy metrics and answers.
- `summary.json`: aggregate token, timing, retrieval, and truncation metrics.
- `observatory_scoring_input.csv`: flattened answer rows sent to the scorer.
- `observatory_scores_v2.csv`: Gemini judge scores for all 14 questions x 3 methods.
- `observatory_score_summary.md`: compact score summary.
- `observatory_score_summary.json`: machine-readable score summary.
- `contexts/`: exact prompt context used for each strategy and question.
- `retrieved/`: retrieved evidence/chunks/layered traces for each strategy and question.
- `answers/`: generated answers for each strategy and question.
- `results_by_query/`: per-question structured results.
