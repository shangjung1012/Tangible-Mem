# Observatory Score Summary: observatory_20260512_000837

## Configuration
- queries: `doc\evaluation_questions_0307_0506.csv`
- strategies: full_context, rag_baseline, layered_memory
- retrieval_mode: `hybrid`
- planner: `heuristic`
- answer model: `gemini-2.5-pro`
- full_context_scope: `all`
- max_context_chars: `0`
- full_context_max_tokens: `0`
- rag_top_k: `12`
- rag_max_context_tokens: `0`
- budget_profile: `generous_layered`

## Average Scores
| Method | Final | Factuality | Completeness | Evidence | Type-specific |
|---|---:|---:|---:|---:|---:|
| Full Context | 4.894 | 4.929 | 4.714 | 5.000 | 4.857 |
| RAG Baseline | 4.507 | 4.357 | 4.000 | 4.929 | 4.357 |
| Layered Memory | 4.789 | 4.857 | 4.429 | 5.000 | 4.714 |

## Average Token and Time
| Method | Avg input tokens | Avg total tokens | Avg total ms | Truncation rate |
|---|---:|---:|---:|---:|
| Full Context | 77562 | 81069 | 46656 | 0.000 |
| RAG Baseline | 18108 | 21284 | 33002 | 0.000 |
| Layered Memory | 10937 | 14115 | 34774 | 0.000 |

## Score Deltas
- layered_minus_full_context: -0.105
- layered_minus_rag: +0.282
- full_context_minus_rag: +0.387

## Query Winners
- VM-E01: Layered Memory=4.47, RAG Baseline=5.00, Full Context=5.00; winner: RAG Baseline, Full Context
- VM-E02: Layered Memory=5.00, RAG Baseline=4.12, Full Context=4.82; winner: Layered Memory
- VM-E03: Layered Memory=5.00, RAG Baseline=3.23, Full Context=5.00; winner: Layered Memory, Full Context
- VM-E04: Layered Memory=5.00, RAG Baseline=5.00, Full Context=5.00; winner: Layered Memory, RAG Baseline, Full Context
- VM-E05: Layered Memory=5.00, RAG Baseline=5.00, Full Context=5.00; winner: Layered Memory, RAG Baseline, Full Context
- VM-E06: Layered Memory=5.00, RAG Baseline=5.00, Full Context=5.00; winner: Layered Memory, RAG Baseline, Full Context
- VM-E07: Layered Memory=5.00, RAG Baseline=5.00, Full Context=5.00; winner: Layered Memory, RAG Baseline, Full Context
- VM-E08: Layered Memory=3.40, RAG Baseline=3.52, Full Context=4.82; winner: Full Context
- VM-E09: Layered Memory=5.00, RAG Baseline=5.00, Full Context=5.00; winner: Layered Memory, RAG Baseline, Full Context
- VM-E10: Layered Memory=4.82, RAG Baseline=5.00, Full Context=5.00; winner: RAG Baseline, Full Context
- VM-E11: Layered Memory=5.00, RAG Baseline=4.00, Full Context=5.00; winner: Layered Memory, Full Context
- VM-E12: Layered Memory=4.35, RAG Baseline=3.23, Full Context=3.87; winner: Layered Memory
- VM-E13: Layered Memory=5.00, RAG Baseline=5.00, Full Context=5.00; winner: Layered Memory, RAG Baseline, Full Context
- VM-E14: Layered Memory=5.00, RAG Baseline=5.00, Full Context=5.00; winner: Layered Memory, RAG Baseline, Full Context
