# Optimization v2 ICSI L2/L3 Scaling Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make optimization v2 robust enough to process larger ICSI BMR batches without forcing every L1 into weak L2 topics, without noisy L3 child splits, and without mutating canonical `share_mem/` or `long_term/`.

**Architecture:** Keep raw L1 immutable and keep all new experiments under sidecar roots. Add evidence-first diagnostics before changing assignment behavior; let low-confidence L1 stay review-only; use LLM-assisted review proposals for merge/split decisions, but validate every proposal before applying it to a candidate run. Avoid Grace-specific or ICSI-content-specific hardcoded ontology in core logic; dataset-specific noise and label policy stays in profiles.

**Tech Stack:** Python stdlib, existing `optimization/long_term_v2` modules, existing `share_mem` ICSI runner, `unittest`, Gemini only for optional review/proposal stages with logged sidecar artifacts.

---

## Manual Inspection Findings To Preserve

- `optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605` improved over fixed2/fixed3: bad labels such as `think`, `oh`, `stuff gets broken`, and `hoc data format` no longer appear as durable L2/L3 labels.
- The current run still links every filtered L1: `linked_l1_count=228`, `unlinked_l1_count=0`. This is acceptable for a small filtered probe but risky for 30 meetings because low-value or ambiguous L1 may pollute durable topics.
- `data source` is too broad: it mixes Aurora digit task source, collaboration data vetting, spontaneous speech vs written text, and backchannel inference hypotheses.
- `data collection` is too broad: it mixes co-located PDA research rationale, digit-reading collection logistics, software crash initialization issues, and equipment deployment choices.
- `corpus management` is partly coherent but has weak child assignment: `audio dvds` also catches renumbering/ad-hoc format artifacts.
- `recording setup` is mostly coherent, but L3 child `open recording equipment` is too broad and absorbs many unrelated setup L1; this is a candidate for LLM-assisted split review, not another deterministic string blacklist.
- Validation currently reports `0` warnings for fixed4, but the manual review still found broad-topic concerns. The validation gate needs quality diagnostics, not only label lint.

---

## Refined Decision Model

This is the core logic that the implementation must preserve. It is intentionally not a Grace-specific ontology and not an ICSI-specific topic map.

### L1 to L2: Durable Topic Eligibility

An L1 does **not** have to link to L2. L2 is a long-term topic surface, not a storage bucket for every extracted evidence object.

An L1 can be assigned to L2 when all of these are true:

1. It has a semantic signature with at least two non-generic signals after profile stopwords and artifact terms are removed.
2. It shares a durable semantic key or high-confidence semantic overlap with an existing or induced L2.
3. The assignment can produce a rationale that cites evidence-derived terms, not only `related_topics`.
4. The confidence passes the profile threshold for durable assignment.

An L1 should become review-only, not force-linked, when any of these are true:

1. Its best topic score is low or depends mostly on generic words.
2. It is a high-importance but ambiguous singleton.
3. It is meaningful but only appears once and has no clear durable topic yet.
4. It is a source-data/setup object that may be useful later but should not define a long-term topic.

The desired output is not `unlinked_l1_count=0`. The desired output is:

- high-value L1 linked or explicitly reviewed;
- low-confidence L1 review-only with reason;
- no silent drop of important evidence;
- no broad L2 created just to absorb everything.

### L2 Quality: What Counts As A Real Topic

A durable L2 should be a recurring long-term issue, method, design direction, data/process concern, or research question. It should have:

- a label supported by representative L1 evidence;
- inclusion and exclusion criteria;
- assignment rationales for linked L1;
- current_state and evolution_summary grounded in the timeline;
- enough internal coherence that a human can inspect 5 linked L1 and see the same problem line.

A suspect L2 should be flagged when:

- it mixes three or more weakly-overlapping subtopic signatures;
- its label is generic, source-like, or administrative;
- it is mostly one meeting and low durability;
- it contains high semantic entropy and low top-term concentration;
- it only exists because many low-confidence L1 needed somewhere to go.

For fixed4, the known suspect examples are:

- `data source`: likely mixes digit task source, collaboration data vetting, and spontaneous speech inference.
- `data collection`: likely mixes data collection logistics, PDA scenario rationale, software crash issues, and deployment choices.
- `recording setup`: real topic, but probably too broad for one L2 at larger scale.
- `corpus management`: real topic, but child split may need review.

### L2 to L3: Promotion Conditions

L3 is a navigation layer above an oversized durable L2. It should not appear just because an L2 is large.

L3 materialization is allowed only when:

1. The source L2 is oversized relative to corpus distribution or prompt pressure.
2. There are at least two child L2 candidates with non-empty evidence.
3. Child candidates are semantically separable.
4. Every promoted source L1 is assigned exactly once.
5. The split improves prompt/retrieval clarity compared with the original L2.

If the split does not satisfy these conditions, the source L2 should produce a `needs_split_review` sidecar item. This is a valid output. It is better than materializing weak children.

### LLM Role

LLM should not replace deterministic assignment as an unchecked authority. Its role is:

- propose splits for broad L2;
- propose merges for fragmented L2;
- propose better labels;
- identify unsupported assignments;
- provide rationale with representative L1 ids.

LLM proposals are sidecar-only until validation passes. Accepted proposals are applied only to a candidate run under `optimization/runs/`.

### 30-Meeting Stability Gates

For a 29/30 BMR first360 run, the system is considered stable only if:

- no canonical `share_mem/`, `long_term/l2`, or `long_term/l3` files are modified;
- L1 final validation creates a filtered sidecar;
- high-importance unlinked L1 count is explainable in manual review;
- L2 labels contain no function words, filler fragments, or Grace memory-system ontology;
- review-only L1 share is not zero by force and not excessive by collapse;
- largest L2 topics are either coherent or listed in topic quality review;
- L3 severe issues are zero;
- weak L3 split candidates are review-only, not materialized;
- topic quality audit is run before any LLM proposal;
- any LLM proposal has representative L1 ids and validation status.

### Cross-Dataset Demonstration Standard

The definitions above are meant to be **demonstration-grade standards** for mentor-mentee / research-meeting memory, not a private rulebook for Grace or ICSI. Every behavioral change to L1-to-L2 assignment, review-only handling, L2 validation, L3 promotion, or retrieval-oriented topic slicing must be checked against a small cross-dataset matrix before it can be considered mature.

The required matrix is:

1. **Grace memory-system meetings**
   - Source: current canonical `share_mem/`.
   - Purpose: ensure existing demo questions and high-importance evidence do not regress.
   - Failure example: a change that makes Grace lose `segment / idea unit` rationale evidence is not acceptable.

2. **ICSI BMR meeting transcripts**
   - Source: sidecar ICSI first360 filtered share_mem roots under `share_mem_experiments/`.
   - Purpose: ensure the system does not pull non-Grace meeting content into Grace memory-system ontology.
   - Failure example: ICSI audio/headset/data-quality discussions becoming `memory evaluation strategy` or `transcript segmentation` is domain leakage.

3. **LOCOMO-style conversation-memory fixture**
   - Source: a small share_mem-style fixture under `optimization/long_term_v2/fixtures/locomo_style_share_mem/`, or a real LOCOMO-derived share_mem root if one is later added.
   - Purpose: show that the rules also work for long-running conversation memory and evaluation-style topics.
   - Required content patterns:
     - stable personal or situational facts;
     - temporal changes across sessions;
     - multi-hop evidence dependencies;
     - unanswerable or insufficient-evidence cases;
     - evaluation-method discussion if the transcript is about LOCOMO itself.
   - Failure example: LOCOMO-style family/work/preference facts collapsing into `memory system`, `data source`, or `evaluation` generic buckets.

Grace meetings that merely **discuss LOCOMO as a benchmark** do not count as LOCOMO-style validation. They only validate Grace's discussion about LOCOMO. A separate LOCOMO-style fixture is required until real LOCOMO share_mem artifacts exist.

For each behavior change, the report must include a compact row for all three datasets:

```json
{
  "dataset": "grace|icsi|locomo_style",
  "l1_count": 0,
  "l2_count": 0,
  "l3_count": 0,
  "high_importance_linked_rate": 0.0,
  "review_only_l1_count": 0,
  "generic_bucket_issue_count": 0,
  "domain_leakage_issue_count": 0,
  "manual_review_issue_count": 0,
  "decision": "pass|warning|fail",
  "reason": "short evidence-backed explanation"
}
```

If a rule improves one dataset but hurts another, it must not be promoted into core logic. It must become either:

- a profile threshold;
- a review-only sidecar rule;
- an LLM proposal hint that still requires validation;
- or a rejected experiment with explicit rationale.

---

## Execution Priority

Because L1 is being run in a separate fork, this plan should prioritize L2/L3 maturity in this order:

1. **Topic quality audit first.** Do not alter assignment until the audit can identify broad-topic and weak-split risks.
2. **Review-only L1 second.** Make it possible for L1 to remain outside L2 when confidence is weak.
3. **L3 separability third.** Prevent weak deterministic child splits from materializing.
4. **Focused LLM topic review fourth.** Use the audit queue as input; do not review the entire corpus blindly.
5. **Cross-dataset matrix fifth.** Any assignment or promotion change must be tested on Grace, ICSI, and LOCOMO-style fixtures before larger scaling is trusted.
6. **Candidate comparison sixth.** Compare baseline fixed4, review-only candidate, separability candidate, and LLM-assisted candidate.
7. **Run larger sidecar validation last.** Only after the above gates exist should a 10-file/29-file L2/L3 run be judged.

The plan should not add a new hardcoded topic taxonomy. Profile-level noise policy is allowed; core ontology shortcuts are not.

---

## File Structure

### Existing files to modify

- `optimization/long_term_v2/induce_l2_topics.py`
  - Add review-only assignment path and topic coherence diagnostics.
  - Keep deterministic assignment conservative; do not force low-confidence L1 into durable L2.

- `optimization/long_term_v2/promote_l3.py`
  - Gate L3 materialization on split separability and coherence improvement, not only event count.
  - Add review-only split recommendations when deterministic child terms are weak.

- `optimization/long_term_v2/validate_view.py`
  - Add broad-topic diagnostics, review-only ratio checks, child split quality checks, and questionable L2 sampling.

- `optimization/long_term_v2/build_view.py`
  - Record review-only L1 metrics and topic-quality audit path in the run manifest when present.

- `optimization/long_term_v2/maturity_certification.py`
  - Add gates for topic-quality audit presence, review-only reason coverage, and weak L3 split handling.
  - Add cross-dataset matrix status so maturity cannot be claimed from a single dataset.

- `optimization/long_term_v2/profiles/isci_meeting.yaml`
  - Add threshold policy only: review-only ratio bounds, minimum meeting spread, split confidence thresholds.
  - Do not add domain-answer ontology. Keep only noise/label policy and scale thresholds.

- `optimization/long_term_v2/profiles/mentor_mentee.yaml`
  - Keep the default standard dataset-neutral for mentor-mentee / research meetings.
  - Add only generic profile knobs such as language, minimum recurrence, generic artifact terms, and review-only threshold ranges.

