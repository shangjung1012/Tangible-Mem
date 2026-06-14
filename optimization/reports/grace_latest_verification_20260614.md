# Grace Latest Verification 2026-06-14

## Scope

This report verifies that the latest code after the ICSI eval-pack changes still works on Grace optimization v2 outputs.

No Grace L1 extraction was rerun. Raw Grace `share_mem/` remains the evidence source. This verification only reruns retrieval/shadow checks against the existing optimization v2 Grace runtime.

## Inputs

- Grace share_mem root: `share_mem`
- Optimization v2 runtime root: `optimization/runs/runtime_shadow_grace_20260605_031853`
- Queries: `long_term/eval/long_term_retrieval_queries.jsonl`

## Retrieval Eval

Output:

- `optimization/runs/runtime_shadow_grace_20260605_031853/retrieval_eval/latest_commit_20260614/retrieval_eval_report.json`
- `optimization/runs/runtime_shadow_grace_20260605_031853/retrieval_eval/latest_commit_20260614/retrieval_eval_report.md`

Result:

- queries: `8`
- avg expected L1 recall: `0.9219`
- expected L2 hit rate: `0.25`
- expected L2 semantic hit rate: `1.0`
- expected L3 hit rate: `0.625`
- expected L3 semantic hit rate: `1.0`

Interpretation:

- Exact L2/L3 ids do not always match the canonical Grace eval ids because optimization v2 uses its own topic surface.
- Semantic L2/L3 hits remain `1.0`, which is the relevant compatibility signal for optimization v2.
- L1 retrieval remains high at `0.9219`.

## Shadow Trace QA

Output:

- `optimization/reports/grace_shadow_qa_latest_20260614/summary.json`
- `optimization/reports/grace_shadow_qa_latest_20260614/summary.md`

Result:

- decision: `shadow_qa_pass`
- query count: `8`
- shadow trace ready: `8`
- needs review: `0`
- average context tokens:
  - canonical: `8603.125`
  - optimization v2: `8467.625`

## Shadow Answer Quality Smoke

Output:

- `optimization/reports/grace_shadow_answer_quality_latest_20260614/summary.json`
- `optimization/reports/grace_shadow_answer_quality_latest_20260614/summary.md`

This is a regression smoke using existing scored rows, not a full answer regeneration run.

Result:

- decision: `answer_quality_pass`
- query count: `8`
- row count: `16`
- canonical overall: `0.9643`
- optimization v2 overall: `0.9384`
- optimization minus canonical: `-0.0259`
- source traceability:
  - canonical: `1.0`
  - optimization v2: `1.0`
- hallucination risk:
  - canonical: `0.0`
  - optimization v2: `0.0`

Interpretation:

- The latest code still passes Grace shadow answer-quality gate.
- Canonical remains slightly higher on this old Grace answer-quality sample, but the delta is within the configured pass threshold and optimization v2 preserves traceability and hallucination safety.

## Canonical Safety

Checked:

- `share_mem`
- `long_term/l2`
- `long_term/l3`
- `long_term/eval/retrieval_eval_report.json`
- `long_term/eval/retrieval_eval_report.md`

Result:

- canonical diff: none
- `.env` untouched

## Test Verification

Command:

```powershell
uv run python -m unittest tests.test_optimization_runtime_adapter tests.test_optimization_long_term_v2
```

Result:

- tests: `111`
- status: `OK`

## Conclusion

Grace has now been re-verified on the latest code without rerunning raw L1 or mutating canonical artifacts. The latest ICSI-focused changes did not break Grace optimization v2 retrieval, shadow trace QA, or answer-quality gate behavior.
