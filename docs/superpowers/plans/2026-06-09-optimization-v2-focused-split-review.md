# Optimization v2 Focused Split Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the remaining ICSI BMR first360 optimization v2 L2/L3 split warnings without adding Grace-specific or BMR-specific hardcoded taxonomy.

**Architecture:** Reuse the existing isolated optimization v2 split-review pipeline. LLM output is a sidecar proposal, deterministic validation decides whether a candidate split can be materialized into a candidate-only run, and comparison reports decide whether the result stays isolated or becomes a shadow candidate.

**Tech Stack:** Python, unittest, Gemini via existing `share_mem.l1.gemini_clients`, optimization v2 JSON sidecars, PowerShell commands.

---

## Scope

This plan starts from:

- source run: `optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609`
- effective L1 root: `memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective`
- query set: `optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl`

The two known unresolved broad topics are:

- `L2-annotation-tool`
- `L2-data-collection`

Do not write to:

- `share_mem/`
- `long_term/l2`
- `long_term/l3`

All generated candidate output remains under `optimization/runs/` or `optimization/reports/`.

## Task 1: Baseline Check

**Files:**
- Read: `optimization/reports/icsi_bmr_first360_promotion_readiness.md`
- Read: `optimization/reports/icsi_bmr_first360_active_l2_split_candidates/active_l2_split_candidates.md`

- [x] Confirm candidate5 exists locally.

Run:

```powershell
Test-Path optimization\runs\icsi_bmr001_031_first360_candidate5_label_split_20260609
```

Expected: `True`

- [x] Confirm effective ICSI root exists locally.

Run:

```powershell
Test-Path memory_outputs\icsi\runs\bmr_first360_combined_bmr001_031_first360_20260606\share_mem_effective
```

Expected: `True`

## Task 2: Run Focused LLM Split Review

**Files:**
- Use: `optimization/long_term_v2/llm_split_review.py`
- Output: `optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609/l2/llm_split_review_proposals.json`
- Output: `optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609/api_calls/*.json`

- [ ] Run focused split review only for the two known broad topics.

Run:

```powershell
uv run python optimization/long_term_v2/llm_split_review.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609 `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --source-l2-id L2-annotation-tool `
  --source-l2-id L2-data-collection `
  --sample-limit 16 `
  --max-sources-per-call 1 `
  --merge-existing
```

Expected:

- The command exits 0.
- API logs are written under the candidate run root.
- Proposals include either accepted split candidates or explicit `review_only` decisions.
- No canonical artifacts are modified.

## Task 3: Apply Accepted Split Candidates To Candidate6

**Files:**
- Use: `optimization/long_term_v2/apply_split_review_candidates.py`
- Output: `optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609`

- [ ] Apply only accepted split candidates.

Run:

```powershell
uv run python optimization/long_term_v2/apply_split_review_candidates.py `
  --source-run-root optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609 `
  --out-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --clean
```

Expected:

- Accepted proposals that fail separability, child-size, or assignment gates are skipped.
- Candidate5 remains unchanged.
- Candidate6 exists only under `optimization/runs/`.

## Task 4: Validate Candidate6

**Files:**
- Use: `optimization/long_term_v2/validate_view.py`
- Use: `optimization/long_term_v2/evaluate_retrieval.py`
- Use: `optimization/long_term_v2/compare_effective_topic_runs.py`
- Output: `optimization/reports/icsi_bmr_first360_candidate6_comparison/`

- [ ] Validate candidate6.

Run:

```powershell
uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609
```

Expected: `severe=0`.

- [ ] Run ICSI retrieval eval for candidate6.

Run:

```powershell
uv run python optimization/long_term_v2/evaluate_retrieval.py `
  --run-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --queries optimization/long_term_v2/eval/icsi_bmr_first360_queries.jsonl `
  --share-mem-root memory_outputs/icsi/runs/bmr_first360_combined_bmr001_031_first360_20260606/share_mem_effective `
  --out-subdir retrieval_eval_icsi_effective
```

Expected:

- Average L1 recall does not drop below candidate5.
- Semantic L2/L3 hits do not regress.

- [ ] Compare candidate5 vs candidate6.

Run:

```powershell
uv run python optimization/long_term_v2/compare_effective_topic_runs.py `
  --baseline optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609 `
  --candidate optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --out optimization/reports/icsi_bmr_first360_candidate6_comparison
```

Expected:

- If splits applied and no metrics regress: candidate can be marked as a shadow candidate.
- If no splits applied or metrics regress: candidate remains isolated.

## Task 5: Answer-Quality Proxy

**Files:**
- Use: `optimization/long_term_v2/evaluate_icsi_answer_quality.py`
- Output: `optimization/reports/icsi_bmr_first360_candidate6_answer_quality/`

- [ ] Run no-LLM answer-quality proxy.

Run:

```powershell
uv run python optimization/long_term_v2/evaluate_icsi_answer_quality.py `
  --baseline-run-root optimization/runs/icsi_bmr001_031_first360_candidate5_label_split_20260609 `
  --candidate-run-root optimization/runs/icsi_bmr001_031_first360_candidate6_llm_split_review_20260609 `
  --out optimization/reports/icsi_bmr_first360_candidate6_answer_quality
```

Expected:

- Candidate6 proxy score is not lower than candidate5.
- Report explicitly states this is not full LLM answer scoring.

## Task 6: Final Report

**Files:**
- Create: `optimization/reports/icsi_bmr_first360_candidate6_promotion_readiness.md`

- [ ] Write a concise readiness report containing:

```text
source run
candidate run
split proposal result
applied split count
skipped split count
validation result
retrieval comparison
answer-quality proxy result
promotion decision
remaining issues
```

Promotion decision rules:

- `candidate6_shadow_ready`: splits applied, validation severe=0, retrieval not worse, answer-quality proxy not worse.
- `candidate6_kept_isolated`: no splits applied, weak labels remain, or any metric regresses.

## Task 7: Verification

**Files:**
- Test: `tests/test_optimization_l2_l3_scaling.py`
- Test: `tests/test_optimization_long_term_v2.py`
- Test: `tests/test_optimization_runtime_adapter.py`
- Test: `tests/test_memory_output_roots.py`

- [ ] Run targeted tests.

```powershell
uv run python -m unittest tests.test_optimization_long_term_v2 tests.test_optimization_l2_l3_scaling tests.test_optimization_runtime_adapter tests.test_memory_output_roots
```

Expected: OK.

- [ ] Run full tests before any completion claim.

```powershell
uv run python -m unittest discover -s tests
```

Expected: OK.

- [ ] Run scans.

```powershell
git diff --check
rg -n "DEFAULT_CHILD|transcript segmentation|idea-unit coverage|topic lifecycle|manager-agent|memory evaluation strategy|L2-transcript|L3-transcript" optimization/long_term_v2 docs/superpowers/plans/2026-06-09-optimization-v2-focused-split-review.md
rg -n "AIza|GOOGLE_APPLICATION_CREDENTIALS|GEMINI_API_KEY|BEGIN PRIVATE KEY|application_default_credentials|C:\\Users\\.*credentials" optimization docs tests -g "!optimization/long_term_v2/maturity_certification.py"
```

Expected:

- `git diff --check` exits 0.
- Hardcode scan has no new core logic hits.
- Secret scan has no real secret hits.

## Self-Review Notes

- This plan does not add deterministic BMR-specific child labels.
- This plan reuses existing generic split-review validation.
- This plan may call the LLM, but the LLM cannot directly overwrite runtime; it only creates proposals.
- Candidate6 remains ignored/local under `optimization/runs/`; only durable reports and code/test changes may be committed.
