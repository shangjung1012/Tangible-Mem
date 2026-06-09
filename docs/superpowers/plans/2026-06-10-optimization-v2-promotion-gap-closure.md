# Optimization V2 Promotion Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining gaps between optimization v2 shadow-mode readiness and a defensible promotion decision, while keeping canonical `share_mem/` and `long_term/` unchanged until an explicit promotion step is approved.

**Architecture:** Treat promotion as a sequence of evidence gates, not a single switch. Add isolated QA tools and reports under `optimization/`, compare canonical and optimization v2 through the same runtime entrypoints, improve ICSI labels through sidecar-reviewed proposals, validate longer ICSI transcript slices, then produce a final promotion decision report with rollback instructions. Runtime default remains canonical until the final gate is explicitly accepted.

**Tech Stack:** Python, unittest, existing `app.memory_context`, existing optimization v2 runtime export, Gemini-backed answer scoring when explicitly requested, JSON/Markdown reports, PowerShell commands.

---

## Current State

The current state is strong enough for shadow-mode delivery:

- ICSI candidate6 shadow QA:
  - report: `optimization/reports/icsi_bmr_first360_candidate6_shadow_qa/summary.md`
  - decision: `shadow_qa_pass`
  - query count: `12`
  - shadow trace ready: `12`
  - needs review: `0`
  - optimization v2 avg context tokens: `3410.1667`
- Grace shadow QA:
  - report: `optimization/reports/grace_shadow_qa_20260610/summary.md`
  - decision: `shadow_qa_pass`
  - query count: `8`
  - shadow trace ready: `8`
  - needs review: `0`
  - optimization v2 avg context tokens: `8467.5`
- ICSI answer-quality available-baseline comparison:
  - report: `optimization/reports/icsi_bmr_first360_candidate6_full_answer_quality/summary.md`
  - optimization v2 overall: `0.7714`
  - full context overall: `0.5417`
  - RAG overall: `0.6155`

Remaining promotion gaps:

1. Canonical-vs-optimization answer-quality comparison is missing.
2. ICSI validation is still mostly first360, not longer/full transcript behavior.
3. ICSI L2/L3 label polish is incomplete.
4. Grace regression has trace QA but not canonical-vs-optimization answer scoring.
5. Runtime switch and rollback are not yet implemented as a safe config-only path.
6. No final promotion decision report aggregates all gates into one source of truth.

Promotion is blocked until those gaps are closed.

---

## Non-Negotiable Boundaries

- Do not edit `.env`.
- Do not mutate canonical `share_mem/tree.json`.
- Do not mutate canonical `share_mem/meetings/*`.
- Do not mutate canonical `long_term/l2/*`.
- Do not mutate canonical `long_term/l3/*`.
- Do not claim optimization v2 is default runtime until the promotion report says `promotion_candidate`.
- All new generated outputs go under:
  - `optimization/runs/`
  - `optimization/reports/`
  - `memory_outputs/` for dataset-scale L1/L2/L3 runs.
- Raw answer/context artifacts stay in ignored run directories; only compact summaries are tracked.

---

## Gate Overview

### Gate A: Canonical vs Optimization Answer Quality

Purpose: prove optimization v2 does not merely retrieve formatted context, but answers at least as well as canonical on supported queries.

Required datasets:

- Grace:
  - canonical is valid production baseline.
  - optimization v2 must not regress.
- ICSI:
  - canonical is diagnostic only because it may carry Grace ontology leakage.
  - optimization v2 should outperform or clearly justify differences.

Pass criteria:

- Grace:
  - optimization overall score >= canonical overall score - `0.03`
  - optimization source traceability >= canonical
  - optimization hallucination risk <= canonical + `0.03`
- ICSI:
  - optimization evidence grounding >= canonical
  - optimization topic evolution >= canonical
  - any canonical failure caused by domain leakage is reported as diagnostic.

### Gate B: Longer ICSI Validation

Purpose: prove first360 does not hide scaling failure.

Required runs:

- first360 current candidate6 report remains baseline.
- run at least one longer slice:
  - first720 or first1080 for the same BMR effective set, if L1 outputs exist.
  - if longer effective L1 does not exist, create a blocked report explaining the missing input and exact next command.

Pass criteria:

