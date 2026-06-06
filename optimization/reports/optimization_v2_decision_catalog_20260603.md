# Optimization v2 Decision Catalog

Generated: 2026-06-03
Scope: isolated `optimization/long_term_v2` pipeline, using Grace as concrete examples

This report explains the current decision logic behind the optimization v2 memory view:

1. Which meeting idea units become L1 evidence objects, and which should not.
2. How L1 evidence objects become semantic keys.
3. How semantic keys are grouped into L2 durable topics.
4. Why some L1 objects remain unlinked.
5. How oversized L2 topics are promoted into L3 topic families and split into child L2 topics.
6. What validation exists to prevent Grace-specific hardcoding or unsupported topic formation.

Important boundary: optimization v2 does **not** re-extract L1 from transcripts. It reads existing `share_mem` L1 evidence as immutable input and builds an isolated L2/L3 view under `optimization/runs/<run_id>/`. The L1 criteria below describe the upstream evidence gate that produces the input optimization v2 consumes.

## Current Grace Optimization Snapshot

Reference run: `optimization/runs/grace_v2_det_rescue_20260529_065827`

| Item | Count |
| --- | ---: |
| Source L1 objects | 448 |
| Semantic key rows | 448 |
| L2 topics | 49 |
| Linked L1 | 440 |
| Unlinked L1 | 8 |
| L3 topic families | 3 |
| L3-assigned L1 | 72 |

The run is deterministic and isolated. It does not write to `share_mem/`, `long_term/l2/`, or `long_term/l3/`.

## End-To-End Flow

```text
Transcript
  -> bounded idea units / evidence spans
  -> L1 evidence object candidates
  -> L1 verifier + reducer + importance calibration
  -> immutable share_mem L1
  -> optimization semantic keys
  -> durable L2 topic induction and assignment
  -> adaptive L3 promotion if L2 is too large
  -> validation, manual review queues, retrieval eval
```

The design principle is evidence-first:

- L1 is the factual evidence unit.
- L2 is a durable topic / evolution context built from multiple L1.
- L3 is a navigation layer for oversized L2 topic families.
- L2/L3 never overwrite raw L1 evidence.

## 1. Idea Unit To L1: What Gets Promoted

An idea unit should become an L1 object when it is a bounded, evidence-backed piece of durable project memory. The L1 taxonomy is role-based:

| L1 type | Keep when the evidence shows |
| --- | --- |
| `decision` | An adopted, rejected, resolved, or materially revised conclusion that changes project state. |
| `action_item` | Explicit follow-up, experiment, implementation task, check, or assigned work with execution expectation. |
| `open_issue` | Unresolved blocker, design issue, uncertainty, research question, or decision point. |
| `proposal` | Suggested option, alternative, hypothesis, design, or plan not yet adopted. |
| `argument` | Reasoning, tradeoff, constraint, evidence interpretation, or justification. |
| `finding` | Stable observation, experiment result, comparison, data-quality finding, literature finding, or failure mode. |
| `approach_change` | Adopted change in method, process, architecture, retrieval strategy, schema, data handling, or evaluation approach. |

The type itself is not enough. A candidate also needs:

- A clear evidence span.
- A reusable project-memory value.
- A calibrated importance score above the retention threshold.
- No near-duplicate stronger object covering the same evidence.
- A bounded claim rather than a vague restatement of the conversation.

### Importance Gate

The upstream L1 importance scale is:

| Importance | Meaning |
| --- | --- |
| `0.90-1.00` | Project-level or cross-meeting decisions / method changes / approach changes. |
| `0.70-0.89` | Affects next research steps, experimental design, data quality, proposals, or unresolved blockers. |
| `0.50-0.69` | Useful meeting-level memory with clear follow-up value. |
| `0.35-0.49` | Weak but durable context; keep only if it may help later recall. |
| `0.00-0.34` | Local chatter, transient logistics, unsupported claims; discard as L1. |

Type floors prevent useful objects from being under-scored, but they do not promote low-value noise by type alone.

### Grace Review Reference Cards

The following compact cards are the common references used by the Grace examples below. Each card contains enough concrete content for manual review: meeting id, L1 id, L1 content, a short meeting evidence excerpt, and the current optimization result.

