# Optimization v2 Promotion Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn optimization v2 from a strong isolated experiment into a promotion-ready shadow runtime candidate without mutating canonical `share_mem/` or `long_term/`.

**Architecture:** All fixes remain sidecar-first under `optimization/` or isolated `memory_outputs/`. The plan converts current review warnings into explicit relabel/split/reassignment candidates, validates them side-by-side, then runs retrieval and answer-quality gates before any runtime shadow-mode discussion.

**Tech Stack:** Python, unittest, JSON/JSONL sidecars, optimization v2 L2/L3 artifacts, ICSI effective share_mem, existing Memory Observatory experiment tooling.

---

## Current State

The latest ICSI active L2 agent spot-check is usable but not final:

- `25` reviewed items.
- `0` severe issues.
- `10` warning issues.
- Key warning classes:
  - `needs_l3_split`: `L2-annotation-tool`, `L2-data-collection`.
  - `needs_label_review`: `L2-participant-consent`, `L2-ti-digit`.
  - `too_broad_watch`: `L2-data-quality`, `L2-analysis-methodology`, `L2-data-analysis`.
  - `needs_manual_decision`: `L2-meeting-agenda`, `L2-annotation-process`, `L2-system-performance`.

The right next step is not to hardcode BMR-specific fixes. The next step is to create candidate sidecars, validate them, and compare them against the current candidate4 baseline.

## Files To Create Or Modify

- Create: `optimization/long_term_v2/propose_topic_label_refinements.py`
  - Reads active review decisions and proposes sidecar-only label refinements.
- Create: `optimization/long_term_v2/propose_active_l2_splits.py`
  - Generates focused L3/split review candidates for warning topics.
- Create: `optimization/long_term_v2/apply_topic_review_candidates.py`
  - Applies accepted relabel/split candidates into an isolated candidate run.
- Create: `optimization/long_term_v2/compare_effective_topic_runs.py`
  - Compares baseline candidate4 vs refined candidate outputs.
- Create: `optimization/long_term_v2/evaluate_icsi_answer_quality.py`
  - Runs ICSI answer-quality comparison across full context, RAG, current optimization v2, and refined optimization v2.
- Modify: `tests/test_optimization_long_term_v2.py`
  - Unit tests for relabel candidates, split proposal schema, candidate application, and ICSI answer-quality report schema.
- Modify: `tests/test_optimization_l2_l3_scaling.py`
  - Tests for split candidate exact assignment and no raw L1 mutation.
- Create generated outputs under:
  - `optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_<timestamp>/`
  - `optimization/reports/icsi_bmr_first360_candidate5_comparison/`

## Promotion Boundary

This plan must not:

- Modify `share_mem/tree.json`.
- Modify `share_mem/meetings/*`.
- Modify canonical `long_term/l2/*`.
- Modify canonical `long_term/l3/*`.
- Use Grace-specific or BMR-specific hardcoded ontology rules.
- Treat agent spot-check decisions as final human review.

## Task 1: Freeze Baseline Evidence

**Files:**
- Read: `optimization/reports/icsi_bmr_first360_active_l2_agent_review/active_l2_review_decisions_summary.json`
- Read: `optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4/`
- Create: `optimization/reports/icsi_bmr_first360_candidate4_baseline_freeze.json`

- [ ] **Step 1: Write a baseline freeze script test**

Add a test that checks a freeze report records:

```python
def test_baseline_freeze_records_review_warning_counts(self) -> None:
    report = {
        "status": "warning",
        "decision_count": 25,
        "warning_issue_count": 10,
        "severe_issue_count": 0,
        "by_decision": {"needs_l3_split": 2},
    }
    self.assertEqual(report["severe_issue_count"], 0)
    self.assertEqual(report["by_decision"]["needs_l3_split"], 2)
```

- [ ] **Step 2: Generate the freeze report**

Command:

```powershell
uv run python - <<'PY'
import json
from pathlib import Path
src = Path("optimization/reports/icsi_bmr_first360_active_l2_agent_review/active_l2_review_decisions_summary.json")
dst = Path("optimization/reports/icsi_bmr_first360_candidate4_baseline_freeze.json")
payload = json.loads(src.read_text(encoding="utf-8-sig"))
dst.write_text(json.dumps({
  "schema_version": 1,
  "baseline_run_root": "optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4",
  "source_review_summary": str(src),
  "status": payload["status"],
  "decision_count": payload["decision_count"],
  "warning_issue_count": payload["warning_issue_count"],
  "severe_issue_count": payload["severe_issue_count"],
  "by_decision": payload["by_decision"],
}, ensure_ascii=False, indent=2), encoding="utf-8")
PY
```

