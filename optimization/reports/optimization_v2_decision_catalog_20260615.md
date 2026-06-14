# Optimization v2 Decision Catalog - Implementation Details

Generated: 2026-06-15  
Scope: `optimization/long_term_v2` isolated L2/L3 pipeline, Grace + ICSI BMR concrete examples  
Status: implementation-detail reference, not a canonical replacement approval document

This document updates the earlier `optimization_v2_decision_catalog_20260603` report. The older report explained the first stable Grace-oriented v2 logic, but it did not include the later ICSI full-BMR work, runtime export distinction, revised held-out evaluation design, or the current token-budget decision. This version is meant to be read by a professor, collaborator, or reviewer who wants to understand exactly how the system decides:

1. what becomes L1 evidence;
2. what remains only review/noise;
3. how L1 becomes semantic keys;
4. how semantic keys become L2 durable topics;
5. how large L2 topics become L3 topic-family navigation;
6. how retrieval uses L1/L2/L3 without turning L3 into unsupported evidence;
7. how ICSI is evaluated without official QA labels;
8. where the system is still limited.

Important boundary:

- `share_mem/` and `memory_outputs/.../share_mem_effective/` are evidence inputs.
- `optimization/long_term_v2` builds derived L2/L3 views.
- v2 generated outputs live under `optimization/runs/` or `optimization/reports/`.
- v2 does not directly mutate canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.
- In the current ICSI evidence comparison, no Gemini/Vertex answer generation or judge call was used.

---

## 0. Current Reference Runs

### Grace reference

Run root:

```text
optimization/runs/grace_v2_latest_20260614
```

Input:

```text
share_mem/
```

Profile:

```text
optimization/long_term_v2/profiles/mentor_mentee.yaml
```

Snapshot:

| Item | Count |
|---|---:|
| Source L1 objects | 448 |
| Semantic key rows | 448 |
| L2 topics | 49 |
| Linked L1 | 440 |
| Unlinked L1 | 8 |
| Raw materialized L3 parents | 3 |
| Runtime L3 parents | 3 |
| L3-assigned L1 | 71 |
| L2 validation severe | 0 |
| L2 validation warnings | 2 |
| L3 validation severe | 0 |
| L3 validation warnings | 2 |
| LLM used | no |

### ICSI BMR reference

Run root:

```text
optimization/runs/icsi_bmr_full_completed29_v2_20260614
```

Input:

```text
memory_outputs/icsi/runs/bmr_full_completed29_eval_20260614/share_mem_effective
```

Profile:

```text
optimization/long_term_v2/profiles/isci_meeting.yaml
```

Snapshot:

| Item | Count |
|---|---:|
| Source effective L1 objects | 6,233 |
| Semantic key rows | 6,233 |
| Raw L2 topics | 530 |
| Linked L1 | 6,203 |
| Unlinked L1 | 30 |
| Raw materialized L3 parents | 65 |
| Runtime L3 parents | 6 |
| Raw L3-assigned L1 | 2,683 |
| L2 validation severe | 0 |
| L2 validation warnings | 9 |
| L3 validation severe | 0 |
| L3 validation warnings | 9 |
| LLM used | no |

The ICSI raw materialized L3 count and runtime L3 count differ intentionally. Raw L3 materialization records many possible parent/child structures. Runtime export uses a compressed corpus-theme L3 surface so retrieval and demo traces do not expose hundreds of noisy topic-family nodes.

---

## 1. Terminology

### Canonical

`canonical` means the currently established production/reference artifacts:

```text
share_mem/
long_term/l2/
long_term/l3/
```

These are not modified by optimization v2 unless a separate explicit promotion decision is made.

### Effective L1

`effective L1` means the L1 surface downstream components should read after sidecar gates. For Grace, this is currently `share_mem/`. For ICSI, this is not the raw BMR extraction folder; it is:

```text
memory_outputs/icsi/runs/bmr_full_completed29_eval_20260614/share_mem_effective
```

The effective view exists because ICSI raw extraction may retain broad-but-valid L1 objects. Sidecar gates suppress source-data-only, duplicate, setup-only, or weak/noisy objects before L2/L3 construction.

### L1

