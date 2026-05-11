# Short-Term Answer Ablation Report

- Run id: `short_term_ablation_20260511_060257`
- Model: `gemini-2.5-pro`
- Planner model: `gemini-2.5-flash`
- Max context chars: `4000`

## Summary

| variant | avg gold recall | avg context tokens | truncation rate | completed answers |
|---|---:|---:|---:|---:|
| `short_only` | 0.3408 | 845.8 | 0.875 | 8 |
| `long_only` | 0.2375 | 1607.6 | 1.0 | 8 |
| `short_plus_long` | 0.3021 | 1231.4 | 1.0 | 8 |

## Per Query Gold Recall

| qid | expected route | short only | long only | short+long |
|---|---|---:|---:|---:|
| VM-E01 | short_term | 0.75 | 0.5 | 0.75 |
| VM-E02 | short_term | 1.0 | 0.4 | 1.0 |
| VM-E05 | short_term | 0.6667 | 0.3333 | 0.6667 |
| VM-E08 | both | 0.1667 | 0.1667 | 0.0 |
| VM-E10 | both | 0.0 | 0.0 | 0.0 |
| VM-E12 | both | 0.0 | 0.0 | 0.0 |
| VM-E13 | short_term | 0.0 | 0.5 | 0.0 |
| VM-E14 | both | 0.1429 | 0.0 | 0.0 |
