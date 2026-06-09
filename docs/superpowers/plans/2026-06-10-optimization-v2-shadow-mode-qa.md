# Optimization V2 Shadow-Mode QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a rigorous shadow-mode QA loop that runs the same query set through canonical and optimization v2 backends, compares retrieval traces, answer quality, token/latency, and fallback behavior, without changing canonical runtime defaults.

**Architecture:** Add a QA runner under `optimization/long_term_v2/` that temporarily overrides backend environment variables per query, calls the existing `app.memory_context` retrieval path, extracts structured trace features from formatted prompt context, optionally runs answer generation/scoring, and writes isolated reports under `optimization/runs/` plus compact summaries under `optimization/reports/`. The runner treats canonical as the active production baseline and optimization v2 as a read-only shadow backend; it never edits `.env`, `share_mem/`, `long_term/l2`, or `long_term/l3`.

**Tech Stack:** Python, unittest, existing `app.memory_context`, existing optimization v2 runtime export, existing answer-quality scoring helpers, JSON/Markdown reports, PowerShell commands.

---

## Current Baseline To Preserve

- Canonical app runtime defaults must stay unchanged:
  - `LONG_TERM_BACKEND` absent or non-v2 resolves to canonical.
  - canonical paths are `share_mem/tree.json`, `long_term/l2/*`, `long_term/l3/*`.
- Optimization v2 candidate6 is already shadow-readable:
  - report: `optimization/reports/icsi_bmr_first360_candidate6_shadow_readiness/summary.md`
  - decision: `shadow_ready`
  - L2 topics: `134`
  - L3 parents: `56`
  - L2 index count: `1359`
  - L3 index count: `986`
  - sample traces include `Global Topic Map`, `L1 Evidence Seeds`, and `L2 Evolution Context`.
- Optimization v2 candidate6 answer-quality comparison on ICSI BMR first360:
  - report: `optimization/reports/icsi_bmr_first360_candidate6_full_answer_quality/summary.md`
  - optimization v2 overall: `0.7714`
  - full context overall: `0.5417`
  - RAG overall: `0.6155`
  - optimization v2 average context tokens: `2981.0833`
- Promotion boundary:
  - `shadow_ready` is not canonical promotion.
  - This plan must not set `.env` or change app default backend.

## What This QA Must Prove

The goal is not just "v2 can load." It must show:

1. **Runtime equivalence surface:** canonical and optimization v2 can both be called through the same `app.memory_context.retrieve_long_term_context()` entrypoint.
2. **Trace visibility:** both backend traces expose useful sections; optimization v2 must contain L1 evidence and topic context.
3. **Fallback safety:** incomplete or missing optimization runtime falls back to canonical, with a clear reason.
4. **Quality boundary:** optimization v2 does not regress on trace metrics or answer quality for supported datasets.
5. **Domain boundary:** ICSI canonical comparison is diagnostic only because canonical still carries Grace ontology risk; Grace canonical comparison is a valid production parity baseline.
6. **No mutation:** reports prove no canonical files were edited.

## Dataset Matrix

### Grace

Purpose: canonical-vs-v2 parity and regression check.

Inputs:

- canonical backend: current app default.
- optimization run root: latest Grace optimization v2 run if present; otherwise create a readiness blocker instead of inventing a result.
- query files:
  - `long_term/eval/long_term_retrieval_queries.jsonl`
  - `optimization/long_term_v2/eval/mentor_mentee_answer_quality_queries.jsonl`

Expected interpretation:

- canonical is valid baseline.
- optimization v2 should not lose L1 evidence, L2 context, or answer quality.

### ICSI BMR First360

Purpose: verify candidate6 works as an ICSI shadow backend and compare against legacy canonical only as a diagnostic.

Inputs:

- optimization run root:
  - `optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609`
- query file:
  - `optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl`

Expected interpretation:

- optimization v2 is the relevant ICSI candidate.
- canonical is not a gold ICSI baseline; if canonical retrieves Grace-like memory-system topics for ICSI queries, report it as domain leakage evidence, not as an optimization failure.

### Optional LOCOMO-Style Fixture

Purpose: small cross-domain sanity check, not promotion gate.

