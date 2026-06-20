# TAICHI Paper Workspace

This folder collects paper-facing material for the TAICHI submission. The paper
framing should treat Virtual Mentor as an HCI system for inspectable and
correctable AI memory, not as a pure retrieval-algorithm paper.

## Core Framing

Recommended one-sentence contribution:

> We present Memory Observatory, an interface for inspecting, tracing, and
> correcting layered AI memory without overwriting raw evidence.

Safe claims:

- Users can inspect how meeting transcripts become L1 evidence objects.
- Users can inspect how L1 evidence connects to L2 topic context and L3 topic
  families.
- Users can inspect retrieval traces rather than only final answers.
- Users can correct importance and feedback through sidecars without mutating
  raw evidence.
- Optimization v2 supports evidence-backed topic organization for new datasets
  such as ICSI.

Non-claims:

- Do not claim solved long-term memory.
- Do not claim SOTA retrieval.
- Do not claim final user-study evidence yet.
- Do not claim optimization v2 is a canonical artifact replacement.
- Do not claim generated L2/L3 topics are perfect.

## Files

- `section_3_4_5_outline.md`: writing plan for the sections owned by this work.
- `demo_walkthrough.md`: polished walkthrough for the live demo and Section 5.
- `artifact_index.md`: source of truth for figures, screenshots, and reports.
- `readiness_checklist.md`: remaining work before submission/demo.

## Paper Section Ownership

The current target sections are:

- Section 3: Design Goals and System Overview.
- Section 4: Implementation.
- Section 5: Use Case Walkthrough.

The section text should focus on user-facing inspection, steering, and
governance. Detailed scoring formulas and thresholds can be summarized in the
main text and moved to appendix or supplemental material.
