# Memory Observatory

Memory Observatory is a demo and inspection surface for the current memory
artifacts. It is intentionally separate from the chat app and does not rewrite
raw L1 evidence.

The observatory uses long-term memory only. Retrieval trace and experiment
surfaces read L1 evidence plus L2 / child-L2 / L3 long-term topic artifacts; they
do not call or display short-term memory context.

It shows three things:

- how transcripts become immutable L1 evidence objects;
- how L1 objects connect to L2 / child-L2 / L3 topic context;
- how layered memory retrieval compares with traditional RAG and full context.

For TAICHI paper/demo work, the Observatory is the primary system surface. The
`Demo Story` tab and optional `presentation.html` capture page are intended for
paper figures and short live walkthroughs.

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

## Demo Readiness Check

Before a TAICHI walkthrough, verify that the ICSI artifact-backed demo can load
and retrieve the fixed trace query:

```bash
uv run python memory_observatory/demo_health_check.py --dataset icsi
```

The same check is available through:

```text
GET /api/demo/health?dataset=icsi
```

Expected status for the current paper/demo artifact is `pass`. The check is
read-only: it verifies dataset registration, L1 source availability, L2/L3
runtime views, a no-LLM retrieval trace, selected L1/L2/L3 counts, and formatted
prompt context generation.

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

The UI also has a presentation-focused dataset switch:

- `Grace` keeps the original behavior and reads the canonical sources above.
- `ICSI` is read-only and artifact-backed. It reads L1 from
  `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/source_share_mem`,
  polished L2/L3 from
  `optimization/runs/icsi_bmr_full_completed29_v2_20260614/runtime`, and
  comparison metrics from
  `optimization/reports/icsi_bmr_full_completed29_system_comparison_revised_20260614`.
  The ICSI overview and trace views are intended for screenshot/demo use and
  run against these read-only sidecar artifacts.

Writable sidecars:

- `share_mem/user_feedback/importance_adjustments.jsonl`
- `share_mem/user_feedback/importance_override_index.json`
- `share_mem/user_feedback/importance_feedback_summary.json`
- `share_mem/user_feedback/summary_corrections.jsonl`
- `share_mem/user_feedback/summary_correction_index.json`
- `share_mem/user_feedback/validity_flags.jsonl`
- `share_mem/user_feedback/validity_flag_index.json`
- `share_mem/user_feedback/topic_link_reviews.jsonl`
- `share_mem/user_feedback/topic_link_review_index.json`
- `share_mem/user_feedback/correction_feedback_summary.json`
- `memory_observatory/runs/<run_id>/...`

Do not edit `share_mem/tree.json` to apply review feedback. The feedback editor
writes sidecar files only. `Correction Review` records importance overrides,
effective-summary corrections, validity flags, and topic-link review decisions
for the effective memory view; raw transcript evidence and raw L1 provenance
remain unchanged.

## Run A No-LLM Comparison Experiment

```bash
uv run python memory_observatory/run_experiment.py \
  --queries long_term/eval/long_term_retrieval_queries.jsonl \
  --out memory_observatory/runs \
  --strategies full_context,rag_baseline,layered_memory \
  --retrieval-mode hybrid \
  --no-llm
```

No-LLM mode does not call the Gemini recall planner or final answer LLM. The
layered retrieval default is `hybrid`: it fuses lexical L1 hits with semantic L1
hits when an embedding client is available, and falls back to lexical when it is
not. Use `--retrieval-mode lexical` for a fully offline retrieval smoke test.
The experiment CLI defaults to the heuristic layered planner; `--no-llm` is kept
in examples for clarity.

The experiment CLI defaults to `--max-context-chars 0`, which means an
unbounded diagnostic run. In that mode the experiment runner does not locally
shorten full-context, RAG, or layered-memory prompt contexts; the model
provider's real context window is the only remaining limit. RAG still has its
retrieval definition limit, controlled by `--rag-top-k`:

```bash
uv run python memory_observatory/run_experiment.py \
  --queries long_term/eval/long_term_retrieval_queries.jsonl \
  --out memory_observatory/runs \
  --strategies full_context,rag_baseline,layered_memory \
  --retrieval-mode hybrid \
  --no-llm \
  --generate-answers \
  --model gemini-2.5-pro \
  --max-context-chars 0 \
  --rag-top-k 12
```

For a more realistic budgeted comparison, avoid the gold-meeting full-context
oracle and cap Full Context / RAG to a multiplier of the Layered Memory context
tokens for each query:

```bash
uv run python memory_observatory/run_experiment.py \
  --queries doc/evaluation_questions_0307_0506.csv \
  --out memory_observatory/runs \
  --strategies full_context,rag_baseline,layered_memory \
  --retrieval-mode hybrid \
  --no-llm \
  --generate-answers \
  --model gemini-2.5-pro \
  --budget-profile deep_layered \
  --full-context-scope all \
  --baseline-token-multiplier 5 \
  --rag-top-k 999 \
  --max-context-chars 0
```

The UI Retrieval Trace demo profile options are:

- `observatory_trace` is the compact live-demo profile. It keeps the
  evidence-first path visible with one compact L2 / child-L2 slice, but gives
  the selected timeline event enough text to explain the method or decision
  being shown.
- `observatory_paper_trace` is the paper/screenshot profile. It keeps the same
  evidence-first contract but widens L1 seeds, L2 summaries, topic events, and
  global topic-map text so reviewers can inspect the actual topic context.