| Ref | Meeting / L1 | L1 content | Meeting evidence excerpt | Optimization result |
| --- | --- | --- | --- | --- |
| G1 | `0422 / L1-0422-006` | 為了取代逐「輪」更新記憶體，團隊探討兩種預處理逐字稿以生成 `idea units` 的方法：迭代合併與 LLM 預分割。 | 「今天的meeting完了我得到一個今天的逐字稿... 要回去update我的memory... 可能不能用turn，因為可能我們好幾個turn都在講同一件事情」 | L1 retained as `approach_change`; assigned to `L2-memory-update`. |
| G2 | `0506 / L1-0506-002` | 團隊定義 `segment` 是較廣泛的相關主題，`idea unit` 是其中更小、更具體的組成部分，例如待辦事項或決策。 | 「segment會是一個相關的段落... idea unit可能是裡面有講到... to-do... decision... 最小的單位都是idea units」 | L1 retained as `decision`; assigned to `L2-segmentation`. |
| G3 | `0506 / L1-0506-009` | 提出應考慮由下而上（bottom-up）的處理方法，從 idea unit 到主題，而非當前由上而下從 segment 到 idea unit。 | 「每一個idea units裡面它可能會有一些label... 現在可能是先從先去分theme然後再去切... inductive coding... 是從idea units」 | L1 retained as `proposal`; assigned to `L2-bottom-up`. |
| G4 | `0429 / L1-0429-122` | 專案放棄將完整逐字稿一次性提供給模型更新記憶，因為 context 太大且 JSON 輸出難處理，轉為分塊策略。 | 「為什麼不要整個transcription直接進去... 我們一開始就是這樣子... 第一個就是context太大，因為我們一定要固定成json」 | L1 retained as `approach_change`; assigned to `L2-update-memory`. |
| G5 | `0429 / L1-0429-102` | 系統架構被概念化為 manager-agent 模型，由精簡 manager 協調多個專業 agent。 | 「有點像是說你可能有一個 manager... 有一些小小的 agent 在處理一些不同的任務... 我預期它比較像就是個 manager」 | L1 retained as `approach_change`; assigned to `L2-manager-agent`. |
| G6 | `0307 / L1-0307-025` | 團隊需要確定如何評估記憶架構效能，並證明它優於標準 LLM。 | 「你們可能要看一下他們怎麼 evaluate... 也許已經有 dataset... 他們是怎麼證明 model performance 的？」 | L1 retained as `open_issue`; assigned to `L2-long-term-memory`. |
| G7 | `0307 / L1-0307-034` | 團隊成員需要統一資料夾結構，避免多個組件重複使用 `meeting_transcript` 造成檔案重複。 | 「你的格式要不要來跟我對一下... short term 裡面吃的是 meeting_recording 裡 transcript 的東西... 才不會有兩份 meeting transcript」 | L1 retained but unlinked; reason `singleton_l2_not_durable_enough`. |
| G8 | `0506 / L1-0506-020` | 系統處理由 Whisper 依語音停頓切分的逐字稿時，決定依賴話語順序，不使用 timestamps。 | 「這個segment它是針對錄音檔的segment對不對... label都是針對idea units... 它會屬於某個segment... 中間是有relationship」 | L1 retained but review-only; reason `semantic_rescue_low_confidence_review`. |
| G9 | `0408 / L1-0408-011` | 應取得另一團隊的 idea-unit 分割 recipe，並評估是否能用於中文會議記錄。 | 「它最後 L1 的結構是什麼？... 我們怎麼 partition？... prompt 怎麼做？... 改成自己先做 partition」 | L1 retained as `action_item`; assigned to `L2-prompt-engineering`. |
| G10 | `0307 / L1-0307-028` | 因為評估是關鍵挑戰，團隊應研究參考論文如何評估模型，可能有可用資料集或標準化測試。 | 「你們可能要看一下他們怎麼 evaluate... 也許已經有 dataset... 除了提出架構之外，他們是怎麼證明 model performance 的？」 | L1 retained as `argument`; assigned to `L2-literature-review`. |
| G11 | `0307 / L1-0307-010` | 長期記憶應是獨立、粗粒度結構，用來追蹤研究專案長期發展弧線、目標和主題。 | 「research meeting 會持續一年... 可能要用另一個架構，比較粗略地抓整個研究脈絡... long term 應該主要會是... 架構變化、研究目標、整個主題」 | L1 retained as `action_item`; assigned to `L2-memory-architecture`. |
| G12 | `0307 / L1-0307-039` | 確認本次會議錄音為部分錄音，從討論中研院實習議題時才開始。 | 「我剛剛有一部錄影... 不過是從你們講中研院之後開始」 | L1 retained as `finding`; assigned to `L2-data-quality`. |

