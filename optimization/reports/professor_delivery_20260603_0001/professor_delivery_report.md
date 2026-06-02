# Optimization v2 Delivery Report

Generated: `2026-06-02T22:37:20Z`

## Executive Status

- Deliverability: `deliverable_shadow_mode`
- Promotion boundary: `do_not_promote_to_canonical`
- Certification status: `warning`
- Failing gates: `0`
- Warning gates: `gate_12_promotion_decision`

## Core Evidence

- Isolation gate: `pass`
- Grace-specific hardcode scan: `pass`, matches `0`
- Baseline high-importance linked rate: `0.9577`
- v2 high-importance linked rate: `1.0`
- L2 severe / warning count: `0` / `2`
- Retrieval L1 recall: `0.8728`
- Retrieval L2 semantic hit: `1.0`
- L3 parents / child L2: `3` / `6`

## Answer Quality

- Status: `pass`
- Best strategy: `optimization_v2_deterministic`
- Overall scores: `{'canonical_layered': 0.85, 'full_context': 0.2857, 'optimization_v2_deterministic': 0.8905, 'optimization_v2_llm_assisted': 0.8571, 'rag_baseline': 0.4286}`
- Average context tokens: `{'canonical_layered': 10262.7, 'full_context': 98531.0, 'optimization_v2_deterministic': 3685.3, 'optimization_v2_llm_assisted': 3696.0, 'rag_baseline': 20197.3}`
- Failure cases retained for review: `4`

## Cross-Dataset And Review Evidence

- Cross-dataset suite: `pass`, datasets `3`, failed `0`
- ICSI severe / warning count: `0` / `0`
- Manual review: `pass`, decisions `43`, severe `0`, wrong-assignment rate `0.0465`
- Focused split review: `pass`, reviewed `14`, accepted splits `2`
- Split candidate application: `pass`, applied `1`, skipped `2`

## V2-Native Query Diagnostics

- `synthetic_candidate_needs_split`: queries `12`, L1 recall `0.625`, L2 semantic hit `1.0`
- `icsi_5file_largest_topics`: queries `8`, L1 recall `1.0`, L2 semantic hit `1.0`

## Five Talking Points

1. Optimization v2 is isolated: it reads raw L1 evidence but writes only optimization-side artifacts.
2. The L2/L3 pipeline is evidence-driven and profile-driven, without the old Grace-specific canonical label map.
3. Related topics are treated as an optional stabilizing signal, not the only assignment source.
4. Current certification has no failing gate; the remaining boundary is policy-level shadow-mode only.
5. Answer-quality evidence favors optimization_v2_deterministic over canonical layered, RAG, and full context on the scored sample.

## Suggested Demo Flow

1. Open with the problem: canonical L2/L3 worked for Grace but looked too project-specific.
2. Show the v2 design: L1 evidence -> semantic keys -> induced L2 -> adaptive L3 -> validation gates.
3. Show the certification summary: no failing gates, no hardcode scan hits, ICSI and synthetic checks pass.
4. Show answer-quality comparison: v2 deterministic has stronger score with much smaller context than full context.
5. Close honestly: v2 is ready for shadow-mode evaluation, not canonical promotion.

## Remaining Risks

- Not promoted: repeated isolated runs and explicit user approval are still required.
- Some split candidates were intentionally skipped because validation found weak separability.
- Answer-quality report still keeps failure cases for manual review rather than hiding them.