Expected:

- `severe_issue_count = 0`
- `warning_issue_count = 10`

## Task 2: Label Refinement Candidate Sidecar

**Files:**
- Create: `optimization/long_term_v2/propose_topic_label_refinements.py`
- Test: `tests/test_optimization_long_term_v2.py`

Target warnings:

- `L2-participant-consent` -> candidate label like `participant background metadata`
- `L2-ti-digit` -> candidate label like `TI-digits benchmark comparison`

Rules:

- Proposals are sidecar-only.
- A proposal must cite representative L1 ids.
- A proposal must not be auto-applied to active L2.
- The candidate label must be evidence-backed and not type-like.

- [ ] **Step 1: Write failing test**

```python
def test_label_refinement_proposals_require_representative_l1(self) -> None:
    from optimization.long_term_v2.propose_topic_label_refinements import propose_label_refinements
    review = {
        "decisions": [
            {
                "item_type": "active_l2",
                "item_id": "L2-ti-digit",
                "decision": "needs_label_review",
                "reason": "Representative L1 concerns TI-digits benchmark.",
            }
        ]
    }
    l2_nodes = {
        "L2-ti-digit": {
            "label": "ti digit",
            "linked_obj_ids": ["L1-A", "L1-B"],
            "timeline_digest": [{"obj_id": "L1-A", "summary": "Compare against TI-digits benchmark."}],
        }
    }
    report = propose_label_refinements(review, l2_nodes)
    self.assertEqual(report["proposal_count"], 1)
    self.assertEqual(report["proposals"][0]["source_l2_id"], "L2-ti-digit")
    self.assertTrue(report["proposals"][0]["representative_l1_ids"])
```

- [ ] **Step 2: Implement deterministic evidence-backed proposal**

The implementation should not contain ICSI-specific keyword rules. It should:

- Read the review reason.
- Read the source L2 label.
- Read representative timeline summaries.
- Produce a candidate using evidence phrases and normalized noun phrases.
- Mark confidence as `review_required`.

- [ ] **Step 3: Generate report**

Command:

```powershell
uv run python optimization/long_term_v2/propose_topic_label_refinements.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --review optimization/reports/icsi_bmr_first360_active_l2_agent_review/active_l2_review_decisions_summary.json `
  --out optimization/reports/icsi_bmr_first360_label_refinement_candidates
```

Expected:

- `proposal_count >= 2`
- no severe validation errors
- no raw L1 mutation

## Task 3: Focused L3 Split Review Candidate

**Files:**
- Create: `optimization/long_term_v2/propose_active_l2_splits.py`
- Test: `tests/test_optimization_l2_l3_scaling.py`

Target warnings:

- `L2-annotation-tool`
- `L2-data-collection`

Rules:

- Use existing semantic keys, timeline summaries, meeting spread, and L1 content.
- Do not hardcode child labels.
- Candidate children must be mutually distinguishable by evidence.
- If separability is weak, output `review_only`, not materialized split.

- [ ] **Step 1: Write failing split schema test**

```python
def test_active_l2_split_candidate_requires_evidence_backed_children(self) -> None:
    from optimization.long_term_v2.propose_active_l2_splits import propose_active_l2_splits
    node = {
        "l2_id": "L2-large",
        "label": "data collection",
        "linked_obj_ids": ["L1-A", "L1-B", "L1-C"],
        "timeline_digest": [
            {"obj_id": "L1-A", "summary": "Collect digit reading data."},
            {"obj_id": "L1-B", "summary": "Define corpus distribution rationale."},
            {"obj_id": "L1-C", "summary": "Discuss recording logistics."},
        ],
    }
    report = propose_active_l2_splits({"L2-large": node}, target_l2_ids=["L2-large"])
    self.assertIn("split_candidates", report)
    self.assertTrue(report["split_candidates"] or report["review_only"])