- `optimization/long_term_v2/profiles/locomo_conversation.yaml`
  - Add a small LOCOMO-style profile for validation fixtures.
  - It may define conversation-memory noise policy and temporal/multi-hop evaluation defaults.
  - It must not encode answer topics such as specific names, preferences, or expected gold labels.

- `share_mem/run_icsi_batch.py`
  - Add `--target-success-count` so resume runs stop naturally when the desired successful files are reached.
  - Make status loading UTF-8 BOM tolerant.

- `share_mem/store.py`
  - Make JSON loading UTF-8 BOM tolerant for generated files.

### New files to create

- `optimization/long_term_v2/audit_topic_quality.py`
  - Produce L2/L3 quality audit reports independent of build.
  - Inspect largest L2, low-confidence assignments, topic coherence, meeting spread, broad-topic risk, and child split separability.

- `optimization/long_term_v2/llm_topic_review.py`
  - Optional LLM sidecar proposal tool for broad L2 topics.
  - Input: L2 node plus representative linked L1 snippets.
  - Output: merge/split/rename/review-only recommendations with representative L1 ids and rationale.

- `optimization/long_term_v2/apply_topic_review_candidates.py`
  - Apply accepted review proposals to a candidate run only.
  - Never writes canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.

- `optimization/long_term_v2/compare_topic_candidates.py`
  - Compare multiple candidate v2 runs on topic quality, review-only L1, L3 split quality, and retrieval pressure.

- `optimization/long_term_v2/cross_dataset_suite.py`
  - Run the same candidate logic on Grace, ICSI, and LOCOMO-style roots.
  - Produce one matrix report with per-dataset pass/warning/fail decisions.

- `optimization/long_term_v2/fixtures/locomo_style_share_mem/`
  - Small checked-in share_mem-style fixture for validation, not for final scoring.
  - Include long-running conversation-memory examples with temporal change, multi-hop dependency, and insufficient-evidence cases.

- `tests/test_optimization_l2_l3_scaling.py`
  - Focused tests for review-only L1, broad-topic diagnostics, child split validation, LLM proposal validation, and candidate-only application.
  - Include LOCOMO-style fixture assertions to ensure the core logic is not Grace/ICSI-only.

- `tests/test_icsi_batch_orchestration.py`
  - Tests for `--target-success-count` and UTF-8 BOM tolerant status loading.

---

## Task 1: Add Topic Quality Audit Before Changing Assignment

**Files:**
- Create: `optimization/long_term_v2/audit_topic_quality.py`
- Test: `tests/test_optimization_l2_l3_scaling.py`

- [ ] **Step 1: Write failing tests for broad-topic diagnostics**

Add tests that build a tiny run with one broad L2 containing unrelated L1 groups:

```python
def test_topic_quality_audit_flags_broad_l2_with_multiple_subtopic_signatures(self):
    report = audit_topic_quality(run_root=self.fixture_run_root)
    issue_codes = {issue["code"] for issue in report["issues"]}
    self.assertIn("broad_l2_mixed_signatures", issue_codes)
    self.assertIn("needs_topic_review", issue_codes)
```

Also test that a coherent topic with repeated terms and shared meeting purpose is not flagged:

```python
def test_topic_quality_audit_keeps_coherent_l2_clean(self):
    report = audit_topic_quality(run_root=self.coherent_run_root)
    self.assertFalse(any(issue["severity"] == "severe" for issue in report["issues"]))
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
uv run python -m unittest tests.test_optimization_l2_l3_scaling
```

Expected: FAIL because `audit_topic_quality` does not exist.

- [ ] **Step 3: Implement `audit_topic_quality.py`**

Implement:

```python
def audit_topic_quality(*, run_root: Path | str, out_dir: Path | str | None = None) -> dict[str, Any]:
    # Load l2_view, l2_index, l3_view, input_snapshot/tree.json.
    # For each L2:
    # - event_count
    # - meeting_spread
    # - top semantic term concentration
    # - representative keyword sets from timeline summaries
    # - subtopic entropy using lexical clusters
    # - broad_topic_risk if one L2 contains 3+ weakly-overlapping clusters.
    # For each L3 child:
    # - child size bucket
    # - parent coverage
    # - child label quality
    # - split separability from sibling keyword overlap.
    # Write topic_quality_report.json/md and manual_topic_review_queue.json.
```

Use deterministic scoring only for diagnostics, not for new topic decisions.

- [ ] **Step 4: Run tests and verify pass**

Run:

```powershell
uv run python -m unittest tests.test_optimization_l2_l3_scaling
```

Expected: PASS.

- [ ] **Step 5: Run audit on fixed4 and inspect manually**

Run:

```powershell
uv run python optimization/long_term_v2/audit_topic_quality.py `
  --run-root optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605 `
  --out optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605/topic_quality
```

Expected review queue should flag at least `data source`, `data collection`, `corpus management`, and `recording setup` as review candidates, not necessarily severe failures.

---

## Task 2: Add Review-Only L1 Assignment Instead Of Linking Everything

**Files:**
- Modify: `optimization/long_term_v2/induce_l2_topics.py`
- Modify: `optimization/long_term_v2/profiles/isci_meeting.yaml`
- Test: `tests/test_optimization_l2_l3_scaling.py`

- [ ] **Step 1: Write failing tests for review-only L1**

Add a fixture with low-importance L1 that shares only generic words with a topic:

```python
def test_low_confidence_l1_goes_review_only_not_forced_into_l2(self):
    result = induce_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)
    self.assertNotIn("L1-low-confidence", result["l2_index"])
    reasons = {row["reason"] for row in result["unlinked_objects"]}
    self.assertIn("review_only_low_assignment_confidence", reasons)
```

