# ICSI Shadow Answer Quality Manual Review: Top 3 Queries

Scope: manual spot-check of `optimization/reports/icsi_shadow_answer_quality_20260610` after regenerated scoring with corrected hallucination-risk semantics.

## q001: Data Quality

Question: `What did the ICSI BMR meetings discuss about data quality?`

Optimization v2 judgment: acceptable and better aligned to ICSI effective L1.

Evidence observed in the answer:

- microphone and audio quality issues: `L1-Bmr011_first360-004`, `L1-Bmr011_first360-024`, `L1-Bmr011_first360-020`
- transcript/content quality issues: `L1-Bmr010_first360-042`, `L1-Bmr022_first360-002`, `L1-Bmr022_first360-005`, `L1-Bmr015_first360-010`
- data collection strategy: `L1-Bmr006_first360-008`, `L1-Bmr006_first360-011`, `L1-Bmr006_first360-017`

Canonical diagnostic issue:

- canonical answered from Grace project context about why ICSI/BMR was chosen as a dataset (`L1-0325-*`, `L1-0408-*`), not from the BMR effective L1 content itself.
- This is a concrete example of why canonical long-term L2/L3 is not a valid gold baseline for ICSI.

Remaining v2 issue:

- the judge scored topic evolution lower because q001 is an overview query and v2 did not explicitly frame change over time. This is acceptable for overview behavior, but the diagnostic gate correctly keeps it visible.

## q002: Data Collection Evolution

Question: `ICSI BMR meetings discussed data collection. How did that topic evolve across meetings?`

Optimization v2 judgment: pass.

Evidence observed in the answer:

- moved away from one-off meetings toward recurring meetings: `L1-Bmr006_first360-008`, `L1-Bmr006_first360-011`, `L1-Bmr006_first360-017`
- hardware/procedure refinements: `L1-Bmr014_first360-016`, `L1-Bmr014_first360-004`
- environment and participant protocol constraints: `L1-Bmr003_first360-045`, `L1-Bmr002_first360-006`
- annotation/protocol updates and open issues: `L1-Bmr021_first360-021`, `L1-Bmr023_first360-007`, `L1-Bmr015_first360-020`, `L1-Bmr008_first360-027`
- resource blocker: `L1-Bmr026_first360-039`

Reasoning:

- This answer uses L1 evidence as factual support and L2/L3 only as cross-meeting organization.
- It gives a real evolution arc rather than a flat list.

## q003: Corpus Design Evidence

Question: `What concrete evidence do the ICSI BMR meetings contain about corpus design?`

Optimization v2 judgment: pass.

Evidence observed in the answer:

- recurring goal-oriented meeting strategy: `L1-Bmr006_first360-008`, `L1-Bmr006_first360-017`, `L1-Bmr006_first360-023`
- speaker diversity/acoustic contrast: `L1-Bmr006_first360-020`
- expanded target hours: `L1-Bmr003_first360-040`
- stop new recordings and process external sources: `L1-Bmr031_first360-037`
- digits corpus design: `L1-Bmr013_first360-033`, `L1-Bmr013_first360-030`, `L1-Bmr013_first360-009`, `L1-Bmr013_first360-010`
- metadata and data management: `L1-Bmr012_first360-006`, `L1-Bmr015_first360-010`, `L1-Bmr016_first360-001`, `L1-Bmr027_first360-022`, `L1-Bmr026_first360-047`

Reasoning:

- The answer is evidence-heavy and source-traceable.
- It does not rely on Grace-specific memory-system ontology.

## Conclusion

Manual review supports the automated conclusion:

- Grace shadow answer quality passes.
- ICSI optimization v2 is better aligned to ICSI effective L1 than canonical diagnostic traces.
- Promotion is still blocked because:
  - ICSI diagnostic topic evolution has one aggregate weakness.
  - label polish review found unresolved weak labels.
  - longer-than-first360 effective ICSI input is absent.