### Grace Examples: Promoted To L1

| Ref | L1 | Why it becomes L1 |
| --- | --- | --- |
| G1 | `L1-0422-006` | `approach_change`, importance `0.70`. The team changed from turn-based update to idea-unit preprocessing. |
| G2 | `L1-0506-002` | `decision`, importance `0.62`. The team defined reusable terminology for `segment` and `idea unit`. |
| G3 | `L1-0506-009` | `proposal`, importance `0.65`. Bottom-up processing was proposed but not yet adopted. |
| G4 | `L1-0429-122` | `approach_change`, importance `0.73`. The team abandoned full-transcript one-shot update and moved toward chunking. |
| G5 | `L1-0429-102` | `approach_change`, importance `0.72`. The architecture was reframed as a manager-agent model. |
| G6 | `L1-0307-025` | `open_issue`, importance `0.64`. The team still needed an evaluation method for memory architecture. |

### What Should Not Become L1

These should generally be dropped before L1:

- Greetings, acknowledgements, filler, or repeated confirmations.
- Pure scheduling or meeting logistics with no lasting project implication.
- One-off setup inventory, microphone checks, channel configuration, or source-file metadata, unless it changes a reusable data-quality policy.
- Unbounded summaries that do not make a specific claim.
- Duplicate objects from the same evidence that answer the same durable question.
- Surface wording that looks important but does not prove adoption. For example, a phrase like "considered" or "suggested" is not enough to call something a decision.

For ICSI-style transcripts, the gate is stricter about setup/source-data-only content. For Grace, most kept L1 objects are research decisions, proposals, arguments, findings, approach changes, or action items.

## 2. L1 To Semantic Keys

Optimization v2 adds a semantic key layer between raw L1 and L2 topics. This is the main change from the older `related_topics`-driven approach.

Input signals:

- `content`
- `evidence`
- `type`
- `importance`
- `related_topics`
- `related_obj_ids`

Output:

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

Decision criteria:

- Content/evidence terms are primary.
- `related_topics` are optional stabilizing signals, not direct L2 labels.
- Topic keys are English in the mentor-mentee profile, even when L1 content is Traditional Chinese.
- Stopwords, speaker IDs, filler, type-like labels, generic single words, and obvious artifacts are filtered.
- Semantic facets provide an interpretable reason for why a term matters.

### Grace Examples: Semantic Keys

| Ref | L1 | Useful semantic signals |
| --- | --- | --- |
| G2 | `L1-0506-002` | `segmentation`, `idea unit`, `data model`, `terminology`. |
| G3 | `L1-0506-009` | `bottom up`, `top down`, `idea unit`, `segmentation`. |
| G5 | `L1-0429-102` | `manager agent`, `modularity`, `agent architecture`. |
| G6 | `L1-0307-025` | `evaluation`, `benchmarking`, `model performance`, `long term memory`. |

Why this matters: if a future dataset has different topic vocabulary, v2 should still form semantic keys from the evidence text rather than forcing Grace's old topic labels.

## 3. Semantic Keys To L2

An L2 is a durable topic, not an L1 type and not a one-off memory object.

Each L2 must have:

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

### L2 Label Selection

The deterministic topic induction process scores candidate labels by:

1. Repeated appearance across L1 evidence.
2. Specific phrase quality.
3. Whether the term appears in content/evidence/facets.
4. Importance of linked L1 objects.
5. Penalty for overly broad labels that absorb too much of the corpus.
6. Rejection of type-like or generic labels.

Profile defaults:

- `min_topic_evidence = 4`
- `minimum_assignment_confidence = 0.25`
- `high_importance_threshold = 0.70`
- `max_l2_topic_share_before_specificity_penalty = 0.18`
- Single-meeting topics are allowed only when evidence is high-impact enough.

### Assignment Criteria

An L1 is linked to an L2 if:

- It shares a recurring semantic key with enough other L1 objects.
- Assignment confidence passes the threshold.
- The topic is durable enough to be useful as long-term memory.
- The label is not a type-like label such as `decision`, `proposal`, `argument`, or `open issue`.
- The label is not a generic-only bucket such as `memory`, `system`, `data`, `topic`, or `discussion`.

### Grace Examples: L1 Assignment To L2

| Ref | L1 | Assigned L2 | Why |
| --- | --- | --- | --- |
| G1 | `L1-0422-006` | `L2-memory-update` | Captures the shift toward idea-unit preprocessing for memory updates. |
| G2 | `L1-0506-002` | `L2-segmentation` | Defines segment vs idea unit, directly supporting segmentation. |
| G3 | `L1-0506-009` | `L2-bottom-up` | Repeats with other top-down/bottom-up tradeoff objects. |
| G4 | `L1-0429-122` | `L2-update-memory` | Abandons full-transcript memory update and moves to chunking. |
| G5 | `L1-0429-102` | `L2-manager-agent` | Shares manager-agent architecture and modularity signals. |
| G9 | `L1-0408-011` | `L2-prompt-engineering` | Evaluates another team's prompt-engineering recipe for idea-unit segmentation. |

### Example L2 Topics In Grace

| Ref | L2 | Linked L1 count | Interpretation |
| --- | --- | ---: | --- |
| G10 | `L2-literature-review` | 26 | Literature search, paper positioning, and dataset/paper review work. |
| G11 | `L2-memory-architecture` | 25 | Long-term/short-term memory architecture and project-level memory design. |
| G12 | `L2-data-quality` | 21 | Data quality, transcription/data-source issues, and evidence reliability. |
| G1 | `L2-memory-update` | 15 | How memory is updated from transcript evidence. |
| G3 | `L2-bottom-up` | 12 | Bottom-up vs top-down transcript/idea-unit processing. |
| G5 | `L2-manager-agent` | 12 | Manager-agent orchestration and modular architecture. |

## 4. Why Some L1 Remain Unlinked

Unlinked does not mean the L1 is wrong. It means optimization v2 did not find enough durable topic evidence to place it in L2 safely.

Main unlink reasons:

| Reason | Meaning |
| --- | --- |
| `candidate_topic_not_durable_enough` | The candidate label did not recur enough and the L1 was not high-impact enough to justify a singleton topic. |
| `singleton_l2_not_durable_enough` | The candidate topic had only one L1 and did not pass the high-importance exception. |
| `low_assignment_confidence` | The best assignment score was below the profile threshold. |
| `semantic_rescue_low_confidence_review` | A possible rescue link existed, but confidence was low, so the object is left for manual review. |

### Grace Examples: Unlinked L1

| Ref | L1 | Candidate | Reason | Interpretation |
| --- | --- | --- | --- | --- |
| G7 | `L1-0307-034` | `meeting transcript` | `singleton_l2_not_durable_enough` | Valid implementation issue, but not enough recurring evidence to become an L2. |
| G8 | `L1-0506-020` | `data quality` | `semantic_rescue_low_confidence_review` | Possibly related to data quality, but assignment confidence is too low, so it remains review-only. |

This conservative unlinking is intentional. Long-term L2 should not become a bucket for every valid L1.

## 5. L2 To L3: When A Topic Is Promoted

L3 is a topic-family navigation layer. It is created only when an L2 becomes too large or too internally diverse for prompt-efficient retrieval.

Promotion uses adaptive thresholds:

- Minimum absolute threshold: `10`.
- Target child L2 size range: `6-20`.
- For larger corpora, threshold is based on corpus distribution and target child size.
- In the Grace run, the adaptive promotion threshold was `20`.

An L2 is considered for L3 if:

- It has enough linked L1 objects.
- It spans enough evidence to pressure retrieval prompt size.
- It contains separable subtopics.
- Child split labels can be induced from evidence-backed terms.
- Child assignments can cover the source L2 without duplicate or missing promoted L1.

An L2 is **not** promoted if:

- The split would create mostly empty or tiny children.
- One child would dominate and the split would not improve coherence.
- Child labels are generic, type-like, artificial n-grams, or unsupported.
- The system cannot assign source L1 exactly once.

## 6. How L3 Splits The Original L2