- L2 severe issue count = 0.
- L3 severe issue count = 0.
- no generic Grace memory-system topic leakage.
- active L2 warning count stays explainable.
- prompt trace contains L1 + L2/L3 context for sample queries.

### Gate C: Label Polish

Purpose: fix weak ICSI labels without hardcoding BMR-specific keyword rules.

Known weak labels:

- `had non native`
- `data per`
- `collection protocol require`
- other child labels that are ungrammatical or artifact-like.

Pass criteria:

- label proposals are sidecar-only.
- every accepted label cites representative L1 ids.
- labels are not type-like.
- labels are not generic-only.
- labels are not Grace project ontology unless evidence supports them.
- retrieval trace metrics do not regress.

### Gate D: Runtime Switch And Rollback

Purpose: implement a safe way to run optimization v2 as runtime without deleting old canonical files.

Pass criteria:

- default remains canonical unless explicitly configured.
- optimization can be enabled with environment/config flags.
- missing/incomplete optimization runtime falls back to canonical.
- rollback is one config change.
- docs show exactly how to enable, verify, and rollback.

### Gate E: Final Promotion Decision

Purpose: aggregate all evidence into one reviewer-readable decision.

Possible decisions:

- `do_not_promote`
- `shadow_ready`
- `promotion_candidate`
- `promoted_by_user_approval`

Pass criteria for `promotion_candidate`:

- Gate A pass.
- Gate B pass or blocked with user-accepted scope boundary.
- Gate C pass for currently known weak labels.
- Gate D pass.
- full test suite pass.
- hardcode scan pass.
- secret scan pass.
- no canonical mutation.

---

## File Structure

Create:

- `optimization/long_term_v2/shadow_answer_quality.py`
  - canonical vs optimization answer generation/scoring from shadow traces.
  - no answer generation unless `--generate-answers` is set.

- `optimization/long_term_v2/promotion_gate_report.py`
  - reads Gate A/B/C/D summaries and writes final decision.

- `optimization/long_term_v2/label_polish_review.py`
  - detects weak labels and produces sidecar label review queue.

- `optimization/reports/grace_shadow_answer_quality_20260610/summary.json`
- `optimization/reports/grace_shadow_answer_quality_20260610/summary.md`

- `optimization/reports/icsi_shadow_answer_quality_20260610/summary.json`
- `optimization/reports/icsi_shadow_answer_quality_20260610/summary.md`

- `optimization/reports/icsi_candidate6_label_polish/summary.json`
- `optimization/reports/icsi_candidate6_label_polish/summary.md`

- `optimization/reports/optimization_v2_promotion_decision_20260610/summary.json`
- `optimization/reports/optimization_v2_promotion_decision_20260610/summary.md`

Modify:

- `tests/test_optimization_long_term_v2.py`
  - add answer-quality summary gate tests.
  - add label polish sidecar tests.
  - add promotion report aggregation tests.

- `tests/test_optimization_runtime_adapter.py`
  - add runtime switch/rollback documentation and fallback tests if needed.

Do not modify:

- `.env`
- `share_mem/`
- `long_term/l2`
- `long_term/l3`

---

## Task 1: Canonical vs Optimization Answer Quality Runner

**Files:**
- Create: `optimization/long_term_v2/shadow_answer_quality.py`
- Test: `tests/test_optimization_long_term_v2.py`

- [x] **Step 1: Add failing test for answer-quality aggregate**

Add this test:

```python
def test_shadow_answer_quality_summary_compares_canonical_and_optimization(self) -> None:
    from optimization.long_term_v2.shadow_answer_quality import summarize_shadow_answer_quality

    rows = [
        {
            "query_id": "q001",
            "backend": "canonical",
            "overall_score": 0.70,
            "dimensions": {"source_traceability": 0.8, "hallucination_risk": 0.1},
        },
        {
            "query_id": "q001",
            "backend": "optimization_v2",
            "overall_score": 0.75,
            "dimensions": {"source_traceability": 1.0, "hallucination_risk": 0.0},
        },
    ]

    summary = summarize_shadow_answer_quality(rows, canonical_is_gold_baseline=True)

    self.assertEqual(summary["query_count"], 1)
    self.assertEqual(summary["decision"], "answer_quality_pass")
    self.assertGreater(summary["overall_delta"]["optimization_minus_canonical"], 0)
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'optimization.long_term_v2.shadow_answer_quality'
```

