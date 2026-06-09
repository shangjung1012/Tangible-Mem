# ICSI BMR First360 Answer Quality Comparison

- status: `warning`
- gate reasons: missing_canonical_layered
- ICSI available-baseline decision: `optimization_v2_wins_available_baselines`
- raw run root: `C:\Users\yiihsinn\Documents\project_git\virtual-mentor\optimization\runs\icsi_bmr_first360_answer_quality_candidate6_stable_20260609`
- v2 overall delta vs full context: `0.2297`
- v2 overall delta vs RAG: `0.1559`
- v2 token delta vs full context: `-97137.9167`
- v2 token delta vs RAG: `-1201.0834`

## Strategy Summary

| Strategy | Overall | Factual | Grounding | Evolution | Completeness | Conciseness | Hallucination Risk | Traceability | Context Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full_context | 0.5417 | 0.2 | 0.6167 | 0.5583 | 0.2833 | 0.3917 | 0.175 | 0.9167 | 100119.0 |
| optimization_v2_deterministic | 0.7714 | 0.45 | 1.0 | 0.7292 | 0.3792 | 0.8417 | 0.0 | 1.0 | 2981.0833 |
| rag_baseline | 0.6155 | 0.0792 | 0.9167 | 0.6417 | 0.0708 | 0.6833 | 0.0 | 0.9167 | 4182.1667 |

## Interpretation Boundary

- `full_context_first360` uses all available first360 transcript lines from the effective corpus and is not token-capped.
- `rag_baseline_first360` uses normal lexical top-k chunks and is not token-capped.
- `optimization_v2_candidate6` uses the isolated candidate6 effective L2/L3 view.
- This report is ICSI BMR first360-specific and does not promote optimization v2 into canonical runtime.
