# ICSI No-LLM System Comparison

This is a retrieval/evidence comparison only. It does not call Gemini/Vertex and does not score final generated answers.

## Summary

| Strategy | Expected L1 recall | Avg context tokens | Avg selected L1 |
|---|---:|---:|---:|
| full_context_l1 | 1.0 | 575199.0 | 4715.0 |
| rag_l1_lexical | 0.5583 | 2369.95 | 20.0 |
| optimization_v2_layered | 0.8958 | 7358.35 | 60.0 |

## Interpretation

- `full_context_l1` is the upper-bound evidence condition: it includes every source-side L1 object.
- `rag_l1_lexical` is a normal lexical top-k baseline over source-side L1 content/evidence.
- `optimization_v2_layered` uses the same evidence-first L1 ranking plus the effective L2/L3 topic surface.
- Use this report to validate retrieval coverage and context-size tradeoffs before any paid answer-quality run.

## Per Query

| Query | Full recall | RAG recall | V2 recall | Full tokens | RAG tokens | V2 tokens |
|---|---:|---:|---:|---:|---:|---:|
| icsi-heldout-q001 | 1.0 | 0.5 | 0.75 | 575199 | 2407 | 7450 |
| icsi-heldout-q002 | 1.0 | 0.5 | 1.0 | 575199 | 2313 | 7280 |
| icsi-heldout-q003 | 1.0 | 0.25 | 0.5 | 575199 | 2738 | 7960 |
| icsi-heldout-q004 | 1.0 | 0.5 | 1.0 | 575199 | 2330 | 7208 |
| icsi-heldout-q005 | 1.0 | 0.6667 | 1.0 | 575199 | 2454 | 7577 |
| icsi-heldout-q006 | 1.0 | 0.0 | 0.6667 | 575199 | 2516 | 7565 |
| icsi-heldout-q007 | 1.0 | 0.5 | 1.0 | 575199 | 2179 | 7517 |
| icsi-heldout-q008 | 1.0 | 0.75 | 1.0 | 575199 | 2087 | 6751 |
| icsi-heldout-q009 | 1.0 | 0.75 | 0.75 | 575199 | 2318 | 6930 |
| icsi-heldout-q010 | 1.0 | 0.5 | 0.5 | 575199 | 1996 | 7213 |
| icsi-heldout-q011 | 1.0 | 0.75 | 1.0 | 575199 | 2314 | 7806 |
| icsi-heldout-q012 | 1.0 | 0.75 | 0.75 | 575199 | 2248 | 7221 |
| icsi-heldout-q013 | 1.0 | 0.5 | 1.0 | 575199 | 2415 | 7972 |
| icsi-heldout-q014 | 1.0 | 0.5 | 1.0 | 575199 | 2353 | 6951 |
| icsi-heldout-q015 | 1.0 | 0.0 | 1.0 | 575199 | 2418 | 7579 |
| icsi-heldout-q016 | 1.0 | 1.0 | 1.0 | 575199 | 2601 | 7287 |
| icsi-heldout-q017 | 1.0 | 1.0 | 1.0 | 575199 | 2519 | 7869 |
| icsi-heldout-q018 | 1.0 | 1.0 | 1.0 | 575199 | 2544 | 6809 |
| icsi-heldout-q019 | 1.0 | 0.75 | 1.0 | 575199 | 2049 | 6522 |
| icsi-heldout-q020 | 1.0 | 0.0 | 1.0 | 575199 | 2600 | 7700 |