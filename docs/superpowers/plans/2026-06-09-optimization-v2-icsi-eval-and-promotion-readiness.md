# Optimization v2 ICSI Eval And Promotion Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make optimization v2 measurable on ICSI 30-file outputs, prove effective L2/L3 are used by downstream retrieval/eval, and define the remaining gates before any promotion discussion.

**Architecture:** Keep canonical `share_mem/` and `long_term/` untouched. Treat `memory_outputs/icsi/.../share_mem_effective/` as the ICSI L1 source, optimization v2 runs as isolated generated artifacts, and `topic_review/effective_topic_index.json` as the durable-topic surface for retrieval/eval/runtime export.

**Tech Stack:** Python standard library, `uv run python -m unittest`, existing `optimization/long_term_v2` modules, JSON/JSONL sidecars, markdown reports.

---

## Current Known State

- `main` is clean and in sync with `origin/main`.
- Optimization v2 sidecar support has been pushed:
  - `finalize_topic_review.py`
  - `effective_view.py`
  - downstream readers now use effective topic surface.
- Latest ICSI 30-file effective source:
  - `memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective`
- Latest ICSI 30-file optimization candidate:
  - `optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4`
- Latest effective audit result:
  - raw warnings: `10`
  - suppressed warnings: `10`
  - unresolved warnings: `0`
  - runtime active L2: `134`
  - suppressed L2: `5`
  - suppressed L1: `36`

---

## File Structure

### Create

- `optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl`
  - ICSI-specific retrieval/eval query set with expected L1/L2/L3 semantic labels.

- `optimization/long_term_v2/curate_icsi_eval_queries.py`
  - Builds a first-pass query candidate list from active L2 topics and representative L1.
  - Does not call LLM.
  - Writes JSONL plus a review markdown.

- `optimization/long_term_v2/manual_review_active_l2.py`
  - Generates standardized manual review queues for active L2, suppressed L2, high-importance L1, and random linked L1.

- `optimization/long_term_v2/apply_durable_topic_policy.py`
  - Candidate-only policy pass that marks weak L1/L2 as review-only using profile-level thresholds.
  - Does not mutate raw L2/L3.

- `optimization/long_term_v2/run_regression_matrix.py`
  - Runs Grace, ICSI, synthetic/Locomo-style checks with the same gates after every L2/L3 change.

### Modify

- `optimization/long_term_v2/evaluate_retrieval.py`
  - Add optional `--save-contexts`.
  - Include suppressed-topic metadata per query.

- `optimization/long_term_v2/run_answer_quality_eval.py`
  - Ensure v2 answer-quality contexts include effective surface metadata.
  - Add no-answer retrieval-only mode for ICSI query trace review.

- `optimization/long_term_v2/maturity_certification.py`
  - Add gates for ICSI query eval and active L2 manual review completion.

- `optimization/long_term_v2/profiles/isci_meeting.yaml`
  - Add profile-level durable-topic thresholds only.
  - Do not add BMR-specific topic names or keyword shortcuts.

- `tests/test_optimization_long_term_v2.py`
  - Unit and integration tests for ICSI eval query curation, active L2 review protocol, durable policy, and regression matrix.

- `tests/test_optimization_l2_l3_scaling.py`
  - Scaling-specific tests for 30-file effective surface behavior and suppressed topic accounting.

---

## Task 1: ICSI Retrieval Query Set

**Files:**
- Create: `optimization/long_term_v2/curate_icsi_eval_queries.py`
- Create: `optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] **Step 1: Write failing test for query curation**

Add a test that creates a tiny run with two active L2 topics and one suppressed L2, then calls `curate_icsi_eval_queries()`.

Expected:
- generated JSONL includes active L2 topics.
- generated JSONL excludes suppressed L2 topics.
- each query has `query`, `expected_l2_labels`, `expected_obj_ids`, and `notes`.

- [ ] **Step 2: Run red test**

Run:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2.OptimizationLongTermV2Tests.test_curate_icsi_queries_uses_effective_active_topics
```

Expected:

```text
ModuleNotFoundError or AttributeError for curate_icsi_eval_queries
```

- [ ] **Step 3: Implement `curate_icsi_eval_queries.py`**

Implementation requirements:
- Read active L2 through `load_effective_topic_surface()`.
- Pick top active L2 by linked L1 count and meeting spread.
- Produce 8-12 reviewable ICSI questions.
- Do not call LLM.
- Do not include suppressed L2 labels in generated query expectations.

Suggested query types:
- topic overview
- topic evolution
- design rationale
- local factual evidence
- unresolved issue

- [ ] **Step 4: Run green test**

Run:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2.OptimizationLongTermV2Tests.test_curate_icsi_queries_uses_effective_active_topics
```

Expected: `OK`.

- [ ] **Step 5: Generate ICSI candidate query set**

Run:

```powershell
uv run python optimization/long_term_v2/curate_icsi_eval_queries.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --share-mem-root memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective `
  --out optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --report-out optimization/reports/icsi_bmr_first360_query_review.md
```

