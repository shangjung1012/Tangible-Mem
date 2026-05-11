# Synthetic CampusEnergyMeet-50 Analysis

## Package Validation
- schema issues: 0
- meetings / L1 objects: 50 / 3197
- Grace avg objects/meeting: 64.0
- synthetic avg/min/max/std objects per meeting: 63.94 / 61 / 67 / 2.024
- within +/-10% of Grace avg: 50/50; within +/-15%: 50/50
- unique content/evidence ratio: 0.9972 / 0.9953
- primary topic labels / related topic labels: 66 / 304

## L2/L3 Build
- default curated build was too narrow for this domain: 5 L2, 1534 linked L1, 1663 unlinked L1.
- freeform related-topic build: 66 L2, 3197/3197 linked L1, 0 unlinked.
- L2 validation: 0 severe, 12 warnings.
- package family L3 materialization: 10 L3, coverage {'unassigned_l1_count': 0, 'duplicate_assignment_count': 0, 'invalid_l3_index_count': 0}
- L3 validation: 0 severe, 118 warnings.
- Child size distribution: {'needs_split_review': 52, 'acceptable_but_watch': 12, 'ideal': 2}

## No-Limit Answer Run Scores
- Structured: avg 4.645, Yes 10/12, failures 0
- RAG: avg 4.592, Yes 11/12, failures 1
- Full Transcript: avg 3.522, Yes 6/12, failures 0

## No-Limit Token/Latency Summary
- avg_total_ms: {'full_context': 50020.362, 'rag_baseline': 40530.255, 'layered_memory': 29379.402}
- avg_context_tokens: {'full_context': 766636.0, 'rag_baseline': 161790.167, 'layered_memory': 14326.583}
- avg_input_tokens: {'full_context': 684501.917, 'rag_baseline': 135268.833, 'layered_memory': 15468.5}
- avg_output_tokens: {'full_context': 622.75, 'rag_baseline': 896.917, 'layered_memory': 810.917}
- avg_total_tokens: {'full_context': 687463.833, 'rag_baseline': 138900.917, 'layered_memory': 18428.333}
- truncation_rate: {'full_context': 0.0, 'rag_baseline': 0.0, 'layered_memory': 0.0}
- expected_obj_recall: {'full_context': 0.0, 'rag_baseline': 0.0, 'layered_memory': 0.8299}
- expected_l2_hit_rate: {'full_context': 0.0, 'rag_baseline': 0.0, 'layered_memory': 1.0}
- expected_l3_hit_rate: {'full_context': 0.0, 'rag_baseline': 0.0, 'layered_memory': 0.0}

## 61-Query Retrieval-Only With Family L3
- avg_total_ms: {'full_context': 131.423, 'rag_baseline': 78.288, 'layered_memory': 673.343}
- avg_context_tokens: {'full_context': 766636.0, 'rag_baseline': 170541.0, 'layered_memory': 18141.885}
- expected_obj_recall: {'full_context': 0.0, 'rag_baseline': 0.0, 'layered_memory': 0.6443}
- expected_l2_hit_rate: {'full_context': 0.0, 'rag_baseline': 0.0, 'layered_memory': 1.0}
- expected_l3_hit_rate: {'full_context': 0.0, 'rag_baseline': 0.0, 'layered_memory': 1.0}
- truncation_rate: {'full_context': 0.0, 'rag_baseline': 0.0, 'layered_memory': 0.0}

## Interpretation
- The package is structurally valid and diverse. Counts match Grace density very closely.
- For non-Grace domains, the safe setting is `--allow-freeform-related-topics`; leaving it off preserves Grace behavior but under-links synthetic CampusEnergy.
- Full Context is not truncated, but very large context can still make Gemini miss obvious meeting-specific facts.
- RAG is strong for single-meeting fact questions when no quota failure occurs, but uses about 9x the Layered context tokens in the family-L3 retrieval run.
- Layered memory uses much fewer tokens and hits all expected L2/L3 topics after family materialization; its weaker area is multi-meeting questions with many expected L1 anchors, where L1 recall is partial even when the L2/L3 topic is correct.
- The family-L3 answer run is not a valid quality comparison because API quota failures dominate the answers.
