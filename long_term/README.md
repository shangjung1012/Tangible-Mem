# Long-Term Memory

`long_term/` owns the current canonical Grace recall surface and fallback L2/L3
sidecars over immutable L1 evidence from `share_mem/`.

Do not use `long_term/tree.json` as a current source of truth; the old temporal
pipeline is archived under `long_term/archive/legacy_temporal_l2_l3/`.

For new datasets and future L2/L3 promotion work, prefer the isolated
profile-driven pipeline under `optimization/long_term_v2/`. The canonical
builder in this folder is still available as the Grace fallback and regression
baseline, but it is no longer the preferred path for ICSI or other new corpus
experiments.

Canonical sidecars remain the default runtime backend. For shadow-mode
comparison only, export an optimization v2 run with
`optimization/long_term_v2/export_runtime_view.py`, then set
`LONG_TERM_BACKEND=optimization_v2` and `OPTIMIZATION_V2_RUN_ROOT=<run-root>`.
If the exported v2 runtime view is missing or incomplete, the app falls back to
the canonical backend.

## Active Contract

- L1 source: `share_mem/tree.json` and `share_mem/meetings/<meeting_id>.json`.
- Recall: `long_term/recall.py`.
- Planner: `long_term/recall_planner.py`.
- L2 builder fallback: `long_term/build_l2_view.py`.
- L2 validator fallback: `long_term/validate_l2_view.py`.
- CLI: `long_term/cli.py`.

## Legacy Canonical Build And Validation

Use this path when rebuilding the current Grace fallback sidecars or when
running a direct comparison against optimization v2. Do not use it as the
primary L2/L3 induction path for ICSI or new datasets without an explicit
comparison objective.

```bash
uv run long_term/cli.py build-l2-view \
  --share-mem-root share_mem \
  --output-root long_term/l2 \
  --mode deterministic \
  --clean

uv run long_term/cli.py validate-l2-view \
  --share-mem-root share_mem \
  --root long_term/l2 \
  --out long_term/l2/validation

uv run long_term/cli.py validate-l3-view \
  --share-mem-root share_mem \
  --l2-root long_term/l2 \
  --l3-root long_term/l3 \
  --out long_term/l3/validation
```

The current L2 implementation is deterministic and does not call Gemini. It
links durable L1 objects to long-term topics and may intentionally leave
low-value or isolated L1 objects unlinked.

L2 topics are built from L1 `related_topics` first, not from a fully hand-written
topic list. The builder normalizes topic hints by lowercasing, replacing
underscores/hyphens with spaces, removing punctuation, dropping generic or
type-like labels, mapping aliases to canonical L2 labels, and deduplicating by
canonical label. Content keyword rules only confirm or refine those seeds,
especially when the seed is broad.

This builder is Grace-tuned. Its data format, sidecar generation, and validators
remain useful, but its topic assignment behavior is not the target architecture
for new datasets. New dataset work should generate L2/L3 sidecars with
`optimization/long_term_v2/` and keep outputs under `optimization/runs/` until a
runtime backend selector is promoted.

L3 promotion is deterministic by default. To let Gemini assist only the L3
split stage, run:

```bash
uv run long_term/cli.py build-l2-view \
  --share-mem-root share_mem \
  --output-root long_term/l2 \
  --mode deterministic \
  --l3-mode llm-assisted \
  --l3-source-l2-id L2-memory-evaluation-strategy
```

## Generated Outputs

- `long_term/l2/l2_index.json`: `obj_id -> l2_id / l2_label / assignment`.
- `long_term/l2/l2_view.json`: compact L2 state, timeline digest, linked L1 ids.
- `long_term/l2/l2_updates/<meeting_id>.json`: per-meeting L2 assignment events.
- `long_term/l2/unlinked_l1_report.json`: skipped L1 objects and review queue.
- `long_term/l2/l2_assignment_review_report.json`: topic size and assignment review summary.
- `long_term/l2/validation/`: validation reports.
- `long_term/l3/l3_promotions.json`: oversized L2 promotion candidates.
- `long_term/l3/l3_view.json`: materialized L3 parents with child L2 nodes.
- `long_term/l3/l3_index.json`: `obj_id -> L3 / child L2` lookup.
- `long_term/l3/l2_merge_review.json`: review-only tiny/weak/oversized child L2 follow-up queue.
- `long_term/l3/l2_split_proposals.json`: review-only candidate child-L2 labels
  for oversized L2 topics that do not yet have reviewed deterministic splits.
- `long_term/l3/validation/`: L3 split coverage, scale-aware child-size,
  prompt-budget, and merge-review reports.
- `long_term/eval/`: retrieval parameter evaluation queries and reports.

## Recall Path

Long-term recall is bottom-up:

```text
query
  -> hybrid L1 retrieval from share_mem/tree.json
  -> compact global topic map from l3_view + unpromoted l2_view labels
  -> l3_index.json lookup by seed obj_id, when available
  -> materialized child L2 context first
  -> l2_index.json / l2_view.json fallback when no child L2 assignment exists
  -> formatted prompt context
```

Missing L2 assignments are non-fatal. Large L2 topics are sliced for prompt
budget safety and should not inject their full timeline. Legacy temporal
phase/profile expansion is compatibility fallback only.

## L3 Promotion

L3 means overflow promotion above L2. If an L2 topic becomes too broad, it can
be promoted into an L3 parent and split into multiple child L2 topics.

The current L3 implementation is materialized as sidecars only:

- hard warning: `linked_l1_count >= 24`
- soft warning: `linked_l1_count >= 12` and `l1_share >= 0.30`
- promotion review sidecar: `long_term/l3/l3_promotions.json`
- materialized child L2 sidecars: `long_term/l3/l3_view.json` and
  `long_term/l3/l3_index.json`
- child-L2 review sidecar: `long_term/l3/l2_merge_review.json`
- unknown-large-L2 split proposal sidecar:
  `long_term/l3/l2_split_proposals.json`

This does not rewrite raw L1 evidence, `l2_index.json`, or `l2_view.json`.

`l2_split_proposals.json` is not a promotion decision. It is a deterministic
review queue that proposes repeated keyword clusters for oversized L2 topics
whose `l3_promotions.json` record is still `needs_split_review`. If the
proposal has low lexical diversity, it is marked with
`insufficient_distinct_keyword_clusters` instead of forcing fake child L2
splits.

The default materialization does not call an LLM. With
`--l3-mode llm-assisted`, Gemini is used only inside the L3 sidecar pipeline.
Large L2 topics that already have reviewed deterministic child splits keep
those splits; Gemini is called for oversized L2 topics that do not yet have
child L2 candidates. Use `--l3-source-l2-id` to limit the API call to one
oversized L2 during review:

1. propose child L2 taxonomy from that promoted L2's linked L1 compact evidence;
2. suggest `obj_id -> child_l2_id` assignments for those same L1 rows;
3. validate every assignment deterministically, falling back to
   `assignment_criteria` and marking low-confidence or invalid suggestions for
   manual review.

Even in LLM-assisted mode, raw L1 evidence, `l2_index.json`, and `l2_view.json`
are not rewritten.

Tiny child L2 nodes are not merged automatically and should not be treated as
wrong only because they are small. A tiny child can be an emerging or niche
topic. The builder writes `l2_merge_review.json` so a reviewer can distinguish
`watch_until_more_evidence` from `merge_candidate`; a merge is recommended only
when sibling similarity is high. The validator checks that tiny child L2 nodes
appear in that review sidecar.

Large child L2 nodes are also not automatically wrong. Validation keeps the
raw size bucket, but adds `scale_assessment`: a large child with strong
assignment-criteria coherence is treated as `large_coherent_needs_retrieval_slice`,
while a large low-coherence child remains `large_low_coherence_needs_split_review`
and enters manual review. This prevents a 50-meeting corpus from forcing fake
taxonomy splits while still surfacing genuinely mixed child topics.

For side-by-side synthetic taxonomy checks, use the reporting-only gold-topic
mapping gate. This compares expected synthetic topic labels against generated
L2/L3 assignment sidecars and writes review artifacts without changing raw L1 or
canonical Grace outputs:

```bash
uv run python long_term/taxonomy_refinement.py gold-topic-mapping \
  --share-mem-root share_mem_experiments/synthetic_longmeet_50_diverse_idea_units \
  --l2-root long_term/eval/synthetic_longmeet_50_diverse_idea_units/l2 \
  --l3-root long_term/eval/synthetic_longmeet_50_diverse_idea_units/l3 \
  --gold-path share_mem_experiments/synthetic_longmeet_50_diverse_idea_units/gold/obj_id_to_expected_topic.json \
  --out long_term/eval/synthetic_longmeet_50_diverse_idea_units/gold_mapping
```

## Retrieval Evaluation

Run the lightweight retrieval-only parameter grid:

```bash
uv run python long_term/evaluate_retrieval.py \
  --queries long_term/eval/long_term_retrieval_queries.jsonl \
  --out long_term/eval \
  --no-llm \
  --retrieval-mode hybrid
```

With `--no-llm`, the eval path uses the heuristic recall plan and does not call
the Gemini planner or a final answer LLM. The default L1 seed retrieval mode is
`hybrid`: lexical hits are always used, semantic hits are fused in when an
embedding client is available, and the path falls back to lexical when offline.
Use `--retrieval-mode lexical` for a fully offline retrieval smoke test. Use
`--retrieval-mode semantic` only when you intentionally want embedding-only
retrieval. The default grid covers the current smoke surface for `top_k_raw`,
seed count, child-L2 events, expanded topic count, and topic-size penalty. The
report compares expected L1/L2/L3 hits, prompt character budget, omitted events,
and whether a large L2 was expanded without child split context.

