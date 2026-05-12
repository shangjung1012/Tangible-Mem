# Final Synthetic Campus Energy Retrieval Experiment

This folder preserves the final scored synthetic comparison run for the current Memory Observatory / layered retrieval implementation.

## Source

- Source run: `long_term/eval/synthetic_campus_energy_50/runs_reasonable_answer_fixed_rag_retry/observatory_20260512_011851`
- Final archived root: `long_term/eval/synthetic_campus_energy_50/experiment_final`
- Run id: `observatory_20260512_011851`
- Created at UTC: `2026-05-12T01:39:46.901270Z`
- Synthetic dataset: `synthetic_campus_energy_50`

## Experiment Command

```powershell
uv run python memory_observatory/run_experiment.py --repo-root long_term/eval/synthetic_campus_energy_50/observatory_repo --queries long_term/eval/demo_subset_12_with_expected_answers.jsonl --out long_term/eval/synthetic_campus_energy_50/runs_reasonable_answer_fixed_rag_retry --strategies full_context,rag_baseline,layered_memory --retrieval-mode lexical --no-llm --generate-answers --model gemini-2.5-pro --full-context-scope all --rag-top-k 10 --max-context-chars 0 --baseline-token-multiplier 0
```

Scoring command:

```powershell
uv run python app/score_evaluation_answers_v2.py --input long_term/eval/synthetic_campus_energy_50/runs_reasonable_answer_fixed_rag_retry/observatory_20260512_011851/observatory_scoring_input.csv --output long_term/eval/synthetic_campus_energy_50/runs_reasonable_answer_fixed_rag_retry/observatory_20260512_011851/observatory_scores_v2.csv --types answer --model gemini-2.5-pro --force
```

## Fairness Settings

- Full Context: all synthetic transcripts, no character cap, no token cap, no truncation.
- Traditional RAG: deterministic lexical transcript chunks, `top_k=10`, no extra token cap. This is a normal bounded-RAG setting, not an artificially compressed one.
- Layered Memory: lexical/no-LLM retrieval planner, no answer-planner LLM, no context char cap, existing layered L1 -> L2/child-L2 -> L3 context path.
- All three strategies generated answers with the same Gemini answer model and were scored by the same v2 judge script.

## Aggregate Metrics

| Strategy | Avg final quality | Median | Min | Max | Avg actual total tokens | Avg context tokens | Avg total ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| Layered Memory | 4.941 | 5.000 | 4.47 | 5.00 | 13,312 | 9,215 | 30,595.5 |
| Traditional RAG | 4.853 | 5.000 | 3.23 | 5.00 | 9,858 | 7,024 | 30,120.5 |
| Full Context | 3.704 | 4.415 | 1.18 | 5.00 | 687,479 | 766,636 | 42,838.3 |

## Retrieval Metrics

| Strategy | Expected L1 recall | Expected L2 hit rate | Expected L3 hit rate | Prompt budget pass | Truncation rate |
|---|---:|---:|---:|---:|---:|
| Layered Memory | 0.8056 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| Traditional RAG | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.0000 |
| Full Context | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.0000 |

Note: expected L1/L2/L3 retrieval metrics are currently computed for layered traces. Full Context and RAG answer quality is evaluated by judge scores and direct context artifacts.

## Per-Question Scores

| Query | Layered Memory | RAG | Full Context | Winner / Tie |
|---|---:|---:|---:|---|
| ND-BENCH-001 | 5.0 | 5.0 | 1.7 | RAG, Structured |
| ND-BENCH-002 | 5.0 | 5.0 | 5.0 | Full Transcript, RAG, Structured |
| ND-BENCH-003 | 5.0 | 5.0 | 5.0 | Full Transcript, RAG, Structured |
| ND-BENCH-004 | 5.0 | 5.0 | 5.0 | Full Transcript, RAG, Structured |
| ND-BENCH-005 | 5.0 | 5.0 | 1.7 | RAG, Structured |
| ND-BENCH-006 | 5.0 | 5.0 | 5.0 | Full Transcript, RAG, Structured |
| ND-BENCH-007 | 5.0 | 5.0 | 1.18 | RAG, Structured |
| ND-BENCH-008 | 4.82 | 5.0 | 5.0 | Full Transcript, RAG |
| ND-BENCH-009 | 5.0 | 5.0 | 3.83 | RAG, Structured |
| ND-BENCH-010 | 5.0 | 5.0 | 2.52 | RAG, Structured |
| ND-BENCH-011 | 5.0 | 3.23 | 3.52 | Structured |
| ND-BENCH-012 | 4.47 | 5.0 | 5.0 | Full Transcript, RAG |

## Key Interpretation

- Layered Memory had the highest average final quality in this run: `4.941`, compared with RAG `4.853` and Full Context `3.704`.
- Layered Memory used far fewer tokens than Full Context: about `13.3k` actual total tokens on average versus Full Context `687.5k`.
- Layered Memory used more tokens than the top-10 RAG baseline because it injects L1 evidence plus L2/child-L2 evolution context and L3 navigation; the advantage is traceable cross-meeting context, not always the smallest prompt against a bounded RAG baseline.
- RAG became competitive on exact single-meeting/topic questions after the meeting-id parsing fix. Its main weakness remains cross-meeting evolution questions where the top chunks stop at early meetings.
- Full Context is not truncated here, but it is extremely token-heavy and slower; it also underperformed on several targeted questions because the huge context made the relevant evidence harder to use.

## Reliability Notes

- Answer generation errors in final run: `0`.
- Transient generation retries in final run: `2` (`ND-BENCH-004/full_context`, `ND-BENCH-006/rag_baseline`).
- The experiment runner now retries transient answer-generation failures so 429 quota errors are not scored as answer quality failures.

## Artifact Map

- `run_config.json`: exact run configuration.
- `summary.json`: aggregate run metrics emitted by Memory Observatory.
- `results.json`: complete structured run result for all queries and strategies.
- `visualization_data.json`: UI-ready copy of the structured result.
- `observatory_scoring_input.csv`: exported scoring input.
- `observatory_scores_v2.csv`: final judge scores.
- `score_summary.json`: compact parsed score summary for scripts.
- `per_question_score_table.csv`: quick table of per-query final scores.
- `answers/`: generated answers by query and strategy.
- `contexts/`: exact prompt context by query and strategy.
- `retrieved/`: retrieved chunks / layered trace artifacts.
- `results_by_query/`: full structured per-query records.
- `artifact_manifest.json`: file list, sizes, and largest artifacts.