- [x] **Step 2: Implement aggregate function**

Create `optimization/long_term_v2/shadow_answer_quality.py` with:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from optimization.long_term_v2.io_utils import utc_now_iso, write_json, write_text


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def summarize_shadow_answer_quality(
    rows: list[dict[str, Any]],
    *,
    canonical_is_gold_baseline: bool,
    allowed_grace_regression: float = 0.03,
) -> dict[str, Any]:
    canonical = [row for row in rows if row.get("backend") == "canonical"]
    optimization = [row for row in rows if row.get("backend") == "optimization_v2"]
    canonical_overall = _avg([float(row.get("overall_score", 0)) for row in canonical])
    optimization_overall = _avg([float(row.get("overall_score", 0)) for row in optimization])
    delta = round(optimization_overall - canonical_overall, 4)
    if canonical_is_gold_baseline:
        decision = "answer_quality_pass" if delta >= -allowed_grace_regression else "answer_quality_regression"
    else:
        decision = "diagnostic_available"
    return {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "query_count": len({row.get("query_id") for row in rows}),
        "canonical_is_gold_baseline": canonical_is_gold_baseline,
        "average_overall": {
            "canonical": canonical_overall,
            "optimization_v2": optimization_overall,
        },
        "overall_delta": {"optimization_minus_canonical": delta},
        "decision": decision,
    }
```

- [x] **Step 3: Add no-LLM report mode**

The CLI must accept:

```powershell
uv run python optimization/long_term_v2/shadow_answer_quality.py `
  --shadow-qa-report optimization/reports/grace_shadow_qa_20260610/summary.json `
  --out optimization/reports/grace_shadow_answer_quality_20260610 `
  --canonical-is-gold-baseline `
  --no-llm
```

When `--no-llm` is used:

- do not call Gemini.
- write `decision=blocked_answer_generation_not_run`.
- still write a report showing which contexts are available.

- [x] **Step 4: Add generated-answer mode**

When `--generate-answers` is used:

- read context paths from shadow QA summary.
- generate canonical and optimization answers with same prompt.
- score both answers with the existing answer-quality rubric.
- write raw rows under ignored run output.
- write compact summary under `optimization/reports/...`.

Implementation can reuse scoring logic from:

- `optimization/long_term_v2/run_icsi_answer_quality_comparison.py`
- `optimization/long_term_v2/evaluate_answer_quality.py`

- [x] **Step 5: Run tests**

Run:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2.OptimizationLongTermV2Tests.test_shadow_answer_quality_summary_compares_canonical_and_optimization
```

Expected:

```text
Ran 1 test
OK
```

---

## Task 2: Run Grace Canonical-vs-Optimization Answer Quality

**Files:**
- Output: `optimization/runs/grace_shadow_answer_quality_20260610/`
- Output: `optimization/reports/grace_shadow_answer_quality_20260610/`

- [x] **Step 1: Run no-LLM dry report**

```powershell
uv run python optimization/long_term_v2/shadow_answer_quality.py `
  --shadow-qa-report optimization/reports/grace_shadow_qa_20260610/summary.json `
  --out optimization/reports/grace_shadow_answer_quality_20260610 `
  --canonical-is-gold-baseline `
  --no-llm
```

Expected:

- report exists.
- no API calls.
- decision is `blocked_answer_generation_not_run`.

- [x] **Step 2: Run generated answer comparison**

```powershell
uv run python optimization/long_term_v2/shadow_answer_quality.py `
  --shadow-qa-report optimization/reports/grace_shadow_qa_20260610/summary.json `
  --out optimization/reports/grace_shadow_answer_quality_20260610 `
  --raw-out optimization/runs/grace_shadow_answer_quality_20260610 `
  --canonical-is-gold-baseline `
  --generate-answers `
  --model gemini-2.5-pro `
  --judge-model gemini-2.5-pro `
  --retry-wait-seconds 45 `
  --max-attempts 5