```

- [ ] **Step 2: Implement generic clustering-based proposal**

Use:

- semantic terms from `semantic_keys/semantic_key_index.json`
- timeline summaries
- object meeting spread
- lexical clustering by shared non-stopword terms

Do not use dataset-specific terms such as `BMR`, `TI-digits`, or `annotation tool` as hardcoded rules.

- [ ] **Step 3: Generate split candidate report**

Command:

```powershell
uv run python optimization/long_term_v2/propose_active_l2_splits.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --review optimization/reports/icsi_bmr_first360_active_l2_agent_review/active_l2_review_decisions_summary.json `
  --out optimization/reports/icsi_bmr_first360_active_l2_split_candidates
```

Expected:

- `L2-annotation-tool` either has a split candidate or explicit `review_only`.
- `L2-data-collection` either has a split candidate or explicit `review_only`.
- every child candidate has representative L1 ids.

## Task 4: Apply Candidates To Isolated Candidate5 Run

**Files:**
- Create: `optimization/long_term_v2/apply_topic_review_candidates.py`
- Test: `tests/test_optimization_l2_l3_scaling.py`

Rules:

- Candidate5 must be written under `optimization/runs/`.
- It must copy candidate4 inputs and sidecars.
- It must not mutate candidate4.
- It must not mutate canonical.
- It may materialize only candidates that pass validation.

- [ ] **Step 1: Write failing isolation test**

```python
def test_apply_topic_review_candidates_writes_only_candidate_run(self) -> None:
    from optimization.long_term_v2.apply_topic_review_candidates import apply_topic_review_candidates
    result = apply_topic_review_candidates(
        source_run_root=Path("source"),
        label_candidates={"proposals": []},
        split_candidates={"split_candidates": []},
        out_root=Path("optimization/runs/candidate"),
    )
    self.assertIn("candidate_run_root", result)
```

- [ ] **Step 2: Implement minimal candidate application**

Candidate application should:

- Write `candidate_manifest.json`.
- Write `applied_label_refinements.json`.
- Write `applied_split_candidates.json`.
- Produce candidate L2/L3 views only if assignments validate.

- [ ] **Step 3: Run candidate application**

Command:

```powershell
uv run python optimization/long_term_v2/apply_topic_review_candidates.py `
  --source-run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --label-candidates optimization/reports/icsi_bmr_first360_label_refinement_candidates/label_refinement_candidates.json `
  --split-candidates optimization/reports/icsi_bmr_first360_active_l2_split_candidates/active_l2_split_candidates.json `
  --out optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609
```

Expected:

- Candidate5 exists.
- Candidate4 remains unchanged.
- canonical remains unchanged.

## Task 5: Validate Candidate5

**Files:**
- Existing: `optimization/long_term_v2/validate_view.py`
- Existing: `optimization/long_term_v2/evaluate_retrieval.py`
- Create: `optimization/reports/icsi_bmr_first360_candidate5_comparison/`

- [ ] **Step 1: Run validation**

```powershell
uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609
```

Expected:

- severe issues: `0`
- high-importance linked rate not worse than candidate4

- [ ] **Step 2: Run ICSI retrieval eval**

```powershell
uv run python optimization/long_term_v2/evaluate_retrieval.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609 `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --out optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609/retrieval_eval_icsi_effective
```

Expected gates:

- average expected L1 recall >= candidate4.
- semantic L2 hit >= candidate4.
- semantic L3 hit >= candidate4.
- context size does not explode.

## Task 6: Compare Candidate4 vs Candidate5

**Files:**
- Create: `optimization/long_term_v2/compare_effective_topic_runs.py`
- Create: `optimization/reports/icsi_bmr_first360_candidate5_comparison/`

- [ ] **Step 1: Write comparison script**

The report must compare:

- active L2 count
- suppressed L2 count
- L3 parent count
- high-importance linked rate
- retrieval metrics
- warning/severe counts
- changed labels
- split source L2 ids
- new child L2 counts

- [ ] **Step 2: Run comparison**

```powershell
uv run python optimization/long_term_v2/compare_effective_topic_runs.py `
  --baseline optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --candidate optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609 `
  --out optimization/reports/icsi_bmr_first360_candidate5_comparison
```

Expected:

- If candidate5 improves clarity without metric regression, keep it as the next isolated candidate.
- If candidate5 hurts retrieval or over-splits, keep candidate4 and mark candidate5 as rejected.

