# Optimization V2 Shadow Answer Quality

- decision: `answer_quality_pass`
- query count: `8`
- row count: `16`
- reason codes: none
- raw run root: `C:\Users\yiihsinn\Documents\project_git\virtual-mentor\optimization\runs\grace_shadow_answer_quality_grace_v2_latest_20260614`

## Backend Summary

| Backend | Overall | Traceability | Hallucination Risk | Context Tokens |
|---|---:|---:|---:|---:|
| canonical | 0.9643 | 1.0 | 0.0 | 8602.625 |
| optimization_v2 | 0.9384 | 1.0 | 0.0 | 8467.5 |

## Delta

- optimization overall minus canonical: `-0.0259`
- dimension delta: `{'factual_correctness': 0.0, 'evidence_grounding': 0.0, 'topic_evolution': -0.125, 'completeness': -0.0563, 'conciseness': 0.0, 'hallucination_risk': 0.0, 'source_traceability': 0.0}`

## Boundary

- This report compares shadow traces only.
- It does not modify `.env`, canonical `share_mem/`, or canonical `long_term/` artifacts.