Inputs:

- Use any existing LOCOMO-style fixture if present under `optimization/long_term_v2/eval/` or `memory_outputs/`.
- If absent, the runner records `dataset_status=not_available` and does not fail the QA.

Expected interpretation:

- confirms that QA tooling itself is dataset-configurable.
- not required for this first shadow QA deliverable.

---

## File Structure

Create:

- `optimization/long_term_v2/shadow_mode_qa.py`
  - Runs canonical and optimization backend traces with temporary environment overrides.
  - Extracts section, L1, L2, L3, token, latency, and fallback metrics.
  - Writes raw per-query results and compact summary.

- `optimization/long_term_v2/shadow_mode_qa_config.py`
  - Defines dataset/backend/query config objects.
  - Keeps path decisions out of the runner logic.

- `optimization/reports/icsi_bmr_first360_candidate6_shadow_qa/summary.json`
- `optimization/reports/icsi_bmr_first360_candidate6_shadow_qa/summary.md`
  - Compact tracked QA result.

- `optimization/runs/icsi_bmr_first360_candidate6_shadow_qa_<timestamp>/`
  - Ignored raw contexts and per-query traces.

Modify:

- `tests/test_optimization_runtime_adapter.py`
  - Add unit tests for backend env isolation and fallback behavior.

- `tests/test_optimization_long_term_v2.py`
  - Add unit tests for trace feature extraction and report summary gate decisions.

Do not modify:

- `.env`
- `share_mem/*`
- `long_term/l2/*`
- `long_term/l3/*`
- existing canonical app default behavior.

---

## Task 1: Define Shadow QA Contracts

**Files:**
- Create: `optimization/long_term_v2/shadow_mode_qa_config.py`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] **Step 1: Add failing tests for config schema**

Add to `tests/test_optimization_long_term_v2.py`:

```python
def test_shadow_qa_backend_specs_are_explicit(self) -> None:
    from optimization.long_term_v2.shadow_mode_qa_config import default_backend_specs

    specs = default_backend_specs(
        optimization_run_root=Path("optimization/runs/demo"),
    )

    self.assertEqual(specs["canonical"]["backend_name"], "canonical")
    self.assertEqual(specs["canonical"]["env"], {})
    self.assertEqual(specs["optimization_v2"]["backend_name"], "optimization_v2")
    self.assertEqual(specs["optimization_v2"]["env"]["LONG_TERM_BACKEND"], "optimization_v2")
    self.assertEqual(
        specs["optimization_v2"]["env"]["OPTIMIZATION_V2_RUN_ROOT"],
        "optimization/runs/demo",
    )
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'optimization.long_term_v2.shadow_mode_qa_config'
```

- [ ] **Step 2: Implement config module**

Create `optimization/long_term_v2/shadow_mode_qa_config.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any


def default_backend_specs(*, optimization_run_root: Path | str) -> dict[str, dict[str, Any]]:
    run_root = str(Path(optimization_run_root))
    return {
        "canonical": {
            "backend_name": "canonical",
            "role": "active_baseline",
            "env": {},
            "expected_backend": "canonical",
        },
        "optimization_v2": {
            "backend_name": "optimization_v2",
            "role": "shadow_candidate",
            "env": {
                "LONG_TERM_BACKEND": "optimization_v2",
                "OPTIMIZATION_V2_RUN_ROOT": run_root,
            },
            "expected_backend": "optimization_v2",
        },
    }
```

- [ ] **Step 3: Run config test**

