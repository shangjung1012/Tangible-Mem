# share_mem L1 Pipeline

This package is the canonical home for multi-agent L1 extraction code.

- `bridge.py`: writes one transcript into a share_mem tree plus sidecars.
- `multi_agent_pipeline.py`: orchestrates segmentation, boundary refinement,
  idea units, bounded extraction packets, typed extraction, grounding,
  verification, and reduction.
- `multi_agent_*.py`: staged prompt agents, validators, state, tools, reducer, verifier, and research logging.
- `l1_quality.py`, `memory_relations.py`, `memory_activity.py`: generated sidecar helpers for L1 quality, relations, and activity.

Use "extraction packet" for collaborator-facing explanations. It means the
bounded group of idea units passed to typed L1 agents before they emit
candidates. The older `batch_id` / `extraction_batches` names remain as
compatibility keys in code and legacy logs.

`long_term/` keeps compatibility aliases for older imports and remains the home
for temporal L2/L3, recall, and legacy baseline entrypoints.
