# Planner Default Validation - 2026-05-10

This note records the manual validation for making the Memory Observatory
experiment planner default to no-LLM heuristic planning.

## Compared Runs

| Run | Planner | Answer model | Query count |
| --- | --- | --- | --- |
| `observatory_20260509_233112` | no-LLM heuristic planner | `gemini-2.5-pro` | 3 |
| `observatory_20260509_232339` | Flash LLM planner | `gemini-2.5-pro` | 3 |

Both runs used:

```text
queries: memory_observatory/runs/live_answer_subset_030607.jsonl
strategies: full_context, rag_baseline, layered_memory
retrieval_mode: lexical
max_context_chars: 12000
```

## Summary

| Layered memory metric | no-LLM planner | Flash planner |
| --- | ---: | ---: |
| avg retrieval ms | 161.205 | 34880.216 |
| avg total ms | 16439.594 | 51875.344 |
| avg context tokens | 2782.0 | 2072.333 |
| avg total tokens | 4524.667 | 3884.333 |
| expected L1 recall | 1.0 | 0.1619 |
| expected L2 hit rate | 0.6667 | 0.3333 |
| expected L3 hit rate | 1.0 | 1.0 |
| prompt budget pass rate | 1.0 | 1.0 |
| truncation rate | 0.0 | 0.0 |

The no-LLM planner retrieves more context, but the added context is still below
the prompt budget and the retrieval latency is dramatically lower.

## Manual Checks

### Transcript Segmentation / Idea Units

No-LLM retrieved the expected evidence set around `L1-0408-017`,
`L1-0429-125`, `L1-0429-126`, `L1-0429-136`, `L1-0506-003`, and
`L1-0506-009`. It selected the materialized child topic
`L2-idea-unit-generation` under
`L3-transcript-segmentation-and-idea-unit-coverage`.

The strict L2 metric is false because the expected ID names the promoted source
L2 while retrieval correctly uses a child L2. This is not a quality regression.

### Manager-Agent Evolution

No-LLM retrieved the early origin objects `L1-0318-002` and `L1-0318-006`,
plus later agent pipeline objects. The answer correctly explains the 2024 paper
pattern: worker agents, a manager agent, and a shared blackboard.

Flash planner missed the 0318 origin objects and focused on later 0429
monolithic-system / agent-architecture discussion. That answer is coherent but
less complete for the evolution question.

### RAG And Topic Lifecycle

No-LLM retrieved the expected lifecycle objects `L1-0325-045`,
`L1-0325-086`, `L1-0325-090`, `L1-0325-093`, and `L1-0422-043`, and selected
`L2-memory-lifecycle`. The answer covers time order, final state, dead topics,
and importance fade-out.

Flash planner retrieved only one of the expected lifecycle objects and selected
`L2-memory-retrieval`, which is adjacent but less precise than
`L2-memory-lifecycle`.

## Decision

Use no-LLM heuristic planning as the default for Memory Observatory experiments
and long-term retrieval eval. LLM planning remains available as an explicit
opt-in via `--use-llm-planner`.