Run:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2.OptimizationLongTermV2Tests.test_shadow_qa_backend_specs_are_explicit
```

Expected:

```text
Ran 1 test
OK
```

---

## Task 2: Add Trace Feature Extraction

**Files:**
- Create: `optimization/long_term_v2/shadow_mode_qa.py`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] **Step 1: Add failing tests for section and ID extraction**

Add to `tests/test_optimization_long_term_v2.py`:

```python
def test_shadow_qa_extracts_trace_features(self) -> None:
    from optimization.long_term_v2.shadow_mode_qa import extract_trace_features

    context = '''
=== Global Topic Map ===
- L3 L3-data-quality: data quality
  - child L2 L2-data-quality-audio: audio data quality

=== L1 Evidence Seeds ===
- [Bmr001_first360 | 2026-06-04 | L1-Bmr001_first360-001] type=finding importance=0.7 score=0.8
  content: The group discussed audio quality.

=== L2 / Child-L2 Evolution Context ===
[L2-data-quality] data quality
  parent L3: L3-data-quality data quality
'''.strip()

    features = extract_trace_features(context)

    self.assertTrue(features["has_global_topic_map"])
    self.assertTrue(features["has_l1_evidence_seeds"])
    self.assertTrue(features["has_l2_evolution_context"])
    self.assertEqual(features["l1_ids"], ["L1-Bmr001_first360-001"])
    self.assertIn("L2-data-quality", features["l2_ids"])
    self.assertIn("L3-data-quality", features["l3_ids"])
    self.assertGreater(features["context_char_count"], 100)
    self.assertGreater(features["estimated_context_tokens"], 0)
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'optimization.long_term_v2.shadow_mode_qa'
```

- [ ] **Step 2: Implement trace feature extractor**

Create the top of `optimization/long_term_v2/shadow_mode_qa.py`:

```python
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import memory_context
from memory_observatory.services.token_utils import estimate_tokens
from optimization.long_term_v2.io_utils import load_json, utc_now_iso, write_json, write_text
from optimization.long_term_v2.shadow_mode_qa_config import default_backend_specs

L1_RE = re.compile(r"\\bL1-[A-Za-z0-9_\\-]+")
L2_RE = re.compile(r"\\bL2-[A-Za-z0-9_\\-]+")
L3_RE = re.compile(r"\\bL3-[A-Za-z0-9_\\-]+")


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def extract_trace_features(context: str) -> dict[str, Any]:
    text = str(context or "")
    return {
        "context_char_count": len(text),
        "estimated_context_tokens": estimate_tokens(text),
        "has_global_topic_map": "=== Global Topic Map ===" in text,
        "has_l1_evidence_seeds": "=== L1 Evidence Seeds ===" in text,
        "has_l2_evolution_context": "=== L2 / Child-L2 Evolution Context ===" in text,
        "has_retrieval_debug": "=== Retrieval Debug ===" in text,
        "l1_ids": _ordered_unique(L1_RE.findall(text)),
        "l2_ids": _ordered_unique(L2_RE.findall(text)),
        "l3_ids": _ordered_unique(L3_RE.findall(text)),
    }
```

- [ ] **Step 3: Run extractor test**

Run:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2.OptimizationLongTermV2Tests.test_shadow_qa_extracts_trace_features
```

Expected:

```text
Ran 1 test
OK
```

---

## Task 3: Implement Backend Trace Runner

**Files:**
- Modify: `optimization/long_term_v2/shadow_mode_qa.py`
- Test: `tests/test_optimization_runtime_adapter.py`

- [ ] **Step 1: Add failing test for temporary env isolation**

Add to `tests/test_optimization_runtime_adapter.py`:

```python
def test_shadow_qa_backend_trace_restores_environment(self) -> None:
    from optimization.long_term_v2.shadow_mode_qa import temporary_backend_env

    os.environ["LONG_TERM_BACKEND"] = "canonical"
    with temporary_backend_env({"LONG_TERM_BACKEND": "optimization_v2"}):
        self.assertEqual(os.environ["LONG_TERM_BACKEND"], "optimization_v2")

    self.assertEqual(os.environ["LONG_TERM_BACKEND"], "canonical")
```

Expected before implementation:

```text
ImportError: cannot import name 'temporary_backend_env'
```

- [ ] **Step 2: Implement temporary env context and trace call**

Add to `optimization/long_term_v2/shadow_mode_qa.py`:

