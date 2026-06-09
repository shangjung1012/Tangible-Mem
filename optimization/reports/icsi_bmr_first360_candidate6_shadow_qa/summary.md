# Optimization V2 Shadow-Mode QA

- decision: `shadow_qa_pass`
- query count: `12`
- shadow trace ready: `12`
- needs review: `0`
- optimization run root: `C:\Users\yiihsinn\Documents\project_git\virtual-mentor\optimization\runs\icsi_bmr001_031_first360_candidate6_llm_split_review_20260609`
- raw run root: `C:\Users\yiihsinn\Documents\project_git\virtual-mentor\optimization\runs\icsi_bmr_first360_candidate6_shadow_qa_20260610`
- retrieval mode: `lexical`
- max context chars: `16000`
- answer quality status: `not_run`

## Average Context Tokens

| Backend | Tokens | Latency ms |
|---|---:|---:|
| canonical | 8301.4167 | 273.7938 |
| optimization_v2 | 3410.1667 | 330.2585 |

## Reason Codes

- none

## Review Items

- none

## Boundary

- This is shadow-mode QA only.
- It does not modify `.env`, canonical `share_mem/`, or canonical `long_term/` artifacts.
- `shadow_qa_pass` means the optimization backend can enter controlled shadow comparison; it is not canonical promotion.