```

Expected:

- report exists.
- `query_count=8`.
- decision is `answer_quality_pass` or `answer_quality_regression`.
- if regression, do not promote.

---

## Task 3: Run ICSI Canonical-vs-Optimization Diagnostic Answer Quality

**Files:**
- Output: `optimization/runs/icsi_shadow_answer_quality_20260610/`
- Output: `optimization/reports/icsi_shadow_answer_quality_20260610/`

- [x] **Step 1: Run ICSI generated answer diagnostic**

```powershell
uv run python optimization/long_term_v2/shadow_answer_quality.py `
  --shadow-qa-report optimization/reports/icsi_bmr_first360_candidate6_shadow_qa/summary.json `
  --out optimization/reports/icsi_shadow_answer_quality_20260610 `
  --raw-out optimization/runs/icsi_shadow_answer_quality_20260610 `
  --diagnostic-canonical-baseline `
  --generate-answers `
  --model gemini-2.5-pro `
  --judge-model gemini-2.5-pro `
  --retry-wait-seconds 45 `
  --max-attempts 5
```

Expected:

- report exists.
- `query_count=12`.
- decision is `diagnostic_available`.
- report explicitly says canonical is not a gold ICSI baseline.

- [x] **Step 2: Manual review top three ICSI answers**

Review:

- data quality
- data collection evolution
- corpus design evidence

For each:

- optimization answer cites ICSI evidence.
- optimization answer uses L2/L3 context only as evolution/navigation, not unsupported fact.
- canonical answer issues are recorded as diagnostic if they arise from Grace ontology.

---

## Task 4: Longer ICSI Validation

**Files:**
- Create if needed: `optimization/long_term_v2/validate_longer_icsi_scope.py`
- Output: `optimization/reports/icsi_longer_scope_readiness_20260610/`

- [x] **Step 1: Discover longer ICSI effective roots**

Run:

```powershell
Get-ChildItem memory_outputs/icsi -Recurse -Directory |
  Where-Object { $_.Name -in @('share_mem_effective','filtered_share_mem') } |
  Sort-Object FullName |
  Select-Object FullName
```

Expected:

- list available effective roots.
- identify whether first720/full effective root exists.

- [x] **Step 2: If longer root exists, run optimization v2**

Command shape:

```powershell
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root <longer-effective-root> `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --out optimization/runs/icsi_bmr_longer_candidate_20260610 `
  --mode deterministic `
  --clean
```

Then:

```powershell
uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/icsi_bmr_longer_candidate_20260610
```

Expected:

- severe = 0.
- warnings are explainable.
- no Grace-only memory-system topic leakage.

- [x] **Step 3: If longer root is absent, write blocked report**

Create:

- `optimization/reports/icsi_longer_scope_readiness_20260610/summary.md`
- `optimization/reports/icsi_longer_scope_readiness_20260610/summary.json`

Required fields:

- decision: `blocked_missing_longer_icsi_effective_root`
- available roots
- exact next command to produce longer effective L1.
- statement that this blocks full promotion, but not current first360 shadow delivery.

---

## Task 5: ICSI Label Polish Sidecar

**Files:**
- Create: `optimization/long_term_v2/label_polish_review.py`
- Test: `tests/test_optimization_long_term_v2.py`
- Output: `optimization/reports/icsi_candidate6_label_polish/`

- [x] **Step 1: Add failing test for weak label detection**

Add:

```python
def test_label_polish_review_flags_artifact_like_child_labels(self) -> None:
    from optimization.long_term_v2.label_polish_review import find_weak_topic_labels

    l2_view = {
        "l2_nodes": [
            {"l2_id": "L2-good", "label": "audio data quality", "linked_obj_ids": ["L1-A"]},
            {"l2_id": "L2-bad", "label": "had non native", "linked_obj_ids": ["L1-B"]},
        ]
    }

    review = find_weak_topic_labels(l2_view)

    self.assertEqual(review["weak_label_count"], 1)
    self.assertEqual(review["weak_labels"][0]["l2_id"], "L2-bad")
    self.assertIn("artifact_like_phrase", review["weak_labels"][0]["reason_codes"])