L1 is the atomic evidence object. It must point back to meeting evidence. It is the factual layer.

### L2

L2 is a durable topic/evolution context built from multiple L1 objects. It is not raw evidence by itself.

### L3

L3 is a topic-family navigation layer for large or internally diverse L2 topics. It helps retrieval decide which child L2 context to include. It is not the factual source of an answer.

### Retrieval rule

Retrieval is evidence-first:

```text
query
  -> L1 evidence seeds
  -> linked L2 context
  -> L3 topic-family navigation
  -> formatted prompt context
```

The answer should be grounded in L1. L2/L3 organize and summarize the evolution, but they do not replace evidence.

---

## 2. End-To-End Pipeline

High-level flow:

```text
transcript
  -> segmentation / bounded idea units
  -> L1 candidate objects
  -> L1 verifier / reducer / sidecar gate
  -> immutable or effective share_mem L1
  -> semantic key extraction
  -> L2 topic induction and L1 assignment
  -> L3 promotion / child split for oversized L2
  -> validation / review sidecars
  -> runtime export
  -> retrieval trace / eval
```

Files involved:

| Stage | Main files |
|---|---|
| L1 input loading | `share_mem.store`, `optimization/long_term_v2/io_utils.py` |
| Profile | `optimization/long_term_v2/profiles/mentor_mentee.yaml`, `optimization/long_term_v2/profiles/isci_meeting.yaml` |
| Calibration | `optimization/long_term_v2/calibrate_profile.py` |
| Semantic keys | `optimization/long_term_v2/extract_semantic_keys.py` |
| L2 induction | `optimization/long_term_v2/induce_l2_topics.py`, `optimization/long_term_v2/assign_l2.py` |
| L3 promotion | `optimization/long_term_v2/promote_l3.py` |
| Topic review / effective surface | `optimization/long_term_v2/audit_topic_quality.py`, `optimization/long_term_v2/apply_topic_review_candidates.py`, `optimization/long_term_v2/effective_view.py` |
| Runtime export | `optimization/long_term_v2/export_runtime_view.py` |
| Retrieval eval | `optimization/long_term_v2/evaluate_retrieval.py` |
| ICSI held-out eval | `optimization/long_term_v2/create_icsi_eval_pack.py`, `optimization/long_term_v2/revise_icsi_eval_pack.py` |
| No-LLM system comparison | `optimization/long_term_v2/compare_icsi_systems_no_llm.py` |

---

## 3. L1: What Becomes Evidence

Optimization v2 does not re-extract L1 for Grace. It reads L1 from `share_mem/`. For ICSI, the extraction is upstream; v2 reads the effective L1 view. Still, the L2/L3 logic depends on the upstream L1 criteria, so the criteria are listed here.

An idea unit should become L1 only if it is:

- bounded by a clear evidence span;
- a specific claim rather than a vague paraphrase;
- useful beyond the current turn;
- not a duplicate of a stronger object;
- typed as one of the project-memory roles;
- important enough to retain or review.

### L1 role taxonomy

| L1 type | Keep when evidence shows |
|---|---|
| `decision` | A conclusion, adoption, rejection, or resolved policy that changes project state. |
| `action_item` | Work to be done, experiment to run, implementation task, check, or follow-up. |
| `open_issue` | Unresolved blocker, design question, research uncertainty, or pending decision. |
| `proposal` | Suggested option or hypothesis that has not yet been adopted. |
| `argument` | Reasoning, tradeoff, constraint, justification, or evidence interpretation. |
| `finding` | Stable observation, result, data-quality issue, failure mode, or literature finding. |
| `approach_change` | Adopted change in method, architecture, data handling, pipeline, or evaluation strategy. |

The type alone does not promote an object. For example, a sentence can be formatted like a decision but still be dropped if the evidence only shows a passing suggestion.

### What should not become L1

Usually drop or sidecar-review:

- greetings, filler, confirmations, and repeated acknowledgements;
- pure scheduling with no durable project implication;
- microphone/setup inventory unless it changes data-quality or corpus policy;
- source-file metadata with no research/process implication;
- one-off tool operations such as "press Control-C";
- vague summaries with no bounded claim;
- duplicated objects where another L1 covers the same evidence better;
- claims that sound strong but have no evidence of acceptance.

