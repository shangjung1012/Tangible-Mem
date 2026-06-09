# Optimization V2 Shadow Answer Quality

- decision: `answer_quality_needs_review`
- query count: `12`
- row count: `24`
- reason codes: optimization_evolution_below_diagnostic_canonical
- raw run root: `C:\Users\yiihsinn\Documents\project_git\virtual-mentor\optimization\runs\icsi_shadow_answer_quality_20260610`

## Backend Summary

| Backend | Overall | Traceability | Hallucination Risk | Context Tokens |
|---|---:|---:|---:|---:|
| canonical | 0.9107 | 0.9167 | 0.0 | 8301.4167 |
| optimization_v2 | 0.9631 | 1.0 | 0.0 | 3410.1667 |

## Delta

- optimization overall minus canonical: `0.0524`
- dimension delta: `{'factual_correctness': 0.0833, 'evidence_grounding': 0.0833, 'topic_evolution': -0.0833, 'completeness': 0.1167, 'conciseness': 0.0833, 'hallucination_risk': 0.0, 'source_traceability': 0.0833}`

## Boundary

- This report compares shadow traces only.
- It does not modify `.env`, canonical `share_mem/`, or canonical `long_term/` artifacts.