Add a high-importance but ambiguous L1 test:

```python
def test_high_importance_ambiguous_l1_is_manual_review_not_silent_drop(self):
    result = induce_l2_topics(tree=tree, semantic_key_index=semantic, profile=profile)
    item = next(row for row in result["manual_review_items"] if row["obj_id"] == "L1-ambiguous")
    self.assertEqual(item["reason"], "high_importance_ambiguous_topic_review")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
uv run python -m unittest tests.test_optimization_l2_l3_scaling
```

Expected: FAIL because all plausible L1 currently get rescued/linked.

- [ ] **Step 3: Add profile thresholds**

In `optimization/long_term_v2/profiles/isci_meeting.yaml`:

```json
"l2_policy": {
  "allow_single_meeting_topic_if_high_importance": false,
  "review_only_min_assignment_confidence": 0.52,
  "semantic_rescue_min_confidence": 0.68,
  "max_review_only_l1_share": 0.20,
  "high_importance_review_threshold": 0.70
}
```

- [ ] **Step 4: Implement review-only result path**

In `induce_l2_topics.py`, add:

```python
if confidence < review_only_min_assignment_confidence:
    unlinked.append({
        "obj_id": obj_id,
        "reason": "review_only_low_assignment_confidence",
        "candidate_label": label,
        "importance": importance,
        "review": True,
    })
    continue
```

For high-importance ambiguous objects:

```python
if importance >= high_importance_review_threshold and confidence < min_confidence:
    unlinked.append({
        "obj_id": obj_id,
        "reason": "high_importance_ambiguous_topic_review",
        "candidate_label": label,
        "importance": importance,
        "review": True,
    })
    continue
```

- [ ] **Step 5: Run tests and fixed4 candidate build**

Run:

```powershell
uv run python -m unittest tests.test_optimization_l2_l3_scaling
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root share_mem_experiments/icsi_bmr_first360_probe_20260605/filtered_share_mem `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --out optimization/runs/icsi_bmr_first360_5file_v2_review_only_candidate_20260605 `
  --mode deterministic `
  --clean
```

Expected: Some unlinked/review-only L1 is acceptable. High-importance unlinked must appear in manual review with explicit reason.

---

## Task 3: Gate L3 Promotion On Split Separability

**Files:**
- Modify: `optimization/long_term_v2/promote_l3.py`
- Test: `tests/test_optimization_l2_l3_scaling.py`

- [ ] **Step 1: Write failing tests for weak split review-only**

Add a fixture where a 30-event L2 has poor child term separation:

```python
def test_l3_does_not_materialize_low_separability_children(self):
    l3 = build_l3_view(l2_result=l2_result, profile=profile)
    self.assertEqual(l3["l3_parents"], [])
    self.assertTrue(any(row["action"] == "needs_split_review" for row in l3["l2_merge_review"]["merge_reviews"]))
```

Add a fixture where a large L2 has clearly separable child topics:

```python
def test_l3_materializes_when_child_topics_are_separable(self):
    l3 = build_l3_view(l2_result=l2_result, profile=profile)
    labels = [child["label"] for parent in l3["l3_parents"] for child in parent["child_l2_nodes"]]
    self.assertIn("wire management", labels)
    self.assertIn("equipment cabinet", labels)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
uv run python -m unittest tests.test_optimization_l2_l3_scaling
```

Expected: FAIL because current promotion mostly uses event count.

- [ ] **Step 3: Implement split separability scoring**

Add internal helper:

```python
def _split_separability(children: list[dict[str, Any]]) -> dict[str, Any]:
    # Compute sibling label token overlap, assignment criteria overlap,
    # empty child count, dominant child share, and child keyword purity.
    # Return {score, reason_codes}.
```

Review-only if:

- fewer than 2 non-empty children
- max child share >= 0.80 and event_count > max child size
- sibling label overlap too high
- child labels are weak/generic after profile filtering

- [ ] **Step 4: Run fixed4 candidate build and audit**

Run:

```powershell
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root share_mem_experiments/icsi_bmr_first360_probe_20260605/filtered_share_mem `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --out optimization/runs/icsi_bmr_first360_5file_v2_l3_separability_candidate_20260605 `
  --mode deterministic `
  --clean

uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/icsi_bmr_first360_5file_v2_l3_separability_candidate_20260605
```

Expected: Broad L2 may remain as L2 with `needs_split_review` instead of forcing weak L3 children.

---

## Task 4: Add Focused LLM Topic Review For Broad L2

**Files:**
- Create: `optimization/long_term_v2/llm_topic_review.py`
- Create: `optimization/long_term_v2/apply_topic_review_candidates.py`
- Test: `tests/test_optimization_l2_l3_scaling.py`

- [ ] **Step 1: Write fake-client tests for proposal validation**

Use a fake LLM response:

```json
{
  "split_candidates": [
    {
      "source_l2_id": "L2-data-source",
      "child_topics": [
        {"label": "digit task source data", "representative_l1_ids": ["L1-001"]},
        {"label": "spontaneous speech inference data", "representative_l1_ids": ["L1-002"]}
      ],
      "rationale": "The current L2 mixes task source data and research-use data.",
      "confidence": 0.82
    }
  ],
  "review_only": []
}
```

Test:

```python
def test_llm_topic_review_requires_representative_l1_ids_and_rationale(self):
    report = validate_topic_review_proposals(proposals, l1_ids={"L1-001", "L1-002"})
    self.assertEqual(report["accepted_count"], 1)
```

Also test a generic unsupported proposal is rejected:

```python
def test_llm_topic_review_rejects_generic_or_unreferenced_split(self):
    report = validate_topic_review_proposals(proposals, l1_ids={"L1-001"})
    self.assertEqual(report["rejected_count"], 1)
```