### Grace L1 examples

#### Example G1: idea-unit preprocessing became L1

L1:

```text
0422 / L1-0422-006
type = approach_change
importance = 0.70
```

Content:

> 為了取代逐「輪」(turn)更新記憶體的簡單作法，團隊探討了兩種新的方法來預處理逐字稿以生成「idea units」。第一種是迭代法：系統讀取固定行數的文本，並根據主題連續性逐步合併。第二種是預分割法：利用 LLM 判斷主題邊界，直接將文本分割成完整的 idea units。如果預分割法技術上可行，將不再需要迭代法。

Evidence excerpt:

> 「今天的逐字稿那我現在就要回去 update 我的 memory ... 可能不能用 turn ... 好幾個 turn 都在講同一件事情 ... 包成一個說好這是一個要 update 的節點」

Why it is L1:

- It changes the memory update unit from turn-level processing to idea-unit preprocessing.
- It has concrete alternatives: iterative merging vs pre-segmentation.
- It affects future pipeline design, not only this meeting.

Current v2 assignment:

```text
L2 = memory update
confidence = 0.95
rationale = shares recurring semantic key with 33 objects; related_topics is optional signal
```

#### Example G2: segment vs idea unit definition became L1

L1:

```text
0506 / L1-0506-002
type = decision
importance = 0.62
```

Content:

> 團隊已定義 `segment` 與 `idea unit` 之間的區別：`segment` 是指一個較廣泛的相關主題（例如，關於海報設計的討論），而 `idea unit` 則是該主題內一個更小、更具體的組成部分（例如，一個待辦事項或一項決策）。

Evidence excerpt:

> 「segment 會是一個相關的段落 ... idea unit 可能是裡面有講到 to-do 是什麼、decision 是什麼，就是比較細節的東西」

Why it is L1:

- It defines reusable terminology.
- It affects segmentation, L1 extraction, and later L2 construction.
- It is more than local discussion; it becomes part of system vocabulary.

Current v2 assignment:

```text
L2 = segmentation
confidence = 0.95
rationale = shares recurring semantic key with 16 objects
```

#### Example G3: bottom-up processing remained a proposal

L1:

```text
0506 / L1-0506-009
type = proposal
importance = 0.65
```

Content:

> 提出應考慮採用由下而上（bottom-up）的處理方法（從 idea unit 到主題），而非當前由上而下（top-down）的方法（從 segment 到 idea unit），因為前者被認為更自然。

Evidence excerpt:

> 「通常我們 theme 你去看 inductive coding 的話，它是從 idea units 然後找到一個 theme ...」

Why it is L1:

- It is a concrete alternative design direction.
- It is not marked as a final decision because the evidence frames it as a proposal/tradeoff.
- It becomes useful for later rationale questions about segmentation design.

Current v2 assignment:

```text
L2 = bottom up
confidence = 0.95
rationale = shares recurring semantic key with 12 objects
```

#### Example G4: full-transcript update was rejected

L1:

```text
0429 / L1-0429-122
type = approach_change
importance = 0.73
```

Content:

> 專案放棄了將完整逐字稿一次性提供給模型進行記憶更新的初始方法。原因是上下文長度過大，難以處理所需的 JSON 輸出格式，因此轉而採用分塊處理的策略。

Evidence excerpt:

> 「為什麼不要整個 transcription 直接進去 ... 我們一開始就是這樣子，但是 ... context 太大，因為我們一定要固定成 json」

Why it is L1:

- It records a rejected architecture and the reason for rejection.
- It explains why segmentation/chunking exists.
- It is central for answering "why not full transcript?" questions.

Current v2 assignment:

```text
L2 = update memory
confidence = 0.95
```

#### Example G5: manager-agent architecture became L1

L1:

```text
0429 / L1-0429-102
type = approach_change
importance = 0.72
```

Content:

> 系統架構被概念化為「manager-agent」模型。一個中央精簡的 manager 依序協調多個小型的專業 agent。每個 agent 都是特定任務的專家（例如，動態跳行、識別 idea units），並可維護自己的內部狀態或知識。

Evidence excerpt:

> 「有點像是說你可能有一個 manager 在這個地方，然後有一些小小的 agent 在處理一些不同的任務。」

Why it is L1:

- It is an architecture-level reframing.
- It affects decomposition, agent responsibilities, and maintainability.
- It can be referenced across later meetings.

Current v2 assignment:

```text
L2 = manager agent
confidence = 0.95
```

### Grace valid L1 that stays unlinked

Unlinked does not mean the L1 is wrong. It means v2 did not find enough evidence to create or assign a durable L2 safely.

#### Example G6: meeting transcript folder structure

L1:

```text
0307 / L1-0307-034
type = open_issue
importance = 0.54
```

Content:

> 團隊成員需要協調統一其資料檔案夾結構，以避免因多個組件都使用 `meeting_transcript` 而造成檔案重複的問題。

Why retained as L1:

- It is a real implementation coordination issue.
- It has clear evidence.

Why unlinked:

- Candidate topic `meeting transcript` is not durable enough by itself.
- It does not have enough recurring evidence to justify a full L2 topic.
- Forcing it into a broad "data" or "system" bucket would make L2 noisier.

#### Example G7: Whisper timestamp decision

L1:

```text
0506 / L1-0506-020
type = decision
importance = 0.64
```

Content:

> 決定目前系統在處理由 Whisper 依據語音停頓切分的逐字稿時，將依賴話語順序，而不使用 Whisper 可提供的時間戳記 (timestamps)。

Why retained as L1:

- It is a concrete decision about transcript handling.

Why review/unlinked:

- It could relate to data quality or segmentation, but the semantic assignment confidence is not high enough.
- v2 leaves it as review-only instead of silently attaching it to a broad topic.

---

## 4. ICSI Effective L1

ICSI BMR transcripts are different from Grace:

- English meeting transcripts.
- Many speaker IDs and ASR-style disfluencies.
- Many source-data/setup details.
- Many acoustic/corpus/process topics rather than memory-system topics.

For ICSI, the L1 extraction was intentionally somewhat broad. The downstream rule is:

```text
raw L1 can remain broad
effective L1 sidecar decides what L2/L3 should see
```

That means ICSI L2/L3 should read:

```text
memory_outputs/icsi/runs/bmr_full_completed29_eval_20260614/share_mem_effective
```

not the raw extraction folders.

### ICSI L1 examples

#### Example I1: annotation tool selection

L1:

```text
Bmr002 / L1-Bmr002-094
type = open_issue
importance = 0.68
```

Content:

> The project needs to select an annotation tool. Tools from Mississippi State and XWaves have been suggested as potential options, with XWaves noted as being low-level but potentially useful for marking speaker changes.

Evidence excerpt:

> "maybe we should look at the tools that Mississippi State has" ... "XWaves have some as well, but they're pretty low level"

Why it is L1:

- It records a concrete tool-selection issue.
- It affects transcription/annotation workflow.
- It recurs later through Transcriber, waveform display, Edit-key, and annotation workflow discussions.

Current v2 assignment:

```text
L2 = annotation tool
L3 = annotation and transcription workflow
confidence = 0.95
```

#### Example I2: Transcriber modification proposal

L1:

```text
Bmr010 / L1-Bmr010-039
type = proposal
importance = 0.67
```

Content:

> It was proposed that Dave Gelbart would modify the 'Transcriber' tool for the project's use, as it is considered a good option if no other tool is available.

Why it is L1:

- It is a concrete fallback proposal.
- It identifies a tool, a person, and a condition.

Current v2 assignment:

```text
L2 = dave gelbart
confidence = 0.95
```

This label is evidence-backed but probably less ideal for final presentation than a broader label such as `transcriber tool modification`. This is an example of why label-polish sidecars still matter.

#### Example I3: save distant microphone data

L1:

```text
Bmr024 / L1-Bmr024-097
type = approach_change
importance = 0.68
```

Content:

> A decision was made to save all recorded data, including from distant microphones, because it is potentially useful for future work and disk space is inexpensive.

Why it is L1:

- It changes corpus data-retention policy.
- It connects recording design, distant microphones, and disk-space assumptions.

Current v2 assignment:

```text
L2 = disk space
L3 = corpus design and data management
confidence = 0.95
```

#### Example I4: speaker location software responsibility

L1:

```text
Bmr001 / L1-Bmr001-052
type = open_issue
importance = 0.59
```

Content:

> Although speaker location detection has been proposed as a research angle and is considered feasible with the available data, it is unresolved who will write the necessary software to implement it.

Why it is L1:

- It is an unresolved responsibility/resource allocation issue.
- It connects research feasibility with implementation staffing.

Current v2 assignment:

```text
L2 = resource allocation
L3 = project planning and management
confidence = 0.95
```

#### Example I5: acoustic models for SmartKom

L1:

```text
Bmr002 / L1-Bmr002-197
type = decision
importance = 0.78
```

Content:

> The data collection effort is for the purpose of building general English acoustic models for the SmartKom project.

Why it is L1:

- It states a core corpus/data-collection purpose.
- It justifies why the meetings are being recorded and processed.

Current v2 assignment:

```text
L2 = acoustic modeling
L3 = asr modeling and evaluation
confidence = 0.95
```

---

## 5. L1 To Semantic Keys

The semantic key layer is the main reason v2 is less hardcoded than the old L2/L3 system.

Input signals:

```text
content
evidence
type
importance
related_topics
related_obj_ids
```

Output shape:

```json
{
  "obj_id": "L1-...",
  "semantic_facets": {
    "project_goal": [],
    "design_problem": [],
    "method_or_approach": [],
    "evaluation_or_validation": [],
    "implementation_workflow": [],
    "resource_or_constraint": [],
    "next_action": [],
    "unresolved_question": []
  },
  "candidate_terms": [],
  "source_signals": {
    "content": "...",
    "evidence": "...",
    "related_topics": []
  },
  "confidence": 0.0
}
```

Decision rules:

- Content and evidence are primary.
- `related_topics` is optional stabilizing signal.
- `related_topics` is not allowed to directly become the authoritative L2 label.
- Stopwords, speaker IDs, filler, weak fragments, type labels, and generic-only terms are filtered.
- Topic key language is profile-controlled.
- Grace profile can produce English topic keys from Chinese L1 content because English topic labels are easier to compare and retrieve.

Why this matters:

- Grace has terms like `manager agent`, `idea unit`, `segmentation`.
- ICSI has terms like `annotation tool`, `disk space`, `acoustic modeling`.
- The same code path should discover both from evidence instead of pushing ICSI into Grace memory-system topics.

---

## 6. Semantic Keys To L2

L2 is not a label pasted onto a single memory object. It is a durable topic that collects related L1 evidence.

Each L2 should have:

- `l2_id`
- `label`
- `definition`
- `inclusion_criteria`
- `exclusion_criteria`
- `linked_obj_ids`
- `assignment_rationale`
- `current_state`
- `evolution_summary`
- `confidence`
- `representative_l1_ids`

### L2 induction criteria

The deterministic L2 induction process considers:

1. repeated semantic key frequency;
2. phrase quality;
3. content/evidence support;
4. L1 importance;
5. cross-meeting recurrence;
6. whether the candidate is too generic;
7. whether the candidate is type-like;
8. whether assigning the L1 would create a noisy catch-all bucket.

Profile-level parameters include:

| Parameter | Meaning |
|---|---|
| `min_topic_evidence` | Minimum evidence count for ordinary durable topics. |
| `minimum_assignment_confidence` | Below this, assignment enters review/unlinked. |
| `high_importance_threshold` | Allows high-value singleton/review handling. |
| `max_l2_topic_share_before_specificity_penalty` | Penalizes labels that absorb too much corpus. |
| stopwords / artifact words | Dataset-specific filtering, not topic answers. |

### What L2 labels should not be

Reject or review:

- type-like labels: `decision`, `proposal`, `argument`, `finding`;
- generic-only labels: `data`, `system`, `topic`, `thing`, `process` alone;
- filler labels: `go ahead`, `did`, `didn`, `know`, `two`;
- artifact labels created by crossing stopword boundaries;
- labels unsupported by representative L1 evidence.

### Grace L2 examples