Optimization v2 does not use a hardcoded child taxonomy such as "transcript segmentation must split into fixed chunking / boundary selection / idea-unit generation."

Instead, it:

1. Reads the parent L2's linked L1 evidence.
2. Extracts candidate child labels from top semantic terms and timeline summaries.
3. Filters weak/generic/type-like labels.
4. Chooses child labels based on separability and target child size.
5. Assigns each source L1 to exactly one child.
6. Produces merge/split review sidecars for tiny or oversized children.

### Grace Examples: L3 Promotions

| Ref | L3 parent | Source L2 | Child L2 | Child counts | Why it was split |
| --- | --- | --- | --- | ---: | --- |
| G10 | `L3-literature-review` | `L2-literature-review` | `google scholar`, `speech annote test` | 15, 11 | Literature review evidence separated into search/paper discovery and speech annotation test/data work. |
| G11 | `L3-memory-architecture` | `L2-memory-architecture` | `long term memory`, `short term memory` | 15, 10 | Memory architecture discussions naturally separated into long-term and short-term memory concerns. |
| G12 | `L3-data-quality` | `L2-data-quality` | `segment start time`, `voice conversion` | 10, 11 | Data-quality evidence separated into timing/segment metadata and voice-conversion/transcription issues. |

The original source L2 is not deleted from the evidence record. L3 materialization creates a sidecar view for navigation and retrieval.

## 7. Validation And Review Gates

Optimization v2 emits validation reports for each run:

```text
validation/
  l1_input_audit.json
  semantic_key_validation.json
  l2_validation_report.json
  l3_validation_report.json
  manual_review_queue.json
  explainability_report.md
```

Core validation checks:

- Raw L1 input hash is unchanged.
- Every linked topic assignment references an existing `obj_id`.
- `related_topics` is not the only assignment source.
- L2 labels are not type-like.
- L2 labels are not generic-only buckets.
- L2 assignments have rationale.
- High-importance unlinked L1 enter manual review.
- Promoted L3 source L1 are assigned exactly once to child L2.
- Tiny child L2 enter merge review.
- Oversized child L2 enter split review.
- LLM-assisted proposals must cite representative L1 ids and pass validation before any candidate application.

## 8. Why This Is Less Hardcoded Than The Previous L2/L3 System

The older canonical L2/L3 system had several Grace-specific parts:

- Hardcoded label maps around memory architecture topics.
- Handwritten child L2 taxonomy for known oversized Grace topics.
- `related_topics` carried too many roles: metadata, assignment seed, and retrieval cue.

Optimization v2 changes this:

- Semantic keys are extracted from content/evidence first.
- `related_topics` is optional and stabilizing, not authoritative.
- L2 labels are induced from repeated evidence-backed terms.
- L3 children are induced from parent evidence, not handwritten topic lists.
- Dataset/profile settings control language, stopwords, noise policy, and thresholds, not project-specific answers.

This does not make v2 universally general. The target domain remains mentor-mentee / research meetings. But the decision logic is defensible because labels and splits must be traceable to evidence.

## 9. Known Limitations

Current status: mature isolated experiment direction, not canonical promotion.

Known limitations:

- Optimization v2 does not solve L1 extraction itself; it depends on upstream `share_mem` L1 quality.
- Some deterministic L2 labels can still be unintuitive when lexical recurrence dominates, so manual review remains necessary.
- `related_topics` ablation works, but quality drops: this confirms `related_topics` is useful as a stabilizer even though it is not required.
- LLM-assisted topic induction is proposal/review-first; it is not yet allowed to overwrite deterministic assignment without validation.
- Promotion requires repeated isolated runs and answer-quality gates before runtime adoption.

## 10. Professor-Facing Explanation

## 10A. 中文 Grace 範例補充

以下範例直接取自 Grace 系列的 L1 內容與 optimization v2 assignment，方便報告時用中文說明。

### 範例一：idea unit 為什麼會升成 L1

`L1-0422-006`

L1 content:

> 為了取代逐「輪」(turn)更新記憶體的簡單作法，團隊探討了兩種新的方法來預處理逐字稿以生成「idea units」。第一種是迭代法：系統讀取固定行數的文本，並根據主題連續性逐步合併。第二種是預分割法：利用 LLM 判斷主題邊界，直接將文本分割成完整的 idea units。如果預分割法技術上可行，將不再需要迭代法。

