# App Memory Comparison Run

- Run id: `app_memory_comparison_20260511_052104`
- Strategy: app-level short-term + long-term memory context

## Summary

- `query_count`: `8`
- `avg_context_tokens`: `1579.375`
- `avg_input_tokens`: `1891.0`
- `avg_output_tokens`: `438.0`
- `avg_total_tokens`: `4219.125`
- `avg_retrieval_ms`: `49152.574`
- `avg_generation_ms`: `20095.861`
- `avg_total_ms`: `69248.435`
- `short_term_included_count`: `3`
- `long_term_included_count`: `8`
- `truncation_rate`: `1.0`

## Per Query

### q001 long-term memory retrieval 現在是怎麼運作的？
- short_term: `True`, long_term: `True`, truncated: `True`
- total tokens: `3782`, context tokens: `1312`, total_ms: `180211.374`

### q002 STM 和 LTM 的整合目前是怎麼設計的？
- short_term: `True`, long_term: `True`, truncated: `True`
- total tokens: `3950`, context tokens: `1325`, total_ms: `22076.169`

### q003 我們之前為什麼要把 transcript 拆成 segment / idea units？
- short_term: `False`, long_term: `True`, truncated: `True`
- total tokens: `4797`, context tokens: `1728`, total_ms: `58520.167`

### q004 memory evaluation strategy 之前討論過哪些方向？
- short_term: `False`, long_term: `True`, truncated: `True`
- total tokens: `4913`, context tokens: `1667`, total_ms: `54664.915`

### q005 L1 到 L2 的分群現在是怎麼決定的？
- short_term: `True`, long_term: `True`, truncated: `True`
- total tokens: `4054`, context tokens: `1373`, total_ms: `51111.073`

### q006 manager-agent 架構是怎麼演變出來的？
- short_term: `False`, long_term: `True`, truncated: `True`
- total tokens: `4697`, context tokens: `1714`, total_ms: `70961.052`

### q007 為什麼一般 RAG 不足以追蹤 topic lifecycle？
- short_term: `False`, long_term: `True`, truncated: `True`
- total tokens: `4052`, context tokens: `1773`, total_ms: `62949.636`

### q008 transcript segmentation 這個大主題被拆成哪些 child L2？
- short_term: `False`, long_term: `True`, truncated: `True`
- total tokens: `3508`, context tokens: `1743`, total_ms: `53493.097`