| L1 | L2 | Why |
|---|---|---|
| `L1-0422-006` | `memory update` | L1 discusses moving from turn-level memory update to idea-unit preprocessing. |
| `L1-0506-002` | `segmentation` | L1 defines segment vs idea unit terminology. |
| `L1-0506-009` | `bottom up` | L1 proposes bottom-up idea-unit-to-topic processing. |
| `L1-0429-102` | `manager agent` | L1 reframes architecture as manager-agent orchestration. |

### ICSI L2 examples

| L1 | L2 | L3 | Why |
|---|---|---|---|
| `L1-Bmr002-094` | `annotation tool` | `annotation and transcription workflow` | Tool-selection issue recurs across transcription/annotation workflow. |
| `L1-Bmr024-097` | `disk space` | `corpus design and data management` | Data retention policy depends on storage assumptions. |
| `L1-Bmr001-052` | `resource allocation` | `project planning and management` | The issue is who will implement speaker-location software. |
| `L1-Bmr002-197` | `acoustic modeling` | `asr modeling and evaluation` | Data collection goal is to build general English acoustic models. |

---

## 7. Why Some L1 Are Unlinked

Unlinked L1 is not automatically a failure.

Valid reasons:

| Reason | Meaning |
|---|---|
| `candidate_topic_not_durable_enough` | Candidate label exists but does not recur enough. |
| `singleton_l2_not_durable_enough` | Topic has only one L1 and does not justify a singleton L2. |
| `low_assignment_confidence` | Best topic assignment is below threshold. |
| `semantic_rescue_low_confidence_review` | Possible link exists, but system refuses to force it. |
| source-data/setup-only gate | Effective view suppresses raw L1 that should not become durable topic context. |

This is important because otherwise every valid local issue becomes an L2 topic, and L2 becomes a noisy index rather than long-term memory.

For ICSI full29, the effective run has:

```text
source effective L1 = 6,233
linked L1 = 6,203
unlinked L1 = 30
```

That means the current effective root is broad but mostly linkable. The remaining risk is not missing too many objects; the risk is topic-label quality and oversized topic presentation.

---

## 8. L2 To L3

L3 exists when L2 is too large or internally diverse.

Promotion criteria:

- enough linked L1 evidence;
- corpus-relative size pressure;
- meeting spread;
- separable subtopic entropy;
- child labels can be induced from evidence;
- child assignments cover source L1 exactly once;
- split improves retrieval/readability.

Do not promote when:

- child labels are generic or type-like;
- one child dominates and the split is cosmetic;
- children are too tiny;
- many source L1 would be unassigned or duplicated;
- split exists only because of hand-authored domain taxonomy.

### Grace L3

Grace runtime L3 has 3 parents:

```text
L3-literature-review
L3-memory-architecture
L3-data-quality
```

Example:

```text
L3-memory-architecture
  -> child L2: long term memory
  -> child L2: short term memory
```

Why:

- `memory architecture` has enough linked L1 to pressure retrieval.
- Evidence naturally separates long-term and short-term memory concerns.
- L3 lets retrieval include the right child L2 context rather than injecting the whole mixed parent.

### ICSI L3

ICSI raw materialized L3 has 65 parents. Runtime export compresses this into 6 corpus-theme L3 parents.

The runtime L3 examples include:

```text
annotation and transcription workflow
corpus design and data management
project planning and management
asr modeling and evaluation
audio acquisition and signal processing
speech and interaction analysis
```

Why compress runtime L3:

- A 6,233-L1 ICSI corpus produces many technically valid child topics.
- Exposing all raw L3 parents in retrieval would bloat traces and confuse demo navigation.
- Runtime L3 should be a navigation layer, not a complete ontology dump.

---

## 9. Runtime Export

Optimization v2 produces build artifacts and runtime artifacts.

Build artifacts:

```text
optimization/runs/<run_id>/l2/
optimization/runs/<run_id>/l3/
optimization/runs/<run_id>/validation/
```

Runtime artifacts:

```text
optimization/runs/<run_id>/runtime/l2/
optimization/runs/<run_id>/runtime/l3/
```

The runtime export is what a backend adapter should read. It can apply sidecar decisions such as:

- suppressed L2;
- relabeled L2;
- corpus-theme L3 compression;
- child-review adjustments.