## Task 7: ICSI Answer Quality Comparison

**Files:**
- Create: `optimization/long_term_v2/evaluate_icsi_answer_quality.py`
- Create: `optimization/reports/icsi_bmr_first360_answer_quality/`

Strategies:

- `full_context`
- `rag_baseline`
- `optimization_v2_candidate4`
- `optimization_v2_candidate5`

Questions:

- Use existing curated ICSI questions.
- Add 3 focused questions:
  - annotation/transcription tooling
  - digit reading / TI-digits benchmark
  - data collection rationale and protocol

Metrics:

- factual correctness
- evidence grounding
- topic evolution
- completeness
- source traceability
- hallucination risk
- context tokens
- latency

- [ ] **Step 1: Run no-LLM retrieval-only answer-quality proxy**

Expected:

- candidate5 must not reduce evidence grounding.
- candidate5 should improve label/source traceability on the relabeled topics.

- [ ] **Step 2: If API budget is available, run LLM answer scoring**

Expected:

- candidate5 score >= candidate4.
- if full context wins on small questions, report honestly.

## Task 8: Runtime Shadow-Mode Readiness

**Files:**
- Existing: `tests/test_optimization_runtime_adapter.py`
- Existing: optimization runtime export tooling.

This task does not switch production runtime. It only verifies that candidate outputs can be loaded in shadow mode.

- [ ] **Step 1: Export candidate5 runtime view**

```powershell
uv run python optimization/long_term_v2/export_runtime_view.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609 `
  --out optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609/runtime_export
```

- [ ] **Step 2: Run runtime adapter tests**

```powershell
uv run python -m unittest tests.test_optimization_runtime_adapter
```

Expected:

- shadow-mode paths resolve.
- missing runtime export falls back safely.
- canonical runtime is not changed.

## Task 9: Final Verification And Promotion Decision

**Files:**
- Create: `optimization/reports/icsi_bmr_first360_promotion_readiness.md`

- [ ] **Step 1: Run targeted tests**

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2 tests.test_optimization_l2_l3_scaling tests.test_optimization_runtime_adapter tests.test_memory_output_roots
```

Expected:

- OK

- [ ] **Step 2: Run full test suite**

```powershell
uv run python -m unittest discover -s tests
```

Expected:

- OK

- [ ] **Step 3: Run scans**

```powershell
rg -n "DEFAULT_CHILD|transcript segmentation|idea-unit coverage|topic lifecycle|manager-agent|memory evaluation strategy|L2-transcript|L3-transcript" optimization/long_term_v2
rg -n "AIza|GOOGLE_APPLICATION_CREDENTIALS|GEMINI_API_KEY|BEGIN PRIVATE KEY|application_default_credentials|C:\\Users\\.*credentials" optimization docs tests -g "!optimization/long_term_v2/maturity_certification.py"
git status --short --branch
```

Expected:

- no new Grace-specific core matches
- no secrets
- no unexpected canonical diff

- [ ] **Step 4: Write promotion decision**

Possible outcomes:

- `candidate5_rejected`: if retrieval or answer quality regresses.
- `candidate5_kept_isolated`: if it improves labels/splits but still needs human review.
- `shadow_ready`: if candidate5 improves or matches candidate4, has 0 severe issues, passes answer quality, and runtime adapter tests pass.

## Acceptance Criteria

Optimization v2 can be called `shadow_ready` only if:

- candidate5 severe issues = `0`
- candidate5 retrieval metrics do not regress from candidate4
- answer quality is not worse than candidate4
- relabeled topics improve clarity without changing raw L1
- split topics improve navigation without over-fragmentation
- no canonical files are modified
- full tests pass
- secret scan passes
- report explicitly states remaining human-review items

Optimization v2 should not be promoted if:

- answer quality regresses
- L2/L3 split creates generic or artificial child topics
- warning count grows without clear benefit
- runtime shadow export is unstable
- any canonical mutation occurs

## Expected Next Decision

After this plan is executed, the likely decision should be one of:

1. Keep candidate4 as current best and document why warnings remain.
2. Adopt candidate5 as better isolated candidate and run one more 30-file verification.
3. Mark optimization v2 as shadow-ready but not canonical replacement.

The plan intentionally avoids a direct canonical replacement decision.
