# v2 Native Query Diagnostics

| dataset | queries | avg L1 recall | L2 hit | semantic L2 hit | needs split | pressure topics |
|---|---:|---:|---:|---:|---:|---:|
| synthetic_candidate_needs_split | 12 | 0.625 | 1.0 | 1.0 | 13 | 12 |
| icsi_5file_largest_topics | 8 | 1.0 | 1.0 | 1.0 |  |  |

## Interpretation

- Synthetic v2-native needs-split queries keep semantic L2 hit at 1.0 and improve L1 recall compared with the earlier broad pressure queries.
- ICSI pilot v2-native largest-topic queries achieve 1.0 L1 recall and 1.0 L2 hit, showing the query curation path is not Grace-specific.
- Retrieval-pressure prioritization now points to real query-hit pressure rather than raw L2 size alone.