```python
@contextmanager
def temporary_backend_env(env: dict[str, str]) -> Iterator[None]:
    keys = {"LONG_TERM_BACKEND", "OPTIMIZATION_V2_RUN_ROOT", "OPTIMIZATION_V2_RUNTIME_ROOT"} | set(env)
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ.pop(key, None)
        for key, value in env.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_backend_trace(
    *,
    query_id: str,
    query: str,
    backend_spec: dict[str, Any],
    max_context_chars: int = 16000,
    retrieval_mode: str = "lexical",
) -> dict[str, Any]:
    started = time.perf_counter()
    with temporary_backend_env(backend_spec.get("env", {})):
        resolver = memory_context.resolve_long_term_runtime_paths()
        try:
            context = memory_context.retrieve_long_term_context(
                query=query,
                api_key="",
                model_name="gemini-2.5-pro",
                max_context_chars=max_context_chars,
                use_llm_planner=False,
                retrieval_mode=retrieval_mode,
            )
            status = "ok"
            error = None
        except Exception as exc:
            context = ""
            status = "error"
            error = {"type": type(exc).__name__, "message": str(exc)}
    elapsed_ms = (time.perf_counter() - started) * 1000
    features = extract_trace_features(context)
    return {
        "query_id": query_id,
        "query": query,
        "backend_name": backend_spec["backend_name"],
        "expected_backend": backend_spec["expected_backend"],
        "resolved_backend": resolver.get("backend"),
        "fallback_reason": resolver.get("fallback_reason"),
        "status": status,
        "error": error,
        "latency_ms": round(elapsed_ms, 3),
        "features": features,
        "context_preview": context[:2400],
    }
```

- [ ] **Step 3: Run env isolation test**

Run:

```powershell
uv run python -m unittest tests.test_optimization_runtime_adapter.MemoryContextBackendTests.test_shadow_qa_backend_trace_restores_environment
```

Expected:

```text
Ran 1 test
OK
```

---

## Task 4: Add Pairwise Trace Comparison

**Files:**
- Modify: `optimization/long_term_v2/shadow_mode_qa.py`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] **Step 1: Add failing test for comparison decision**

Add to `tests/test_optimization_long_term_v2.py`:

```python
def test_shadow_qa_pairwise_comparison_marks_shadow_trace_ready(self) -> None:
    from optimization.long_term_v2.shadow_mode_qa import compare_backend_traces

    canonical = {
        "status": "ok",
        "resolved_backend": "canonical",
        "features": {
            "has_global_topic_map": True,
            "has_l1_evidence_seeds": True,
            "has_l2_evolution_context": False,
            "l1_ids": ["L1-A"],
            "l2_ids": [],
            "l3_ids": [],
            "estimated_context_tokens": 2000,
        },
    }
    shadow = {
        "status": "ok",
        "resolved_backend": "optimization_v2",
        "features": {
            "has_global_topic_map": True,
            "has_l1_evidence_seeds": True,
            "has_l2_evolution_context": True,
            "l1_ids": ["L1-A", "L1-B"],
            "l2_ids": ["L2-topic"],
            "l3_ids": ["L3-family"],
            "estimated_context_tokens": 1800,
        },
    }

    comparison = compare_backend_traces(canonical, shadow)

    self.assertEqual(comparison["decision"], "shadow_trace_ready")
    self.assertEqual(comparison["l1_overlap_count"], 1)
    self.assertGreater(comparison["shadow_l2_count"], 0)
```

Expected before implementation:

```text
ImportError: cannot import name 'compare_backend_traces'
```

- [ ] **Step 2: Implement comparison**

Add:

```python
def compare_backend_traces(canonical: dict[str, Any], shadow: dict[str, Any]) -> dict[str, Any]:
    canonical_features = canonical.get("features", {})
    shadow_features = shadow.get("features", {})
    canonical_l1 = set(canonical_features.get("l1_ids", []))
    shadow_l1 = set(shadow_features.get("l1_ids", []))
    overlap = sorted(canonical_l1 & shadow_l1)
    reason_codes: list[str] = []

    if canonical.get("status") != "ok":
        reason_codes.append("canonical_trace_error")
    if shadow.get("status") != "ok":
        reason_codes.append("shadow_trace_error")
    if shadow.get("resolved_backend") != "optimization_v2":
        reason_codes.append("shadow_backend_not_resolved")
    if not shadow_features.get("has_l1_evidence_seeds"):
        reason_codes.append("shadow_missing_l1_evidence")
    if not shadow_features.get("has_global_topic_map"):
        reason_codes.append("shadow_missing_global_topic_map")
    if not shadow_features.get("has_l2_evolution_context"):
        reason_codes.append("shadow_missing_l2_context")

    decision = "shadow_trace_ready" if not reason_codes else "needs_review"
    return {
        "decision": decision,
        "reason_codes": reason_codes,
        "l1_overlap_count": len(overlap),
        "l1_overlap_ids": overlap,
        "canonical_l1_count": len(canonical_l1),
        "shadow_l1_count": len(shadow_l1),
        "shadow_l2_count": len(set(shadow_features.get("l2_ids", []))),
        "shadow_l3_count": len(set(shadow_features.get("l3_ids", []))),
        "shadow_token_delta_vs_canonical": shadow_features.get("estimated_context_tokens", 0)
        - canonical_features.get("estimated_context_tokens", 0),
    }
```