Meeting evidence excerpt:

> [SPEAKER_00]: 如果假設說好現在我要我們現在今天的meeting完了我得到一個今天的逐字稿，那我現在就要回去update我的memory對不對... 可能不能用turn，因為可能我們好幾個turn都在講同一件事情... [SPEAKER_02]: Long-term 跟 Short-...

判定：

- `type = approach_change`
- `importance = 0.70`
- 這不是普通聊天，因為它改變了「逐字稿如何進入記憶更新 pipeline」。
- 它有明確 evidence、可追蹤到會議、且會影響後續系統設計，所以升成 L1。

`L1-0506-002`

L1 content:

> 團隊已定義 `segment` 與 `idea unit` 之間的區別：`segment` 是指一個較廣泛的相關主題（例如，關於海報設計的討論），而 `idea unit` 則是該主題內一個更小、更具體的組成部分（例如，一個待辦事項或一項決策）。

Meeting evidence excerpt:

> [SPEAKER_01]: segment會是一個相關的段落，就是他都在討論這件事情，那idea unit可能是裡面有講到裡面可能to-do是什麼、decision是什麼，就是比較細節的東西... [SPEAKER_02]: 最小的單位都是idea units...

判定：

- `type = decision`
- `importance = 0.62`
- 它定義了系統後續會反覆使用的核心術語，所以是 durable memory。
- 如果這段沒有被保留，後面討論 L1/L2、segmentation、idea unit 時會失去共同語境。

### 範例二：L1 怎麼群聚成 L2

`L1-0506-002 -> L2-segmentation`

- L1 內容在定義 `segment` 和 `idea unit`。
- optimization v2 抽出的語意訊號包含 `segmentation`、`idea unit`、`terminology`。
- 因為 `segmentation` 不是只出現一次，而是和多個 L1 形成 recurring semantic key，所以被群聚成 `L2-segmentation`。

`L1-0506-009 -> L2-bottom-up`

L1 content:

> 提出應考慮採用由下而上（bottom-up）的處理方法（從 idea unit 到主題），而非當前由上而下（top-down）的方法（從 segment 到 idea unit），因為前者被認為更自然。

Meeting evidence excerpt:

> [SPEAKER_02]: 我們說每一個idea units裡面它可能會有一些label... 它有可能是theme是什麼... 然後我們現在可能是先從先去分theme然後再去切... inductive coding的話他是從idea units然後他找到...

判定：

- 這是 `proposal`，不是 `decision`，因為內容是「提出應考慮」，不是已採納。
- 語意訊號包含 `bottom up`、`top down`、`idea unit`、`segmentation`。
- Grace 中有多個 L1 都在討論 bottom-up vs top-down 的 tradeoff，所以形成 `L2-bottom-up`。

`L1-0429-122 -> L2-update-memory`

L1 content:

> 專案放棄了將完整逐字稿一次性提供給模型進行記憶更新的初始方法。原因是上下文長度過大，難以處理所需的 JSON 輸出格式，因此轉而採用分塊處理的策略。

Meeting evidence excerpt:

> [SPEAKER_02]: 為什麼不要整個transcription直接進去跟他說你把所有的需要update的memory都改一改？ [SPEAKER_00]: 我們一開始就是這樣子，但是這樣有幾個問題，第一個就是context太大，因為我們一定要固定成json...

判定：

- 這是 `approach_change`，因為系統不再使用 full transcript one-shot update。
- 它和其他 memory update / chunking / context window 的 L1 共同支撐 `L2-update-memory`。
- 這個 L2 的意義不是「某一場會議的一句話」，而是「記憶更新方法如何演變」。

### 範例三：哪些 L1 不連到 L2，為什麼

`L1-0307-034`

L1 content:

> 團隊成員需要協調統一其資料檔案夾結構，以避免因多個組件都使用 `meeting_transcript` 而造成檔案重複的問題。

Meeting evidence excerpt:

> [SPEAKER_01]: 你的格式要不要來跟我對一下？... 我現在在 app 同層建 short term，short term 裡面吃的是 meeting_recording 裡 transcript 的東西... 我們才不會有兩份 meeting transcript 之類的。

判定：