Named retrieval budget profiles are deterministic presets used by the app,
Observatory, and eval scripts:

- `eval_best`: current Grace no-LLM hybrid eval profile.
- `generous_layered`: current app and Observatory trace runtime profile. It
  keeps a bounded evidence-first slice, but raises the default from the older
  tight profile to 24 L1 seeds, two relevant topic summaries, two expanded
  L2/child-L2 topics, up to 8 child-L2 timeline events, and up to two
  same-parent L3 sibling child-L2 slices for rationale/evolution/architecture
  queries. This is the default because the tighter profile saved tokens at the
  cost of answer context.
- `large_corpus_tight`: large-corpus, RAG-competitive budget profile. It keeps
  8 L1 evidence seeds versus `eval_best`'s 12, and slices global topic map and
  L2/child-L2 timeline context more aggressively. Treat it as a quality-preserving
  efficiency profile, not as a hard ultra-short target. The eval prompt-budget
  threshold is currently 16000 characters so retrieval quality is not sacrificed
  just to shorten already-RAG-competitive context.

Use the tight profile only with a guard run for the target dataset:

```bash
uv run python long_term/evaluate_retrieval.py \
  --queries long_term/eval/long_term_retrieval_queries.jsonl \
  --out long_term/eval/grace_tight_profile_guard \
  --no-llm \
  --retrieval-mode hybrid \
  --budget-profile large_corpus_tight
```

The acceptance criterion for this profile is retrieval quality first:
L1/L2/L3 hits should not regress versus `eval_best`. Prompt size should then be
compared against the RAG baseline for the same query set; beating RAG on context
tokens is more important than satisfying an arbitrary character cap.

For side-by-side synthetic roots, pass the generated sidecar roots explicitly
so the eval does not accidentally use active Grace L2/L3:

```bash
uv run python long_term/evaluate_retrieval.py \
  --queries long_term/eval/synthetic_longmeet_50_diverse_idea_units/retrieval_issue_queries.jsonl \
  --share-mem-root share_mem_experiments/synthetic_longmeet_50_diverse_idea_units \
  --l2-root long_term/eval/synthetic_longmeet_50_diverse_idea_units/l2 \
  --l3-root long_term/eval/synthetic_longmeet_50_diverse_idea_units/l3 \
  --out long_term/eval/synthetic_longmeet_50_diverse_idea_units/retrieval_issue_tight \
  --no-llm \
  --retrieval-mode hybrid \
  --budget-profile large_corpus_tight
```

For API-backed planner experiments, `--model` remains the recall/answer model,
`--use-llm-planner` opts into Gemini recall planning, and `--planner-model`
controls only that planner call. If no planner model is provided, the planner
uses `--model`:

```bash
uv run python long_term/evaluate_retrieval.py \
  --queries long_term/eval/long_term_retrieval_queries.jsonl \
  --out long_term/eval \
  --retrieval-mode hybrid \
  --use-llm-planner \
  --model gemini-2.5-pro
```

## Current Generated State

- Source L1: 7 Grace meetings, 448 L1 objects. Canonical L1 `content` is
  Traditional Chinese; `related_topics` remain English machine-facing keys.
- L2 view: 16 L2 topics, 411 linked L1 objects, 37 unlinked L1 objects.
- L2 validation: 0 severe issues; 3 warnings for high-importance unlinked
  administrative / project-logistics objects.
- L3 validation: 0 severe issues; 5 warnings, all prompt-slice diagnostics
  rather than assignment coverage or oversized-child failures.
- Materialized L3: 2 parents, 14 child L2 topics, 169 assigned L1 objects,
  0 unassigned L1 objects.
- Reviewed deterministic L3: `L3-transcript-segmentation-and-idea-unit-coverage`
  and `L3-memory-evaluation-strategy`.
- Retrieval eval: 8 demo-safe queries, no-LLM hybrid `generous_layered` run,
  expected L1 recall 0.8594, strict L1 recall 1.0, L2 hit rate 1.0, L3 hit
  rate 1.0, average context 12018.38 chars, and prompt-budget pass rate 1.0.

## Archive Boundary

The old temporal L1/L2/L3 pipeline, old snapshots, and prototype viewers are
under `long_term/archive/`. They are historical reference only and are not
exposed through active CLI commands.

The current canonical L2/L3 builder implementation is archived under
`long_term/archive/canonical_l2_l3_builder_legacy/`. Root-level modules with the
same names remain as compatibility wrappers for existing CLI commands, tests,
and rollback workflows.