The underlying `RetrievalTraceService` service default is `generous_layered`
when no explicit budget profile is passed. It allows more L1 seeds and topic
timeline events for API callers and CLI experiments. `large_corpus_tight`
remains available for large-corpus budget diagnostics, and `deep_layered`
remains available for diagnostic runs where quality is more important than
prompt size.
`--baseline-token-multiplier 5` means Full Context and RAG can use about 5x the
Layered Memory context tokens for the same query.

## Run Artifacts And Legacy Runs

New generated run directories under `memory_observatory/runs/` are ignored by
git. Some old demo runs may still exist locally or in historical checkouts; the
`/api/runs` endpoint hides legacy run artifacts by default when their config was
created before the current hybrid/no-LLM/fairness-parameter schema. Use
`/api/runs?include_legacy=true` only when you explicitly need to inspect those
historical runs.

## Optional LLM Planner

The default path uses the heuristic no-LLM planner. If you explicitly want
Gemini to plan recall targets, pass `--use-llm-planner`; by default that planner
uses the same model as `--model` unless `--planner-model` or
`GEMINI_PLANNER_MODEL` is set.

```bash
uv run python memory_observatory/run_experiment.py \
  --queries long_term/eval/long_term_retrieval_queries.jsonl \
  --out memory_observatory/runs \
  --strategies full_context,rag_baseline,layered_memory \
  --retrieval-mode hybrid \
  --generate-answers \
  --use-llm-planner \
  --model gemini-2.5-pro
```

`--use-llm-planner` opts into Gemini recall planning. `--planner-model` is used
only for that planner call. Layered recall and answer generation still use
`--model`. The same split is available through the `/api/retrieval/trace`
`planner_model` query parameter and the `GEMINI_PLANNER_MODEL` environment
variable.

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

## Export Answers For Judge Scoring

Existing judge scripts under `app/score_evaluation_answers_v2.py` use a flat CSV
schema. Export a Memory Observatory run into that schema with:

```bash
uv run python memory_observatory/export_scoring_csv.py \
  --run memory_observatory/runs/<run_id> \
  --out memory_observatory/runs/<run_id>/observatory_scoring_input.csv
```

Observatory runs normally produce one answer per strategy, not a separate
evidence-answer variant. Score those exports with Answer rows only:

```bash
uv run python app/score_evaluation_answers_v2.py \
  --input memory_observatory/runs/<run_id>/observatory_scoring_input.csv \
  --output memory_observatory/runs/<run_id>/observatory_scores_v2.csv \
  --types answer
```

The exporter also writes `observatory_scoring_input.summary.json/md`. If
`missing_expected_answer_count` is nonzero, the run is useful for inspecting
retrieval and answers but should not be treated as a valid answer-quality judge
run until gold expected answers are attached.

For answer-quality experiments, use a query file that includes
`expected_answer`, such as `doc/evaluation_questions_0307_0506.csv`. The
experiment runner accepts both JSONL and CSV query files.

## Visual QA With Playwright

Playwright is available as a dev dependency for checking the local UI:

```bash
uv run python -m playwright install chromium
uv run uvicorn memory_observatory.main:app --host 127.0.0.1 --port 8765
```

Then a small Playwright script can open `http://127.0.0.1:8765/`, switch to
Experiment Lab, and capture screenshots or check element overflow.

## Memory Control Audit

The default demo screen includes a closed-loop, session-only audit workflow:

1. Inspect the L1 evidence and L2 topic state used by the baseline retrieval trace.
2. Challenge one topic state or exclude selected L1 evidence from a candidate context.
3. Rebuild and compare the formatted prompt context before claiming that the control had an effect.

The preview endpoint is `POST /api/demo/audit-preview?dataset=icsi`. It operates
on an in-memory copy of the structured recall result, never writes to raw L1 or
generated L2/L3 artifacts, and reports whether the source tree hash remained
unchanged. The UI labels answer generation as pending: this sandbox verifies
retrieval-context impact, not answer-quality impact, and makes no Vertex AI call.

## Pages

- Overview: memory pipeline and artifact statistics.
- Demo Story: a presentation-focused ICSI walkthrough showing topic memory,
  L1 evidence seeds, L2 evolution context, L3 navigation, and strategy contrast.
- Retrieval Trace: query -> L1 evidence -> L2 / child-L2 -> L3 -> prompt context.
- Memory Explorer: meeting, L1 object, evidence, topic link, feedback, and
  correction sidecar browsing.
- Topic Observatory: drawn L3 -> child L2 tree, L2 state/timeline detail,
  on-demand linked L1 evidence, and sidecar importance feedback.
- Correction Review: sidecar-only importance feedback, effective-summary
  corrections, validity flags, and topic-link review decisions.
- Experiment Lab: compare full context, traditional RAG, and layered memory.

## TAICHI Presentation Capture

The static capture page is available at:

```text
http://localhost:8000/static/presentation.html
```

It is a compact paper/demo view, not a separate product surface. Use it to
capture controlled figures when the full Observatory is too dense for a paper
screenshot. The source files are:

- `memory_observatory/static/presentation.html`
- `memory_observatory/static/presentation.css`
- `memory_observatory/static/presentation.js`

Paper-facing artifact notes live under `doc/taichi/`.