- 這是有效 L1，因為它記錄了一個實作上的 open issue。
- 但 candidate topic `meeting transcript` 只有 singleton evidence，不足以形成 durable L2。
- 所以 optimization v2 保留 L1，但不強行建立 L2，理由是 `singleton_l2_not_durable_enough`。

`L1-0506-020`

L1 content:

> 決定目前系統在處理由 Whisper 依據語音停頓切分的逐字稿時，將依賴話語順序，而不使用 Whisper 可提供的時間戳記 (timestamps)。

Meeting evidence excerpt:

> [SPEAKER_02]: 這個segment它是針對錄音檔的segment對不對？... label都是針對idea units... 它會屬於某個segment... 中間是有relationship的...

判定：

- 這是有效 L1，因為它記錄了 transcript handling 的決策。
- 它可能屬於 `data quality`，但 assignment confidence 不夠穩定。
- 系統把它放進 review queue，而不是硬塞進 `L2-data-quality`，理由是 `semantic_rescue_low_confidence_review`。

這裡可以跟教授說：unlinked 不是丟掉 evidence，而是不讓 L2 被低信心或一次性內容污染。

### 範例四：L2 怎麼升成 L3

`L2-memory-architecture`

- linked L1 count = `25`
- Grace reference run 的 L3 promotion threshold = `20`
- 這個 L2 太大，且內部自然分成 long-term memory 和 short-term memory 兩條線。

因此升成：

```text
L3-memory-architecture
  -> L2-memory-architecture-long-term-memory   15 L1
  -> L2-memory-architecture-short-term-memory  10 L1
```

判定理由：

- 原本的 `L2-memory-architecture` 太寬，如果 retrieval 時整包放進 prompt，會混入太多不同脈絡。
- 拆成 child L2 後，query 問 long-term memory 時可以優先展開 long-term memory child；問 short-term memory 時可以展開 short-term memory child。
- L3 本身不是答案來源，而是導航層。

`L2-data-quality`

```text
L3-data-quality
  -> L2-data-quality-segment-start-time  10 L1
  -> L2-data-quality-voice-conversion    11 L1
```

判定理由：

- `data quality` 包含不同種類的資料品質問題。
- Grace evidence 顯示它可以拆成 segment/time metadata 與 voice conversion/transcription 兩個方向。
- 這不是手寫 taxonomy，而是從 parent L2 的 evidence term 和 timeline summary 產生 child labels。

### 可以口頭講的中文版本

> 例如 Grace 裡 `L1-0506-002` 定義了 segment 和 idea unit 的差別，所以它被保留成 L1，並被連到 `L2-segmentation`。但像 `L1-0307-034` 這種資料夾命名協調，雖然是有效 L1，卻沒有足夠 recurring evidence 形成長期 topic，所以不會硬建立 L2。再往上，如果某個 L2 太大，例如 `memory architecture` 有 25 個 L1，系統會把它升成 L3，並拆成 `long term memory` 和 `short term memory` 兩個 child L2，讓 retrieval 不需要整包塞進 prompt。

Short version:

> We do not directly use every transcript sentence as long-term memory. We first keep only evidence-backed L1 objects: decisions, actions, issues, proposals, arguments, findings, and approach changes. Then optimization v2 converts L1 into semantic keys derived primarily from content and evidence. Repeated and durable semantic keys become L2 topics. Oversized L2 topics become L3 topic families only if the evidence supports separable child topics. All assignments have rationale, all raw L1 evidence remains immutable, and uncertain cases are left as review sidecars rather than silently forced into topics.

If asked why some L1 are unlinked:

> Unlinked means the object may still be valid L1 evidence, but it does not yet have enough repeated or high-confidence evidence to become long-term topic context. This prevents L2 from becoming a noisy bucket. High-importance unlinked objects are sent to manual review instead of being ignored.

If asked why L3 exists:

> L3 is not another answer source. It is a navigation layer used when an L2 topic becomes too large. It lets retrieval expand the right child L2 rather than injecting a huge mixed topic into the prompt.

If asked whether this is Grace-specific:

> Grace terms may appear in labels because they appear in Grace evidence. But optimization v2 does not hardcode Grace's topic map or child taxonomy in the core logic. Dataset-specific behavior should live in profiles, and every L2/L3 label must be backed by representative L1 evidence.