- [ ] **Step 3: Run comparison test**

Run:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2.OptimizationLongTermV2Tests.test_shadow_qa_pairwise_comparison_marks_shadow_trace_ready
```

Expected:

```text
Ran 1 test
OK
```

---

## Task 5: Implement Full QA Runner And Reports

**Files:**
- Modify: `optimization/long_term_v2/shadow_mode_qa.py`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] **Step 1: Add failing report summary test**

Add:

```python
def test_shadow_qa_summary_decision_requires_all_queries_ready(self) -> None:
    from optimization.long_term_v2.shadow_mode_qa import summarize_shadow_qa

    summary = summarize_shadow_qa(
        query_results=[
            {"comparison": {"decision": "shadow_trace_ready"}},
            {"comparison": {"decision": "needs_review", "reason_codes": ["shadow_missing_l2_context"]}},
        ]
    )

    self.assertEqual(summary["decision"], "needs_review")
    self.assertEqual(summary["query_count"], 2)
    self.assertEqual(summary["shadow_trace_ready_count"], 1)
    self.assertEqual(summary["needs_review_count"], 1)
    self.assertIn("shadow_missing_l2_context", summary["reason_code_counts"])
```

- [ ] **Step 2: Implement query loading, runner, summary, markdown**

Add:

```python
def load_queries(path: Path | str, *, max_queries: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if max_queries is not None:
        rows = rows[:max_queries]
    return rows


def summarize_shadow_qa(query_results: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    ready_count = 0
    for row in query_results:
        comparison = row.get("comparison", {})
        if comparison.get("decision") == "shadow_trace_ready":
            ready_count += 1
        for code in comparison.get("reason_codes", []):
            reason_counts[code] = reason_counts.get(code, 0) + 1
    needs_review = len(query_results) - ready_count
    return {
        "query_count": len(query_results),
        "shadow_trace_ready_count": ready_count,
        "needs_review_count": needs_review,
        "reason_code_counts": reason_counts,
        "decision": "shadow_qa_pass" if needs_review == 0 else "needs_review",
    }
```

Then implement:

```python
def run_shadow_mode_qa(...):
    ...
```

Requirements:

- Create `optimization/runs/<run_id>/contexts/<query_id>/<backend>.txt`.
- Create `optimization/runs/<run_id>/traces/<query_id>.json`.
- Create compact summary under requested `--summary-out`.
- The compact summary must not include full context text.
- It must include:
  - source run root
  - query count
  - decision
  - ready count
  - needs review count
  - average canonical tokens
  - average optimization tokens
  - average latency by backend
  - reason code counts
  - top per-query review items
  - boundary statement.

- [ ] **Step 3: Add CLI**

Expected command:

```powershell
uv run python optimization/long_term_v2/shadow_mode_qa.py `
  --optimization-run-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --out optimization/runs/icsi_bmr_first360_candidate6_shadow_qa_20260610 `
  --summary-out optimization/reports/icsi_bmr_first360_candidate6_shadow_qa `
  --max-queries 12 `
  --max-context-chars 16000 `
  --retrieval-mode lexical
```

- [ ] **Step 4: Run summary unit test**

Run:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2.OptimizationLongTermV2Tests.test_shadow_qa_summary_decision_requires_all_queries_ready
```

Expected:

```text
Ran 1 test
OK
```

---

## Task 6: Add Optional Answer-Quality Shadow Comparison

**Files:**
- Modify: `optimization/long_term_v2/shadow_mode_qa.py`
- Reuse: `optimization/long_term_v2/evaluate_answer_quality.py`
- Reuse: `optimization/long_term_v2/run_icsi_answer_quality_comparison.py`

This task should be optional because it calls Gemini. The trace QA must be useful without answer generation.

- [ ] **Step 1: Add CLI flags**

Add:

```text
--generate-answers
--model gemini-2.5-pro
--judge-model gemini-2.5-pro
--max-answer-queries N
```

- [ ] **Step 2: When `--generate-answers` is absent**

Behavior:

- no Gemini calls.
- report `answer_quality_status=not_run`.
- shadow trace QA still runs.

- [ ] **Step 3: When `--generate-answers` is present**

Behavior:

- Generate answers for canonical and optimization contexts only.
- Use the same answer prompt for both.
- Score each answer using existing answer-quality dimensions:
  - factual_correctness
  - evidence_grounding
  - topic_evolution
  - completeness
  - conciseness
  - hallucination_risk
  - source_traceability
- Write raw answers/scores under ignored `optimization/runs/...`.
- Write compact answer-quality aggregate under `optimization/reports/...`.

- [ ] **Step 4: Acceptance**

For ICSI:

- optimization v2 should beat or match canonical on evidence grounding, traceability, and topic evolution.
- If canonical is worse because of Grace ontology leakage, report that explicitly.

For Grace:

- optimization v2 must not materially underperform canonical.

---

## Task 7: Run ICSI Candidate6 Shadow QA

**Command:**

```powershell
uv run python optimization/long_term_v2/shadow_mode_qa.py `
  --optimization-run-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --out optimization/runs/icsi_bmr_first360_candidate6_shadow_qa_20260610 `
  --summary-out optimization/reports/icsi_bmr_first360_candidate6_shadow_qa `
  --max-queries 12 `
  --max-context-chars 16000 `
  --retrieval-mode lexical
```

Expected:

- Exit 0.
- Summary is written.
- All query traces have `optimization_v2` resolved backend.
- All optimization traces contain:
  - `Global Topic Map`
  - `L1 Evidence Seeds`
  - `L2 / Child-L2 Evolution Context`
- Any canonical ICSI weakness is marked as diagnostic, not a blocker.

---

## Task 8: Run Grace Shadow QA If V2 Run Exists

**Files:**
- Read only:
  - `optimization/runs/`
  - `long_term/eval/long_term_retrieval_queries.jsonl`

- [ ] **Step 1: Discover latest Grace optimization run**

Command:

```powershell
Get-ChildItem optimization/runs -Directory |
  Where-Object { $_.Name -match 'grace' -and (Test-Path ($_.FullName + '/runtime/manifest.json')) } |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 5 Name, FullName
```

- [ ] **Step 2: If a valid Grace v2 runtime exists, run QA**

Command shape:

```powershell
uv run python optimization/long_term_v2/shadow_mode_qa.py `
  --optimization-run-root <latest-grace-v2-runtime-run> `
  --queries long_term/eval/long_term_retrieval_queries.jsonl `
  --out optimization/runs/grace_shadow_qa_20260610 `
  --summary-out optimization/reports/grace_shadow_qa_20260610 `
  --max-queries 8 `
  --max-context-chars 16000 `
  --retrieval-mode lexical
```

- [ ] **Step 3: If no valid Grace v2 runtime exists**

Write:

- `optimization/reports/grace_shadow_qa_20260610/summary.md`
- decision: `blocked_missing_grace_v2_runtime`
- not a failure of ICSI candidate6.
- explicit next action: export latest Grace v2 run or build Grace v2 in isolated optimization root.

---

## Task 9: Fallback Stability Tests

**Files:**
- Test: `tests/test_optimization_runtime_adapter.py`

- [ ] **Step 1: Add test for missing optimization runtime fallback in QA**

Add:

```python
def test_shadow_qa_missing_optimization_runtime_reports_fallback(self) -> None:
    from optimization.long_term_v2.shadow_mode_qa import run_backend_trace

    with tempfile.TemporaryDirectory() as temp_dir:
        trace = run_backend_trace(
            query_id="q001",
            query="What is the memory design?",
            backend_spec={
                "backend_name": "optimization_v2",
                "expected_backend": "optimization_v2",
                "env": {
                    "LONG_TERM_BACKEND": "optimization_v2",
                    "OPTIMIZATION_V2_RUN_ROOT": temp_dir,
                },
            },
            max_context_chars=1000,
            retrieval_mode="lexical",
        )

    self.assertEqual(trace["resolved_backend"], "canonical")
    self.assertEqual(trace["fallback_reason"], "optimization_v2_runtime_incomplete")
```

Expected:

- QA traces do not crash when runtime is missing.
- fallback is explicit.

---

## Task 10: Final Verification And Report Review

**Commands:**

```powershell
uv run python -m unittest tests.test_optimization_runtime_adapter
uv run python -m unittest tests.test_optimization_long_term_v2 tests.test_optimization_l2_l3_scaling tests.test_optimization_runtime_adapter tests.test_memory_output_roots
uv run python -m unittest discover -s tests
uv run python -m py_compile optimization/long_term_v2/shadow_mode_qa.py optimization/long_term_v2/shadow_mode_qa_config.py
git diff --check
rg -n "DEFAULT_CHILD|transcript segmentation|idea-unit coverage|topic lifecycle|manager-agent|memory evaluation strategy|L2-transcript|L3-transcript" optimization/long_term_v2 -g "*.py" -g "profiles/**" -g "prompts/**"
git status --short --branch
```

Expected:

- All tests pass.
- No core Grace-hardcoded topic rule added.
- No canonical paths modified.
- Dirty files are limited to:
  - plan
  - QA runner/config
  - compact reports
  - tests.

---

## Decision Rules

### `shadow_qa_pass`

All are true:

- optimization backend resolves to `optimization_v2` for every query.
- optimization traces have Global Topic Map, L1 Evidence Seeds, and L2 Evolution Context.
- no query has backend exception.
- fallback test passes.
- canonical defaults remain canonical.
- answer-quality comparison, if run, is not worse than canonical for the dataset where canonical is a valid baseline.

### `needs_review`

Any are true:

- optimization trace misses L2 context.
- L1 Evidence Seeds missing.
- backend falls back unexpectedly.
- context is too short to include useful evidence.
- answer quality is worse on Grace.
- ICSI trace shows suspicious topic labels that need manual review.

### `blocked`

Any are true:

- optimization runtime export missing.
- query file missing.
- existing app resolver cannot select optimization runtime.
- canonical files are dirty before the run.

---

## Manual Review Checklist

For each shadow QA report, manually inspect:

1. Three highest-risk queries:
   - data quality
   - data collection evolution
   - corpus design evidence
2. For each:
   - optimization L1 seeds are concrete ICSI BMR evidence.
   - L2/L3 topic labels are not Grace memory-system labels.
   - canonical trace weakness, if any, is reported as legacy diagnostic.
   - optimization context is not just a huge dump.
3. For fallback:
   - missing v2 runtime falls back to canonical.
   - fallback reason is visible.
4. For promotion boundary:
   - report says `shadow`, not `promoted`.
   - `.env` remains untouched.

---

## Acceptance Criteria

This plan is complete when:

- `optimization/long_term_v2/shadow_mode_qa.py` exists and is tested.
- ICSI candidate6 shadow QA report exists under `optimization/reports/`.
- Report clearly separates:
  - canonical baseline behavior
  - optimization shadow behavior
  - fallback behavior
  - promotion boundary.
- `uv run python -m unittest discover -s tests` passes.
- `git status --short --branch` shows no canonical generated artifact diffs.
- If pushed, commit message should be:

```text
Add optimization shadow mode QA
```

## What This Still Does Not Prove

Even after this plan passes:

- optimization v2 is not automatically canonical runtime.
- ICSI first360 success does not prove all ICSI full transcripts are solved.
- It does not prove arbitrary dataset generality.
- It only proves the candidate is ready for controlled shadow-mode QA and comparison.