Expected:
- 8-12 query rows.
- no query expects suppressed L2.
- report shows representative L1 examples.

---

## Task 2: ICSI Retrieval Eval With Effective Surface

**Files:**
- Modify: `optimization/long_term_v2/evaluate_retrieval.py`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] **Step 1: Write failing test for suppressed metadata in retrieval report**

Expected:
- report includes `effective_topic_surface`.
- each query row includes:
  - `selected_l2_ids`
  - `selected_l2_labels`
  - `suppressed_l2_ids_available`
  - `suppressed_selected_l1_count`

- [ ] **Step 2: Run red test**

Run:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2.OptimizationLongTermV2Tests.test_retrieval_report_records_suppressed_topic_context
```

Expected: fails because per-query suppressed metadata is missing.

- [ ] **Step 3: Implement metadata**

Implementation requirements:
- Keep selected L1 evidence unchanged.
- Do not count suppressed L2 as selected L2.
- Count selected L1 whose old raw L2 assignment was suppressed.
- Save enough debug data for manual trace review.

- [ ] **Step 4: Run ICSI retrieval eval**

Run:

```powershell
uv run python optimization/long_term_v2/evaluate_retrieval.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --share-mem-root memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective `
  --top-k-l1 60 `
  --out-subdir retrieval_eval_icsi_effective
```

Expected:
- retrieval report exists.
- selected L2 does not include suppressed L2.
- selected L1 may include suppressed L1 as evidence.
- report says whether retrieval is actually better than raw topic surface.

---

## Task 3: Active L2 Manual Review Protocol

**Files:**
- Create: `optimization/long_term_v2/manual_review_active_l2.py`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] **Step 1: Write failing test for manual review queue**

Expected output sections:
- `top_largest_active_l2`
- `suppressed_l2`
- `random_linked_l1`
- `high_importance_l1_sample`
- `review_schema`

- [ ] **Step 2: Implement manual review queue generator**

Implementation requirements:
- Read effective active L2 only.
- Include suppressed L2 separately.
- Include representative L1 snippets.
- Decisions allowed:
  - `correct`
  - `too_broad`
  - `too_fragmented`
  - `wrong_assignment`
  - `generic_bucket`
  - `should_suppress`
  - `needs_l3_split`

- [ ] **Step 3: Generate 30-file ICSI manual review queue**

Run:

```powershell
uv run python optimization/long_term_v2/manual_review_active_l2.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --share-mem-root memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective `
  --out optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4/manual_review_active_l2
```

Expected:
- top 20 active L2 listed.
- suppressed 5 L2 listed separately.
- no raw canonical mutation.

- [ ] **Step 4: Manual inspection**

Inspect:
- top 20 largest active L2.
- all suppressed L2.
- 20 random linked L1.
- high-importance sample.

Pass condition:
- severe issue count = 0.
- sampled wrong assignment rate <= 5%.
- no top active L2 is a generic bucket.

---

## Task 4: Profile-Level Durable Topic Policy

**Files:**
- Create: `optimization/long_term_v2/apply_durable_topic_policy.py`
- Modify: `optimization/long_term_v2/profiles/isci_meeting.yaml`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] **Step 1: Write failing tests**

Tests:
- low-confidence singleton L1 goes review-only.
- high-importance singleton goes manual review, not silent drop.
- policy does not use dataset-specific topic strings.
- active L2 count can decrease while raw L2 remains unchanged.

- [ ] **Step 2: Implement policy sidecar**

Output:

```text
topic_review/durable_topic_policy_decisions.json
topic_review/effective_topic_index.json
topic_review/durable_topic_policy_report.md
```

Implementation rules:
- Use profile thresholds.
- Use coherence/meeting-spread/evidence-count signals.
- Do not add topic-name keyword shortcuts.
- Preserve raw L1/L2.

- [ ] **Step 3: Run candidate-only policy on ICSI 30**

Run:

```powershell
uv run python optimization/long_term_v2/apply_durable_topic_policy.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --out optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4/topic_review_policy_candidate
```

Pass condition:
- active L2 gets cleaner or remains stable.
- high-importance evidence is not silently unlinked.
- no BMR-specific rules appear in code.

---

## Task 5: L3 Stress And Focused Split Review

**Files:**
- Modify: `optimization/long_term_v2/llm_split_review.py`
- Modify: `optimization/long_term_v2/apply_split_review_candidates.py`
- Modify: `optimization/long_term_v2/retrieval_split_pressure.py`
- Test: `tests/test_optimization_l2_l3_scaling.py`

- [ ] **Step 1: Add tests for active-only L3 split pressure**

Expected:
- suppressed L2 is not proposed for L3 split.
- active oversized L2 can still be proposed.
- split failure stays review-only.

- [ ] **Step 2: Run focused split pressure on ICSI**

Run:

```powershell
uv run python optimization/long_term_v2/retrieval_split_pressure.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --retrieval-subdir retrieval_eval_icsi_effective `
  --out optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4/reports