- [ ] **Step 2: Implement sidecar-only LLM review**

`llm_topic_review.py` should:

- read `topic_quality/manual_topic_review_queue.json`
- only send flagged L2 to the LLM
- include representative L1 ids, content snippets, evidence snippets, and top terms
- write full logs under `api_calls/`
- write `topic_review_proposals.json`, `topic_review_validation.json`, `topic_review_queue.json`

- [ ] **Step 3: Implement candidate-only apply**

`apply_topic_review_candidates.py` should:

- copy run to a new candidate root under `optimization/runs/`
- apply accepted split/merge/rename only to that candidate
- regenerate `l2_view`, `l2_index`, `l3_view`, `l3_index`
- preserve original run untouched

- [ ] **Step 4: Run focused review on fixed4**

Run:

```powershell
uv run python optimization/long_term_v2/llm_topic_review.py `
  --run-root optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605 `
  --review-source optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605/topic_quality/manual_topic_review_queue.json `
  --model gemini-2.5-pro `
  --out optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605/topic_review
```

Expected: Proposals for `data source`, `data collection`, `recording setup`, and `corpus management`; no proposal is applied without validation.

---

## Task 5: Make ICSI Batch Orchestration Stop Cleanly At Target Success Count

**Files:**
- Modify: `share_mem/run_icsi_batch.py`
- Test: `tests/test_icsi_batch_orchestration.py`

- [ ] **Step 1: Write failing test for target success count**

```python
def test_batch_stops_after_target_success_count_without_starting_next_file(self):
    status = run_batch(config_with_target_success_count_2)
    self.assertEqual(status["summary"]["succeeded_count"], 2)
    self.assertEqual(status["summary"]["target_success_reached"], True)
    self.assertEqual(len([r for r in status["runs"] if r["status"] == "running"]), 0)
```

- [ ] **Step 2: Add CLI and config field**

Add to `BatchConfig`:

```python
target_success_count: int | None = None
```

Add parser:

```python
parser.add_argument("--target-success-count", type=int, default=None)
```

- [ ] **Step 3: Stop loop before preparing the next transcript**

In `run_batch()`:

```python
if config.target_success_count is not None:
    succeeded = sum(1 for run in runs if run.get("status") == "succeeded")
    if succeeded >= config.target_success_count:
        status["target_success_reached"] = True
        break
```

- [ ] **Step 4: Run tests**

Run:

```powershell
uv run python -m unittest tests.test_icsi_batch_orchestration tests.test_icsi_batch_orchestrator
```

Expected: PASS.

---

## Task 6: Make JSON Loading UTF-8 BOM Tolerant

**Files:**
- Modify: `optimization/long_term_v2/io_utils.py`
- Modify: `share_mem/store.py`
- Modify: `share_mem/run_icsi_batch.py`
- Test: `tests/test_icsi_batch_orchestration.py`

- [ ] **Step 1: Write failing tests**

```python
def test_optimization_load_json_accepts_utf8_bom(self):
    path.write_text("\\ufeff{\"ok\": true}", encoding="utf-8")
    self.assertEqual(load_json(path), {"ok": True})

def test_batch_status_loader_accepts_utf8_bom(self):
    path.write_text("\\ufeff{\"schema_version\": 1, \"runs\": []}", encoding="utf-8")
    self.assertEqual(_load_status(path)["runs"], [])
```

- [ ] **Step 2: Update loaders**

Use:

```python
path.read_text(encoding="utf-8-sig")
```

Only for reading. Keep writing as UTF-8 without BOM.

- [ ] **Step 3: Run tests**

Run:

```powershell
uv run python -m unittest tests.test_icsi_batch_orchestration tests.test_optimization_l2_l3_scaling
```

Expected: PASS.

---

## Task 7: Add Cross-Dataset Demonstration Harness

**Files:**
- Create: `optimization/long_term_v2/cross_dataset_suite.py`
- Create: `optimization/long_term_v2/profiles/locomo_conversation.yaml`
- Create: `optimization/long_term_v2/fixtures/locomo_style_share_mem/manifest.json`
- Create: `optimization/long_term_v2/fixtures/locomo_style_share_mem/tree.json`
- Create: `optimization/long_term_v2/fixtures/locomo_style_share_mem/l1_index.json`
- Create: `optimization/long_term_v2/fixtures/locomo_style_share_mem/meetings/LOC-001.json`
- Create: `optimization/long_term_v2/fixtures/locomo_style_share_mem/meetings/LOC-002.json`
- Create: `optimization/long_term_v2/fixtures/locomo_style_share_mem/meetings/LOC-003.json`
- Test: `tests/test_optimization_l2_l3_scaling.py`

- [ ] **Step 1: Write failing tests for LOCOMO-style fixture behavior**

Add a fixture test that verifies the LOCOMO-style data does not collapse into Grace or ICSI labels:

```python
def test_locomo_style_fixture_does_not_collapse_into_grace_or_icsi_labels(self):
    run_root = build_v2_fixture_run(
        share_mem_root=LOCOMO_STYLE_FIXTURE_ROOT,
        profile="optimization/long_term_v2/profiles/locomo_conversation.yaml",
    )
    labels = {row["label"].lower() for row in load_l2_view(run_root)["topics"]}
    forbidden_fragments = {
        "transcript segmentation",
        "idea unit",
        "memory evaluation strategy",
        "recording setup",
        "data collection",
        "data source",
    }
    self.assertFalse(any(fragment in label for label in labels for fragment in forbidden_fragments))
```