```

- [x] **Step 2: Implement generic label quality checks**

Rules must be generic, not BMR-specific:

- label has fewer than 2 meaningful tokens -> review.
- label starts with auxiliary-like weak verb:
  - `had`
  - `have`
  - `was`
  - `were`
  - `is`
  - `are`
  - `do`
  - `does`
  - `did`
- label ends with weak preposition/determiner:
  - `of`
  - `for`
  - `to`
  - `per`
  - `the`
  - `a`
  - `an`
- label contains only generic words:
  - `data`
  - `system`
  - `process`
  - `topic`
  - `meeting`
  - `discussion`
- label has no representative L1 ids -> review.

Do not add hardcoded BMR labels.

- [x] **Step 3: Produce candidate6 label polish report**

Command:

```powershell
uv run python optimization/long_term_v2/label_polish_review.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --out optimization/reports/icsi_candidate6_label_polish
```

Expected:

- weak labels are listed.
- proposed action is `review_label`, not auto-rewrite.
- accepted labels are not applied automatically.

- [x] **Step 4: Manual review and optional LLM label proposal**

If weak labels are few:

- write `review_decisions.jsonl`.
- proposed labels must cite representative L1 ids.

If weak labels are many:

- run LLM label proposal in sidecar mode only.
- validate proposals before applying.

---

## Task 6: Runtime Switch And Rollback Design

**Files:**
- Create: `optimization/reports/runtime_switch_design_20260610.md`
- Modify if approved later: `README.md`, `long_term/README.md`, or app docs.

- [x] **Step 1: Write switch design**

Document:

```text
Default:
  LONG_TERM_BACKEND unset -> canonical.

Enable optimization v2:
  LONG_TERM_BACKEND=optimization_v2
  OPTIMIZATION_V2_RUN_ROOT=optimization/runs/<approved-run>

Rollback:
  remove LONG_TERM_BACKEND and OPTIMIZATION_V2_RUN_ROOT.

Fallback:
  if runtime export is incomplete, app resolver returns canonical with fallback_reason.
```

- [x] **Step 2: Add smoke commands**

Document:

```powershell
uv run python optimization/long_term_v2/shadow_runtime_readiness.py `
  --run-root <approved-run> `
  --queries <query-file> `
  --out optimization/reports/<approved-run>_runtime_readiness
```

and:

```powershell
uv run python optimization/long_term_v2/shadow_mode_qa.py `
  --optimization-run-root <approved-run> `
  --queries <query-file> `
  --out optimization/runs/<approved-run>_shadow_qa `
  --summary-out optimization/reports/<approved-run>_shadow_qa
```

- [x] **Step 3: Do not edit `.env`**

This task only writes docs/report. Actual `.env` switch requires user approval.

---

## Task 7: Promotion Decision Aggregator

**Files:**
- Create: `optimization/long_term_v2/promotion_gate_report.py`
- Test: `tests/test_optimization_long_term_v2.py`
- Output: `optimization/reports/optimization_v2_promotion_decision_20260610/`

- [x] **Step 1: Add failing test for promotion decision**

Add:

```python
def test_promotion_gate_report_blocks_when_answer_quality_missing(self) -> None:
    from optimization.long_term_v2.promotion_gate_report import decide_promotion_status

    status = decide_promotion_status(
        {
            "shadow_qa": {"decision": "shadow_qa_pass"},
            "answer_quality": {"decision": "blocked_answer_generation_not_run"},
            "runtime_switch": {"decision": "documented"},
            "label_polish": {"decision": "label_review_pass"},
        }
    )

    self.assertEqual(status["decision"], "shadow_ready")
    self.assertIn("answer_quality_not_passed", status["blocking_reasons"])
```

- [x] **Step 2: Implement decision logic**

Rules:

- `do_not_promote` if shadow QA fails.
- `shadow_ready` if shadow QA passes but any promotion gate is missing.
- `promotion_candidate` if all gates pass.
- `promoted_by_user_approval` only if a report explicitly has `user_approved_promotion=true`.

- [x] **Step 3: Generate final report**

Command:

```powershell
uv run python optimization/long_term_v2/promotion_gate_report.py `
  --icsi-shadow-qa optimization/reports/icsi_bmr_first360_candidate6_shadow_qa/summary.json `
  --grace-shadow-qa optimization/reports/grace_shadow_qa_20260610/summary.json `
  --icsi-answer-quality optimization/reports/icsi_shadow_answer_quality_20260610/summary.json `
  --grace-answer-quality optimization/reports/grace_shadow_answer_quality_20260610/summary.json `
  --label-polish optimization/reports/icsi_candidate6_label_polish/summary.json `
  --runtime-switch-design optimization/reports/runtime_switch_design_20260610.md `
  --out optimization/reports/optimization_v2_promotion_decision_20260610