```

Expected:
- split candidates are active L2 only.
- no suppressed topic is reintroduced.

- [ ] **Step 3: Optional LLM split review**

Only run if split pressure report shows real oversized active topics.

Run:

```powershell
uv run python optimization/long_term_v2/llm_split_review.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --model gemini-2.5-pro `
  --review-source optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4/reports/retrieval_split_pressure.json
```

Pass condition:
- proposals cite representative L1.
- accepted splits pass child-size/coherence gates.
- rejected splits have reasons.

---

## Task 6: Grace / ICSI / Locomo-Style Regression Matrix

**Files:**
- Create: `optimization/long_term_v2/run_regression_matrix.py`
- Test: `tests/test_optimization_long_term_v2.py`

- [ ] **Step 1: Write failing test for matrix output**

Expected datasets:
- `grace`
- `icsi`
- `locomo_style`

Expected metrics:
- active L2 count
- suppressed L2 count
- severe count
- unresolved warning count
- high-importance linked rate
- domain leakage count

- [ ] **Step 2: Implement matrix runner**

Implementation:
- Accept explicit run roots.
- Do not rebuild unless requested.
- Write summary JSON/MD.
- Do not mutate canonical.

- [ ] **Step 3: Run matrix**

Run:

```powershell
uv run python optimization/long_term_v2/run_regression_matrix.py `
  --grace-run-root optimization/runs/grace_v2_det_latest `
  --icsi-run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --locomo-run-root optimization/runs/locomo_style_latest `
  --out optimization/reports/regression_matrix_20260609
```

If Grace or Locomo latest roots are missing, the runner must report `missing_run_root` rather than failing silently.

Pass condition:
- ICSI does not produce Grace-only topic contamination.
- Grace does not regress.
- Locomo-style does not collapse into generic buckets.

---

## Task 7: Promotion Readiness Report

**Files:**
- Modify: `optimization/long_term_v2/maturity_certification.py`
- Create report under: `optimization/reports/`

- [ ] **Step 1: Add certification gates**

New gates:
- effective surface used by downstream.
- ICSI retrieval eval exists.
- ICSI active L2 manual review exists.
- regression matrix exists.

- [ ] **Step 2: Run certification**

Run:

```powershell
uv run python optimization/long_term_v2/maturity_certification.py `
  --grace-run-root optimization/runs/grace_v2_det_latest `
  --icsi-run-root optimization/runs/icsi_bmr001_031_first360_candidate4_rerun_20260608_c4 `
  --core-root optimization/long_term_v2 `
  --out optimization/reports/maturity_certification_20260609
```

Pass condition for this phase:
- status may remain `warning`.
- promotion decision must remain `do_not_promote` unless all gates pass.
- report must explicitly list missing gates.

---

## Verification Commands

Run after each task group:

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2 tests.test_optimization_l2_l3_scaling
```

Run before commit/push:

```powershell
uv run python -m unittest discover -s tests
rg -n "Bmr|BMR|go-ahead|little-bit|team-decided|annotation-process|system-performance|icsi_bmr" optimization/long_term_v2
rg -n "AIza|GOOGLE_APPLICATION_CREDENTIALS|GEMINI_API_KEY|BEGIN PRIVATE KEY|application_default_credentials|C:\\Users\\.*credentials" optimization tests -g "!optimization/long_term_v2/maturity_certification.py"
git status --short --branch
```

Expected:
- tests pass.
- no generated outputs tracked.
- no secret scan hits outside scanner regex definitions.
- no BMR-specific hardcode in implementation.

---

## Execution Order

1. Task 1: ICSI query set.
2. Task 2: ICSI retrieval eval.
3. Task 3: active L2 manual review protocol.
4. Review results manually.
5. Task 4 only if active L2 still over-links weak topics.
6. Task 5 only if retrieval pressure shows oversized active L2.
7. Task 6 regression matrix.
8. Task 7 promotion readiness report.

This order is intentional: first prove current effective surface works in retrieval, then decide whether thresholds and L3 split logic need more changes. Do not change durable-topic policy before reviewing retrieval traces.

---

## Stop Conditions

Stop and report instead of continuing if:

- ICSI query eval shows selected L1 evidence is mostly irrelevant.
- active L2 manual review finds severe generic bucket in top 20.
- durable policy reduces Grace high-importance linked rate significantly.
- focused split review proposes child labels unsupported by representative L1.
- any command writes into canonical `share_mem/` or `long_term/`.

---

## Success Criteria For This Plan

This plan is complete when:

- ICSI 30-file effective retrieval eval exists.
- ICSI active L2 manual review queue exists and has been inspected.
- downstream retrieval/eval/runtime all use effective topic surface.
- no suppressed L2 appears as durable topic in retrieval context.
- Grace / ICSI / Locomo-style regression matrix exists.
- maturity certification explicitly reports remaining blockers.
- canonical memory artifacts remain untouched.