Add a test that verifies temporal and multi-hop conversation-memory patterns become durable topics:

```python
def test_locomo_style_fixture_preserves_temporal_and_multihop_topics(self):
    run_root = build_v2_fixture_run(
        share_mem_root=LOCOMO_STYLE_FIXTURE_ROOT,
        profile="optimization/long_term_v2/profiles/locomo_conversation.yaml",
    )
    report = load_json(run_root / "validation" / "l2_validation_report.json")
    semantic_labels = {row["semantic_family"] for row in report["topic_summaries"]}
    self.assertIn("temporal_state_change", semantic_labels)
    self.assertIn("multi_hop_personal_context", semantic_labels)
    self.assertIn("insufficient_evidence_boundary", semantic_labels)
```

- [ ] **Step 2: Create LOCOMO-style share_mem fixture**

Create three small meetings with 24-36 L1 objects total:

- recurring personal context such as a preference, schedule, or relationship fact;
- a temporal update that changes an earlier state;
- a multi-hop dependency where answer requires connecting two meetings;
- an unanswerable object where evidence says the information is unknown;
- a low-value administrative object that should be review-only or unlinked.

Use share_mem-style objects:

```json
{
  "obj_id": "L1-LOC-001-001",
  "type": "finding",
  "legacy_type": "result",
  "meeting_id": "LOC-001",
  "meeting_date": "2026-01-01",
  "content": "The mentee prefers evening study sessions because morning lab work is unpredictable.",
  "importance": 0.66,
  "evidence": "Mentee: I usually study in the evening because lab work can change every morning.",
  "related_topics": ["study preference", "schedule constraint"],
  "related_obj_ids": []
}
```

The fixture is not a LOCOMO benchmark score. It is a demonstration that optimization v2 rules generalize to LOCOMO-style conversation memory.

- [ ] **Step 3: Add profile without answer ontology**

Create `optimization/long_term_v2/profiles/locomo_conversation.yaml` with only:

```yaml
profile_id: locomo_conversation
content_language: en
topic_key_language: en
l2_policy:
  review_only_min_assignment_confidence: 0.50
  semantic_rescue_min_confidence: 0.66
  high_importance_review_threshold: 0.70
  max_review_only_l1_share: 0.25
semantic_key_policy:
  generic_artifact_terms:
    - conversation
    - discussion
    - thing
    - topic
    - update
  protected_semantic_families:
    - temporal_state_change
    - multi_hop_personal_context
    - insufficient_evidence_boundary
l3_policy:
  min_parent_event_count: 18
  min_child_count: 2
  min_split_separability: 0.58
```

This profile must not list expected answers, people, preferences, or exact topic labels from the fixture.

- [ ] **Step 4: Implement cross-dataset suite**

`cross_dataset_suite.py` should accept:

```powershell
uv run python optimization/long_term_v2/cross_dataset_suite.py `
  --grace-share-mem-root share_mem `
  --icsi-share-mem-root share_mem_experiments/icsi_bmr_first360_probe_20260605/filtered_share_mem `
  --locomo-share-mem-root optimization/long_term_v2/fixtures/locomo_style_share_mem `
  --out optimization/runs/cross_dataset_suite_20260605 `
  --mode deterministic `
  --clean
```

For each dataset it must:

- run optimization v2 build into a dataset-specific subrun;
- run validation;
- run topic quality audit if available;
- compute the matrix fields from the Cross-Dataset Demonstration Standard;
- write `suite_summary.json` and `suite_summary.md`.

- [ ] **Step 5: Run cross-dataset tests**

Run:

```powershell
uv run python -m unittest tests.test_optimization_l2_l3_scaling
```

Expected: PASS, including LOCOMO-style checks.

- [ ] **Step 6: Run the suite before larger ICSI**

Run:

```powershell
uv run python optimization/long_term_v2/cross_dataset_suite.py `
  --grace-share-mem-root share_mem `
  --icsi-share-mem-root share_mem_experiments/icsi_bmr_first360_probe_20260605/filtered_share_mem `
  --locomo-share-mem-root optimization/long_term_v2/fixtures/locomo_style_share_mem `
  --out optimization/runs/cross_dataset_suite_20260605 `
  --mode deterministic `
  --clean
```

Expected:

- Grace decision is pass or warning with no high-importance regression.
- ICSI decision has no Grace ontology leakage.
- LOCOMO-style decision has no Grace/ICSI label collapse and preserves temporal/multi-hop/insufficient-evidence topic families.

If any dataset fails, stop. Do not run larger ICSI until the regression is explained and fixed in a profile-safe way.

---

## Task 8: Run Larger Sidecar Validation Without Promoting

**Files:** no production code changes.

- [ ] **Step 1: Run 10-file first360 sidecar**

Run:

```powershell
uv run python share_mem/run_icsi_batch.py `
  --transcript-dir meeting_recording/transcript/ISCI `
  --output-root share_mem_experiments/icsi_bmr_first360_10file_probe_20260605 `
  --transcript-glob "Bmr*.txt" `
  --line-limit 360 `
  --max-files 30 `
  --target-success-count 10 `
  --timeout-seconds 7200 `
  --continue-on-failure `
  --clean
```

Expected: 10 successes, no accidental 11th run starts.

- [ ] **Step 2: Run L1 final validation**

```powershell
uv run python share_mem/validate_icsi_l1.py `
  --root share_mem_experiments/icsi_bmr_first360_10file_probe_20260605/share_mem `
  --out share_mem_experiments/icsi_bmr_first360_10file_probe_20260605/final_validation
