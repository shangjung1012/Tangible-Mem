# ICSI Answer Quality Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a formal ICSI BMR first360 answer-quality comparison between full context, traditional lexical RAG, and optimization v2 candidate6.

**Architecture:** Keep raw generated contexts, answers, and judge rows in ignored `optimization/runs/`, then publish a compact tracked summary under `optimization/reports/`. The runner uses the effective ICSI L1 root and candidate6 optimization v2 run; it does not read or write canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.

**Tech Stack:** Python, unittest, Gemini via existing `share_mem.l1.gemini_clients`, optimization v2 JSON artifacts, PowerShell commands.

---

## Scope

Inputs:

- effective L1 root: `memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective`
- transcript root: `meeting_recording/transcript/ISCI`
- optimization v2 run: `optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609`
- queries: `optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl`

Strategies:

- `full_context_first360`: all available BMR first360 transcript lines for the effective corpus, no token cap.
- `rag_baseline_first360`: lexical line chunks over the same first360 transcript scope, normal top-k, no token cap.
- `optimization_v2_candidate6`: evidence-first optimization v2 context from candidate6.

Out of scope:

- Do not compare current canonical `long_term/l2/l3` as an ICSI baseline; it is Grace-oriented and already known to risk domain leakage.
- Do not promote candidate6 into runtime.
- Do not write generated answer rows into canonical directories.

## Task 1: Add ICSI Answer-Quality Runner

**Files:**
- Create: `optimization/long_term_v2/run_icsi_answer_quality_comparison.py`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] Add tests for first360 transcript context construction:

```python
def test_icsi_full_context_uses_requested_line_scope(self) -> None:
    ...
```

Expected:

- Reads only requested meetings.
- Includes no more than the configured first N transcript lines.

- [ ] Add tests for expected-answer brief construction:

```python
def test_icsi_expected_answer_brief_uses_gold_l1_content(self) -> None:
    ...
```

Expected:

- Builds a judge gold brief from `expected_obj_ids`.
- Includes expected L2 labels and representative L1 content.

- [ ] Implement the runner with these public helpers:

```python
build_first360_full_context(...)
retrieve_first360_lexical_rag(...)
build_expected_answer_brief(...)
run_icsi_answer_quality_comparison(...)
```

## Task 2: Run Smoke Comparison

**Files:**
- Output: `optimization/runs/icsi_bmr_first360_answer_quality_candidate6_smoke_20260609/`

- [ ] Run a 2-query smoke with Gemini answer generation and judge scoring:

```powershell
uv run python optimization/long_term_v2/run_icsi_answer_quality_comparison.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --share-mem-root memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective `
  --transcript-dir meeting_recording/transcript/ISCI `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --out optimization/runs/icsi_bmr_first360_answer_quality_candidate6_smoke_20260609 `
  --summary-out optimization/reports/icsi_bmr_first360_candidate6_full_answer_quality_smoke `
  --max-queries 2 `
  --model gemini-2.5-pro `
  --judge-model gemini-2.5-pro
```

Expected:

- Exit 0.
- `summary.json`, `summary.md`, and `scored_rows.json` exist.
- No canonical artifacts modified.

## Task 3: Run Full 12-Query Comparison

**Files:**
- Output: `optimization/runs/icsi_bmr_first360_answer_quality_candidate6_20260609/`
- Output: `optimization/reports/icsi_bmr_first360_candidate6_full_answer_quality/`

- [ ] Run all ICSI query rows:

```powershell
uv run python optimization/long_term_v2/run_icsi_answer_quality_comparison.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --share-mem-root memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective `
  --transcript-dir meeting_recording/transcript/ISCI `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --out optimization/runs/icsi_bmr_first360_answer_quality_candidate6_20260609 `
  --summary-out optimization/reports/icsi_bmr_first360_candidate6_full_answer_quality `
  --model gemini-2.5-pro `
  --judge-model gemini-2.5-pro
```

Expected:

- Exit 0.
- Summary contains all 12 queries and 36 scored strategy rows.
- Full context is first360 scoped but not token-capped.
- RAG is not artificially token-capped.
- Optimization v2 answer quality is clearly reported, whether it wins or loses.

## Task 4: Verification

**Files:**
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] Run targeted tests:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2 tests.test_optimization_l2_l3_scaling tests.test_optimization_runtime_adapter tests.test_memory_output_roots
```

Expected: OK.

- [ ] Run full tests:

```powershell
uv run python -m unittest discover -s tests
```

Expected: OK.

- [ ] Run hygiene checks:

```powershell
git diff --check
# Run the repo's normal targeted secret scan; do not include real credentials in commands or reports.
git status --short --branch
```

Expected:

- No whitespace errors.
- No real secrets.
- Dirty files limited to optimization/docs/tests/reports.

## Promotion Boundary

This comparison can support a stronger claim about candidate6 quality, but it
does not by itself promote optimization v2. Promotion still requires:

- runtime adapter shadow mode,
- repeated cross-dataset checks,
- user approval before replacing canonical runtime.