```

Expected:

- decision is not `promotion_candidate` until all inputs exist and pass.
- report lists missing gates clearly.

---

## Task 8: Final Verification

Run:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2 tests.test_optimization_runtime_adapter
uv run python -m unittest tests.test_optimization_long_term_v2 tests.test_optimization_l2_l3_scaling tests.test_optimization_runtime_adapter tests.test_memory_output_roots
uv run python -m unittest discover -s tests
uv run python -m py_compile `
  optimization/long_term_v2/shadow_answer_quality.py `
  optimization/long_term_v2/label_polish_review.py `
  optimization/long_term_v2/promotion_gate_report.py
git diff --check
git status --short --branch
```

Run hardcode scan:

```powershell
rg -n "DEFAULT_CHILD|transcript segmentation|idea-unit coverage|topic lifecycle|manager-agent|memory evaluation strategy|L2-transcript|L3-transcript" optimization/long_term_v2 -g "*.py" -g "profiles/**" -g "prompts/**"
```

Run secret scan using the repo's established scan pattern and exclude known scanner/test dummy files.

Expected:

- tests pass.
- no new Grace-specific hardcoded topic logic.
- no real secrets.
- no canonical generated artifact diffs.

---

## Final Acceptance Criteria

Optimization v2 can be called `promotion_candidate` only if all are true:

- ICSI shadow QA pass.
- Grace shadow QA pass.
- Grace canonical-vs-optimization answer quality pass.
- ICSI canonical-vs-optimization diagnostic answer quality available.
- ICSI longer-scope validation pass or explicitly accepted as out of current delivery scope.
- label polish review pass or accepted weak labels are justified.
- runtime switch/rollback design documented.
- final promotion decision report says `promotion_candidate`.
- full tests pass.
- hardcode scan pass.
- secret scan pass.
- canonical mutation false.

If any are missing:

- status remains `shadow_ready`.
- report must list missing gates.
- runtime default remains canonical.

---

## Recommended Execution Order

1. Task 1: implement answer-quality aggregate.
2. Task 2: run Grace answer quality because it is the strongest promotion gate.
3. Task 3: run ICSI diagnostic answer quality.
4. Task 5: run label polish review.
5. Task 4: check longer ICSI input availability.
6. Task 6: write runtime switch/rollback design.
7. Task 7: generate promotion decision.
8. Task 8: full verification.

This order prevents code churn: if Grace answer quality regresses, promotion stays blocked and runtime switch work remains documentation-only.


---

## Execution Notes 2026-06-10

Executed in this workspace without modifying canonical `.env`, `share_mem/`, `long_term/l2`, or `long_term/l3`.

Completed outputs:

- `optimization/long_term_v2/shadow_answer_quality.py`
- `optimization/long_term_v2/label_polish_review.py`
- `optimization/long_term_v2/promotion_gate_report.py`
- `optimization/reports/grace_shadow_answer_quality_20260610/summary.json`
- `optimization/reports/icsi_shadow_answer_quality_20260610/summary.json`
- `optimization/reports/icsi_shadow_answer_quality_20260610/manual_review_top3.md`
- `optimization/reports/icsi_longer_scope_readiness_20260610/summary.json`
- `optimization/reports/icsi_candidate6_label_polish/summary.json`
- `optimization/reports/runtime_switch_design_20260610.md`
- `optimization/reports/optimization_v2_promotion_decision_20260610/summary.json`

Important outcomes:

- Grace canonical-vs-optimization answer quality: `answer_quality_pass`.
- ICSI diagnostic answer quality: `answer_quality_needs_review`; optimization v2 overall is higher, but topic evolution is lower than diagnostic canonical on aggregate.
- Longer ICSI validation: `blocked_missing_input`; no first720/first1080/full effective root was found.
- Label polish: `label_polish_review_needed`; weak labels are listed as sidecar review items only.
- Final promotion gate: `do_not_promote`; remaining blockers are answer-quality review and longer ICSI scope input.

Verification:

- `uv run python -m unittest tests.test_optimization_long_term_v2`: pass.
- `uv run python -m unittest discover -s tests`: pass, 647 tests.
- `uv run python -m py_compile optimization/long_term_v2/shadow_answer_quality.py optimization/long_term_v2/label_polish_review.py optimization/long_term_v2/promotion_gate_report.py`: pass.
- core hardcode scan over `.py` / `.yaml`: no matches.
- secret scan over `optimization` and tests: no matches.
