# Optimization V2 Shadow Runtime Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that an isolated optimization v2 run can be loaded through the existing long-term runtime path resolver in shadow mode, without changing canonical runtime defaults.

**Architecture:** Reuse the existing `optimization/long_term_v2/export_runtime_view.py` and `app.memory_context.resolve_long_term_runtime_paths()` instead of creating another adapter. Add a small report generator that verifies runtime sidecar completeness, canonical fallback safety, and lexical sample traces against the optimization v2 runtime export. Outputs stay under `optimization/reports/`.

**Tech Stack:** Python, unittest, existing optimization v2 JSON sidecars, `app.memory_context`, PowerShell commands.

---

## Scope

Inputs:

- candidate run root: `optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609`
- query file: `optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl`
- existing runtime export under `<run-root>/runtime`

Outputs:

- `optimization/reports/icsi_bmr_first360_candidate6_shadow_readiness/summary.json`
- `optimization/reports/icsi_bmr_first360_candidate6_shadow_readiness/summary.md`

Non-goals:

- Do not set `.env` to use optimization v2.
- Do not modify `app/memory_context.py` unless a defect is found.
- Do not write into canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.
- Do not call Gemini or embeddings; shadow readiness uses lexical/no-LLM retrieval only.

## Task 1: Add Shadow Readiness Tests

**Files:**
- Modify: `tests/test_optimization_runtime_adapter.py`
- Create: `optimization/long_term_v2/shadow_runtime_readiness.py`

- [ ] Add a test that a complete runtime export is reported as ready.

Expected:

- Missing file count is `0`.
- Backend resolved under `LONG_TERM_BACKEND=optimization_v2`.
- Sample prompt contains `Global Topic Map` and `L1 Evidence Seeds`.
- Canonical fallback remains available when env vars are absent.

- [ ] Add a test that an incomplete runtime export is blocked.

Expected:

- Readiness decision is `not_ready`.
- Missing runtime files are listed.

## Task 2: Implement Shadow Readiness Report

**Files:**
- Create: `optimization/long_term_v2/shadow_runtime_readiness.py`

- [ ] Implement:

```python
REQUIRED_RUNTIME_RELATIVE_PATHS = [...]
inspect_runtime_export(run_root: Path) -> dict[str, Any]
run_shadow_readiness_report(run_root: Path, queries_path: Path, out: Path, max_queries: int = 3) -> dict[str, Any]
```

Expected report fields:

- source run root
- runtime root
- required file status
- runtime manifest counts
- resolved backend with optimization env
- fallback backend without optimization env
- sample lexical prompt summaries
- decision: `shadow_ready` or `not_ready`
- canonical mutation: always `false`

## Task 3: Run Candidate6 Shadow Readiness

**Command:**

```powershell
uv run python optimization/long_term_v2/shadow_runtime_readiness.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --out optimization/reports/icsi_bmr_first360_candidate6_shadow_readiness `
  --max-queries 3
```

Expected:

- Exit 0.
- Summary decision is `shadow_ready`.
- Report states this is shadow-mode only, not canonical promotion.

## Task 4: Verification

**Commands:**

```powershell
uv run python -m unittest tests.test_optimization_runtime_adapter
uv run python -m unittest tests.test_optimization_long_term_v2 tests.test_optimization_l2_l3_scaling tests.test_optimization_runtime_adapter tests.test_memory_output_roots
uv run python -m unittest discover -s tests
git diff --check
git status --short --branch
```

Expected:

- Tests pass.
- Whitespace check has no errors.
- Dirty files limited to this plan, new report/tool, and tests.

## Acceptance Criteria

- Candidate6 can be read through optimization v2 runtime paths in shadow mode.
- Missing runtime export fails closed and falls back to canonical when configured through `app.memory_context`.
- Sample lexical traces prove formatted long-term context is available from optimization v2.
- Canonical runtime defaults remain unchanged.
- Report clearly says `shadow_ready`, not `promoted`.