This separation matters because raw build artifacts are useful for auditing, while runtime artifacts are optimized for retrieval/demo.

---

## 10. Retrieval Behavior

Current retrieval comparison uses no LLM. It measures evidence inclusion and topic hits.

ICSI revised held-out comparison:

```text
optimization/reports/icsi_bmr_full_completed29_system_comparison_revised_20260614/
```

| Strategy | Expected L1 recall | Avg context tokens | Avg selected L1 |
|---|---:|---:|---:|
| Full context L1 | 1.0 | 575,199.0 | 4,715 |
| RAG lexical top-20 | 0.5583 | 2,369.95 | 20 |
| Optimization v2 layered top-60 | 0.8958 | 7,358.35 | 60 |

v2 also achieved:

```text
expected L2 hit rate = 1.0
expected L2 semantic hit rate = 1.0
expected L3 hit rate = 1.0
expected L3 semantic hit rate = 1.0
```

### Token-budget decision

Sensitivity check:

| Layered top-k L1 | Expected L1 recall | Avg context tokens |
|---:|---:|---:|
| 20 | 0.5583 | 2,430.4 |
| 40 | 0.7958 | 4,920.5 |
| 60 | 0.8958 | 7,358.35 |
| 80 | 0.9083 | 9,717.25 |
| 100 | 0.9083 | 12,143.55 |

Decision:

```text
default layered_top_k_l1 = 60
```

Reason:

- top-60 preserves almost all top-80 recall;
- top-60 saves about 2.36k average context tokens compared with top-80;
- top-100 adds cost without recall gain;
- top-20 behaves too much like RAG and loses evidence.

### Interpretation

Full context is still inside Gemini 2.5 Pro style long-context capacity for the 29-meeting ICSI source-side L1 corpus. But it is not efficient:

- 575k input tokens per question is expensive and slow.
- The model still has to attend to a huge evidence set.
- Full context gives no explicit retrieval trace.

Optimization v2 is not claiming that full context cannot fit. The claim is:

```text
v2 gets most expected evidence and all expected topic structure using about 7.4k tokens,
while RAG is cheaper but misses much more evidence.
```

---

## 11. ICSI Evaluation Design

ICSI has no official question-answer benchmark like some memory datasets. The current evaluation is therefore a held-out future-meeting evidence benchmark.

Pipeline:

```text
source meetings through Bmr023
held-out trigger meetings after Bmr023
select topics that appear in source and reappear later
generate question from the topic
score using source-side expected L1, L2, L3
do not use held-out trigger L1 as answer evidence
```

The gold is not a hand-written prose answer. It is an expected evidence brief:

- expected source L1 IDs;
- expected L2 labels;
- expected L3 labels;
- source evidence previews;
- held-out trigger previews only to justify why the question is future-relevant.

Why this is defensible:

- It avoids inventing arbitrary professor-written answers.
- It tests whether the memory system retrieves the prior evidence needed for a future meeting.
- It can be manually audited because every expected ID points to a concrete L1 object.

Current revised pack:

```text
optimization/reports/icsi_bmr_full_completed29_eval_pack_revised_20260614/
```

Key revisions:

- 7 questions were rewritten from pre-review notes.
- q006 removed `L1-Bmr002-239` because it was process noise.
- q005 removed `L1-Bmr002-114` because it was only a narrow free-tool uncertainty rather than core annotation-tool workflow evidence.
- held-out trigger objects remain excluded from expected answer evidence.

Current result:

```text
20 revised held-out questions
avg expected L1 recall at top-60 = 0.8958
semantic L2 hit = 1.0
semantic L3 hit = 1.0
```

This is still not final answer-quality scoring. A paid LLM run would be required to compare generated answers from full context, RAG, and v2.

---

## 12. Validation Gates

Each v2 run should check:

- raw/effective L1 input hash exists and remains read-only;
- all linked L1 IDs exist;
- L2 labels are not type-like;
- L2 labels are not generic-only;
- high-importance unlinked L1 are explainable;
- `related_topics` is not the only assignment source;
- child L2 assignments do not duplicate or lose promoted L1;
- weak labels enter sidecar review;
- runtime export is explicit and separate from build artifacts;
- no generated output writes into canonical `share_mem/`, `long_term/l2`, or `long_term/l3`.

