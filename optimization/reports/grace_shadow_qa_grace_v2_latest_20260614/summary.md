# Optimization V2 Shadow-Mode QA

- decision: `shadow_qa_pass`
- query count: `8`
- shadow trace ready: `8`
- needs review: `0`
- optimization run root: `C:\Users\yiihsinn\Documents\project_git\virtual-mentor\optimization\runs\grace_v2_latest_20260614`
- raw run root: `C:\Users\yiihsinn\Documents\project_git\virtual-mentor\optimization\runs\grace_shadow_qa_grace_v2_latest_20260614`
- retrieval mode: `lexical`
- max context chars: `16000`
- answer quality status: `not_run`

## Average Context Tokens

| Backend | Tokens | Latency ms |
|---|---:|---:|
| canonical | 8608.125 | 258.1971 |
| optimization_v2 | 8453.125 | 255.9265 |

## Reason Codes

- none

## Review Items

- none

## Boundary

- This is shadow-mode QA only.
- It does not modify `.env`, canonical `share_mem/`, or canonical `long_term/` artifacts.
- `shadow_qa_pass` means the optimization backend can enter controlled shadow comparison; it is not canonical promotion.
