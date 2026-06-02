# Long-Term Memory v2

This is an experimental, optimization-only long-term memory view builder. It
reads an existing `share_mem` L1 evidence store and writes side-by-side outputs
under `optimization/runs/<run_id>/`.

Design constraints:

- Raw L1 evidence is immutable.
- Existing `long_term/l2` and `long_term/l3` are baseline inputs only.
- `related_topics` are optional source signals, not canonical L2 labels.
- L2/L3 generation should be evidence-backed and explainable.
- Grace-specific rules belong in explicit profile overrides, not core code.

Example:

```powershell
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root share_mem `
  --profile optimization/long_term_v2/profiles/mentor_mentee.yaml `
  --out optimization/runs/grace_v2_001 `
  --mode deterministic `
  --clean

uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/grace_v2_001
```

Maturity tooling added after the initial v2 scaffold:

- `validate_llm_proposals.py` validates LLM merge/split/assignment proposals
  before they can be treated as accepted sidecar decisions.
- `evaluate_answer_quality.py` aggregates scored answer rows across full
  context, RAG, canonical layered memory, and optimization-v2 strategies.
- `finalize_manual_review.py` turns reviewer-filled JSONL decisions into a
  pass/fail manual-review report.
- `run_maturity_suite.py` runs multiple isolated datasets into
  `optimization/runs/<suite_id>/`.
- `maturity_certification.py` is the single maturity summary. A run is still
  not promotable unless answer quality, final manual review, cross-dataset
  suite, tests, secret scan, and repeated stability all pass.
- `curate_v2_native_queries.py` creates deterministic, evidence-backed
  retrieval diagnostic queries from a v2 run's own L2 topics. Use
  `--topic-source needs_split` for large synthetic topics and `--topic-source
  largest` for pilot corpora such as ICSI.
- `retrieval_split_pressure.py` ranks `needs_split_review` topics by actual
  retrieval-query hits, so split work is driven by retrieval pressure rather
  than raw topic size alone.

Recent diagnostic reports:

- `optimization/reports/v2_native_query_diagnostics_20260603_0001.md`
- `optimization/reports/maturity_certification_split_pressure_20260602_0002`

Example v2-native query diagnostic flow:

```powershell
uv run python optimization/long_term_v2/curate_v2_native_queries.py `
  --run-root optimization/runs/<run_id> `
  --topic-source needs_split `
  --max-queries 12

uv run python optimization/long_term_v2/evaluate_retrieval.py `
  --run-root optimization/runs/<run_id> `
  --queries optimization/runs/<run_id>/retrieval_eval/v2_native_queries.jsonl `
  --share-mem-root optimization/runs/<run_id>/input_snapshot `
  --out-subdir retrieval_eval_v2_native

uv run python optimization/long_term_v2/retrieval_split_pressure.py `
  --run-root optimization/runs/<run_id> `
  --retrieval-subdir retrieval_eval_v2_native
```