Current validation:

| Dataset | L2 severe | L2 warnings | L3 severe | L3 warnings |
|---|---:|---:|---:|---:|
| Grace latest | 0 | 2 | 0 | 2 |
| ICSI full29 | 0 | 9 | 0 | 9 |

The ICSI warnings are not ignored. They mean the full-scale topic view still needs label polish and some split/merge review before being called fully mature.

---

## 13. What Is Less Hardcoded Than The Old System

The old canonical L2/L3 path had several Grace-shaped assumptions:

- project-specific memory-system labels;
- `related_topics` doing too much work;
- handwritten child L2 taxonomy;
- topic rules that made sense for Grace but leaked into ICSI.

Optimization v2 changes this:

- L2 labels are induced from evidence-backed semantic keys.
- `related_topics` is optional stabilizer, not authority.
- L3 child labels are induced from parent evidence.
- Dataset-specific differences live in profile settings and sidecar review, not in hardcoded Grace topic maps.
- ICSI uses effective L1 and `isci_meeting.yaml`, not canonical Grace L2/L3.

This does not mean v2 supports every possible dataset. The intended domain is still mentor-mentee / research meetings. The goal is not maximum generality; the goal is defensible, evidence-backed decisions that do not look like cheating on Grace.

---

## 14. Known Limitations

1. L1 extraction quality still matters. v2 cannot fully fix bad L1.
2. ICSI full29 has many L2 topics because 6,233 L1 is much larger than Grace.
3. Some evidence-backed labels are still not presentation-friendly, e.g. a person-name label such as `dave gelbart`.
4. Runtime L3 compression is useful, but it is a design decision that should be documented in demos.
5. Current ICSI system comparison is no-LLM evidence comparison, not final answer scoring.
6. Full context still fits inside a long-context model for 29 ICSI meetings, so the claim should be efficiency/traceability, not impossibility.
7. v2 should be the default for new dataset L2/L3 work, but canonical replacement still requires explicit approval and runtime shadow QA.

---

## 15. Short Professor-Facing Explanation

中文：

> 我們不是直接把所有逐字稿丟進模型，也不是只做一般 RAG top-k chunk。系統先把會議內容整理成可追溯的 L1 evidence objects。L1 是回答的事實基礎。接著 optimization v2 從 L1 的 content 和 evidence 抽出 semantic keys，再把反覆出現且有長期價值的 keys 組成 L2 durable topics。如果某個 L2 太大，才會升成 L3 topic family，用來做導航和切分 child L2。回答時仍然先找 L1 evidence，再用 L2/L3 補上跨會議脈絡。L2/L3 不是憑空生成的 summary，而是由具體 L1 evidence 支撐的 sidecar view。

English:

> The system does not use raw transcript context as long-term memory. It first keeps bounded, evidence-backed L1 memory objects. Optimization v2 derives semantic keys from L1 content and evidence, induces durable L2 topics from recurring evidence-backed keys, and promotes oversized L2 topics into L3 topic families only when the evidence supports separable child topics. Retrieval remains evidence-first: L1 grounds the answer, while L2/L3 provide cross-meeting organization and navigation.

If asked why not just full context:

> For the current 29-meeting ICSI subset, full context can still fit in a long-context model, but it costs about 575k input tokens per question. Optimization v2 reaches 0.8958 expected L1 recall and 1.0 semantic L2/L3 hit with about 7.4k tokens. The point is not that full context is impossible; the point is that layered memory is cheaper, traceable, and organized.

If asked whether ICSI evaluation is official:

> ICSI does not provide official memory QA labels. We therefore use a held-out future-meeting evidence benchmark: later meetings trigger questions, but answers are scored only against source-side L1 evidence from earlier meetings. This is not a prose gold answer benchmark yet, but it is auditable because every expected answer point maps to source L1 IDs.

If asked whether v2 is already canonical:

> v2 is the recommended L2/L3 path for new datasets and ICSI work. It is still isolated from canonical runtime. Canonical replacement would require explicit approval after shadow-mode QA and answer-quality comparison.
