# ICSI Answer Quality Proxy

- method: `no_llm_retrieval_quality_proxy`
- decision: `candidate_not_worse`
- score delta: `0.0`

| Strategy | Proxy Overall | Evidence Grounding | Topic Evolution | Source Traceability |
|---|---:|---:|---:|---:|
| icsi_bmr001_031_first360_candidate5_label_split_20260609 | 0.9128 | 0.8104 | 1.0 | 1.0 |
| icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 | 0.9128 | 0.8104 | 1.0 | 1.0 |

## Limitations

- This is not final answer scoring; it estimates answer quality from retrieval recall, semantic topic hits, and source traceability.
- Full-context and RAG answer quality still require the Memory Observatory or LLM answer scorer for a final claim.