```

Expected: filtered sidecar exists; high-value protocol L1 remain retained.

- [ ] **Step 3: Build optimization v2 on filtered L1**

```powershell
uv run python optimization/long_term_v2/build_view.py `
  --share-mem-root share_mem_experiments/icsi_bmr_first360_10file_probe_20260605/filtered_share_mem `
  --profile optimization/long_term_v2/profiles/isci_meeting.yaml `
  --out optimization/runs/icsi_bmr_first360_10file_v2_20260605 `
  --mode deterministic `
  --clean
```

- [ ] **Step 4: Validate and audit**

```powershell
uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/icsi_bmr_first360_10file_v2_20260605

uv run python optimization/long_term_v2/audit_topic_quality.py `
  --run-root optimization/runs/icsi_bmr_first360_10file_v2_20260605 `
  --out optimization/runs/icsi_bmr_first360_10file_v2_20260605/topic_quality
```

Expected:

- severe validation issues = 0
- broad L2 review queue is allowed
- no Grace memory-system ontology
- no function-word/filler L2 or child L2 labels

---

## Task 9: Compare Candidate Runs Before Accepting Any L2/L3 Change

**Files:**
- Create: `optimization/long_term_v2/compare_topic_candidates.py`
- Test: `tests/test_optimization_l2_l3_scaling.py`

- [ ] **Step 1: Write failing tests for candidate comparison**

Create two tiny candidate run roots:

- baseline: 10 linked L1, 0 review-only, one broad L2, one weak L3 split.
- candidate: 8 linked L1, 2 review-only with explicit reasons, two coherent L2, no weak L3 split.

Add:

```python
def test_compare_topic_candidates_prefers_explicit_review_over_forced_broad_l2(self):
    report = compare_topic_candidates(
        baseline_run_root=baseline_root,
        candidate_run_roots=[candidate_root],
    )
    row = report["candidates"][0]
    self.assertGreater(row["score_delta"], 0)
    self.assertIn("reduced_broad_topic_risk", row["improvements"])
    self.assertIn("review_only_l1_has_reason", row["improvements"])
```

Add regression for bad candidate:

```python
def test_compare_topic_candidates_penalizes_high_importance_unlinked_without_reason(self):
    report = compare_topic_candidates(
        baseline_run_root=baseline_root,
        candidate_run_roots=[bad_candidate_root],
    )
    row = report["candidates"][0]
    self.assertLess(row["score_delta"], 0)
    self.assertIn("unexplained_high_importance_unlinked", row["regressions"])
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
uv run python -m unittest tests.test_optimization_l2_l3_scaling
```

Expected: FAIL because `compare_topic_candidates` does not exist.

- [ ] **Step 3: Implement candidate comparison**

`compare_topic_candidates.py` should load:

- `manifest.json`
- `l2/l2_view.json`
- `l2/unlinked_l1_report.json`
- `l3/l3_view.json`
- `l3/l2_merge_review.json`
- `topic_quality/topic_quality_report.json`

Score components:

```python
score = 0
score += coherent_l2_count * 2
score -= broad_l2_review_count * 2
score -= weak_l3_materialized_count * 3
score += needs_split_review_count * 1
score += explained_review_only_l1_count * 0.5
score -= unexplained_high_importance_unlinked_count * 5
score -= function_word_label_count * 5
```

The score is only for side-by-side triage. It must not auto-promote.

- [ ] **Step 4: Run comparison on real candidates**

After Tasks 1-4 produce candidates, run:

```powershell
uv run python optimization/long_term_v2/compare_topic_candidates.py `
  --baseline-run-root optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605 `
  --candidate-run-root optimization/runs/icsi_bmr_first360_5file_v2_review_only_candidate_20260605 `
  --candidate-run-root optimization/runs/icsi_bmr_first360_5file_v2_l3_separability_candidate_20260605 `
  --out optimization/runs/icsi_bmr_first360_5file_candidate_comparison_20260605
```

Expected: report states whether each candidate improves topic quality, and lists exact regressions if not.

---

## Task 10: Add Maturity Certification Gates For L2/L3 Scaling

**Files:**
- Modify: `optimization/long_term_v2/maturity_certification.py`
- Test: `tests/test_optimization_l2_l3_scaling.py`

- [ ] **Step 1: Write failing certification tests**

```python
def test_certification_warns_when_topic_quality_audit_missing(self):
    report = certify_maturity(grace_run_root=run_root, core_root=core_root, out=out)
    gate = report["gates"]["topic_quality_audit"]
    self.assertEqual(gate["status"], "warning")
```

```python
def test_certification_fails_on_materialized_weak_l3_split(self):
    report = certify_maturity(grace_run_root=run_root, core_root=core_root, out=out)
    gate = report["gates"]["l3_split_quality"]
    self.assertEqual(gate["status"], "fail")
```

```python
def test_certification_requires_cross_dataset_matrix_for_behavior_changes(self):
    report = certify_maturity(grace_run_root=run_root, core_root=core_root, out=out)
    gate = report["gates"]["cross_dataset_demonstration"]
    self.assertEqual(gate["status"], "warning")
    self.assertIn("Grace, ICSI, and LOCOMO-style", gate["message"])
```

- [ ] **Step 2: Implement gates**

Add gates:

- `topic_quality_audit_present`
- `review_only_l1_reason_coverage`
- `l3_split_quality`
- `candidate_comparison_present`
- `cross_dataset_demonstration`

Gate statuses:

- missing audit = warning
- unexplained high-importance review-only/unlinked L1 = fail
- weak materialized child L2 = fail
- candidate comparison missing = warning
- missing cross-dataset matrix = warning
- any cross-dataset fail decision = fail
- Grace/ICSI/LOCOMO-style all pass or justified warning = pass

- [ ] **Step 3: Run certification on fixed4**

