# Memory Observatory

Memory Observatory is a demo and inspection surface for the current memory
artifacts. It is intentionally separate from the chat app and does not rewrite
raw L1 evidence.

It shows three things:

- how transcripts become immutable L1 evidence objects;
- how L1 objects connect to L2 / child-L2 / L3 topic context;
- how layered memory retrieval compares with traditional RAG and full context.

## Start The UI

```bash
uv run uvicorn memory_observatory.main:app --reload
```

Open:

```text
http://localhost:8000/
```

The app serves static HTML/CSS/JS and FastAPI JSON endpoints. It does not use
React, D3, or React Flow.

## Data Contract

Read-only sources:

- `share_mem/tree.json`
- `share_mem/meetings/<meeting_id>.json`
- `long_term/l2/l2_view.json`
- `long_term/l2/l2_index.json`
- `long_term/l3/l3_view.json`
- `long_term/l3/l3_index.json`
- `long_term/l3/validation/l3_validation_report.json`
- `long_term/eval/long_term_retrieval_queries.jsonl`
- `long_term/eval/retrieval_eval_report.json`

Writable sidecars:

- `share_mem/user_feedback/importance_adjustments.jsonl`
- `share_mem/user_feedback/importance_override_index.json`
- `share_mem/user_feedback/importance_feedback_summary.json`
- `memory_observatory/runs/<run_id>/...`

Do not edit `share_mem/tree.json` to apply review feedback. The feedback editor
writes sidecar files only.

## Run A No-LLM Comparison Experiment

```bash
uv run python memory_observatory/run_experiment.py \
  --queries long_term/eval/long_term_retrieval_queries.jsonl \
  --out memory_observatory/runs \
  --strategies full_context,rag_baseline,layered_memory \
  --retrieval-mode lexical \
  --no-llm
```

No-LLM mode does not call the Gemini planner, embedding API, or final answer
LLM. It uses lexical RAG, heuristic layered recall planning, deterministic token
estimates, and retrieval/context-build timing.

Each run writes:

- `run_config.json`
- `queries.jsonl`
- `summary.json`
- `results.json`
- `visualization_data.json`
- `results_by_query/<query_id>.json`
- `contexts/<query_id>/<strategy>.txt`
- `retrieved/<query_id>/<strategy>.json`
- `answers/<query_id>/<strategy>.txt`

Generated run directories are ignored by git; `.gitkeep` preserves the folder.

## Pages

- Overview: memory pipeline and artifact statistics.
- Retrieval Trace: query -> L1 evidence -> L2 / child-L2 -> L3 -> prompt context.
- Memory Explorer: meeting, L1 object, evidence, topic link, and feedback browsing.
- Topic Observatory: L3 -> child L2 hierarchy plus topic detail.
- Importance Review: sidecar-only importance feedback.
- Experiment Lab: compare full context, traditional RAG, and layered memory.