Run:

```powershell
uv run python optimization/long_term_v2/maturity_certification.py `
  --grace-run-root optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605 `
  --core-root optimization/long_term_v2 `
  --out optimization/reports/icsi_fixed4_l2_l3_certification_20260605
```

Expected: fixed4 should not be promotion-ready; if audit is missing, status should be warning, not pass.

---

## Task 11: LLM-Assisted Review Run On 5-File Probe

**Files:** no production code changes after Task 4.

- [ ] **Step 1: Run audit**

```powershell
uv run python optimization/long_term_v2/audit_topic_quality.py `
  --run-root optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605 `
  --out optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605/topic_quality
```

- [ ] **Step 2: Run focused LLM topic review**

```powershell
uv run python optimization/long_term_v2/llm_topic_review.py `
  --run-root optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605 `
  --review-source optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605/topic_quality/manual_topic_review_queue.json `
  --model gemini-2.5-pro `
  --out optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605/topic_review
```

- [ ] **Step 3: Apply only accepted proposals to candidate root**

```powershell
uv run python optimization/long_term_v2/apply_topic_review_candidates.py `
  --source-run-root optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605 `
  --proposal-validation optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605/topic_review/topic_review_validation.json `
  --out optimization/runs/icsi_bmr_first360_5file_v2_llm_review_candidate_20260605 `
  --clean
```

- [ ] **Step 4: Validate, audit, and compare**

```powershell
uv run python optimization/long_term_v2/validate_view.py `
  --run-root optimization/runs/icsi_bmr_first360_5file_v2_llm_review_candidate_20260605

uv run python optimization/long_term_v2/audit_topic_quality.py `
  --run-root optimization/runs/icsi_bmr_first360_5file_v2_llm_review_candidate_20260605 `
  --out optimization/runs/icsi_bmr_first360_5file_v2_llm_review_candidate_20260605/topic_quality

uv run python optimization/long_term_v2/compare_topic_candidates.py `
  --baseline-run-root optimization/runs/icsi_bmr_first360_5file_v2_fixed4_20260605 `
  --candidate-run-root optimization/runs/icsi_bmr_first360_5file_v2_llm_review_candidate_20260605 `
  --out optimization/runs/icsi_bmr_first360_5file_v2_llm_review_comparison_20260605
```

Expected: LLM candidate either improves broad-topic quality or is rejected with explicit reasons. A rejected LLM proposal is a valid outcome.

---

## Task 12: Verification And Promotion Boundary

**Files:** no production code changes.

- [ ] **Step 1: Run targeted tests**

```powershell
uv run python -m unittest `
  tests.test_optimization_l2_l3_scaling `
  tests.test_optimization_long_term_v2 `
  tests.test_icsi_l1_quality `
  tests.test_icsi_batch_orchestration `
  tests.test_icsi_batch_orchestrator
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

```powershell
uv run python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 3: Run hardcode and secret scans**

```powershell
rg -n "DEFAULT_CHILD|transcript segmentation|idea-unit coverage|topic lifecycle|manager-agent|memory evaluation strategy|L2-transcript|L3-transcript" optimization/long_term_v2 -g "*.py"
rg -n "<secret-patterns>" optimization share_mem tests -g "!optimization/long_term_v2/maturity_certification.py"
```

Expected: no core hardcode matches; no secret matches outside scanner definitions.

- [ ] **Step 4: Commit only code/tests**

Do not stage:

- `share_mem_experiments/**`
- `optimization/runs/**`
- old untracked `optimization/reports/optimization_v2_decision_catalog_20260603.*` unless explicitly requested

Commit:

```powershell
git add optimization/long_term_v2 share_mem/run_icsi_batch.py share_mem/store.py tests/test_optimization_l2_l3_scaling.py tests/test_icsi_batch_orchestration.py
git commit -m "Improve v2 ICSI scaling review gates"
git push
```

---

## Acceptance Criteria

- ICSI batch can stop at exactly N successful files without manual process killing.
- BOM JSON files do not break status/report readers.
- L2 induction can leave low-confidence L1 review-only instead of forcing all L1 into topics.
- High-importance unlinked L1 always has explicit review reason.
- L3 promotion does not materialize weak deterministic child splits.
- Broad L2 topics are surfaced in `topic_quality/manual_topic_review_queue.json`.
- Optional LLM topic review produces validated sidecar proposals, not unchecked assignment changes.
- 10-file first360 sidecar run completes with no canonical mutation.
- No Grace-specific ontology appears in optimization core Python.
- Every L2/L3 behavior change has a cross-dataset matrix row for Grace, ICSI, and LOCOMO-style validation.
- LOCOMO-style validation does not reuse Grace's LOCOMO benchmark discussion as a substitute for actual conversation-memory-style evidence.
- If Grace, ICSI, and LOCOMO-style outcomes disagree, the change is either profile-scoped, review-only, or rejected; it is not silently promoted into core logic.
- Full test suite passes.

---

## What Not To Do

- Do not modify canonical `share_mem/tree.json`, `share_mem/meetings/*`, `long_term/l2`, or `long_term/l3`.
- Do not fix ICSI L2/L3 by adding a hand-written canonical topic map.
- Do not fix LOCOMO-style behavior by adding a hand-written LOCOMO answer map.
- Do not claim generality from Grace and ICSI alone.
- Do not treat Grace meetings that discuss LOCOMO as a LOCOMO-style validation dataset.
- Do not force every L1 into L2 just to maximize linked count.
- Do not auto-apply LLM split/merge proposals without validation.
- Do not treat `validation severe=0` as sufficient if manual topic quality shows broad-topic collapse.
