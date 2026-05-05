# Long-Term Multi-Agent L1 架構說明

這份文件整理目前 `long_term/` 的 multi-agent L1 萃取流程，目標是讓開發者可以快速回答三個問題：

1. 現在每個環節各自負責什麼。
2. 這版設計還缺哪些關鍵閉環。
3. 接下來應該先補哪些代辦。

本文只描述 `--mode multi-agent` 的 L1 萃取路徑。L2 / L3 目前仍沿用既有 `summarize phase` / `summarize profile`。

## 1. 系統定位

目前的 long-term multi-agent 不是整個 long-term 系統重寫，而是把「單場 transcript 如何變成 L1 memory objects」從 monolithic prompt 改成顯式多階段 pipeline。

整體定位如下：

- `full` / `monolithic`：既有 baseline，整份 transcript 直接抽 L1。
- `incremental`：Gemini function-calling 逐段讀取 transcript，產出 L1。
- `multi-agent`：研究版 L1 pipeline，保留中介 artifact、局部責任邊界與後段驗證。

multi-agent 的核心目標不是只追求抽得更多，而是讓流程具備：

- bounded scope
- artifact traceability
- local deterministic checks
- failure localization

## 2. 高階流程

目前 `multi_agent` 的 L1 主流程是：

`context_planner -> segmentation_agent -> segment_coverage_validator/repair -> segment_coarsening -> idea_unit_agent -> idea_unit_quality_validator/repair/coverage-fallback/compaction -> continuation_merge -> bounded l1_decision/todo/method_change/result_agent -> optional fallback_l1_agent -> evidence_grounding_agent -> cross_type_conflict_resolver -> verify_l1_candidates -> reduce_l1_patch/type-calibration/viewpoint-recurrence -> persist_l1`

入口在 `long_term/bridge.py`。當 `--mode multi-agent` 被指定時，bridge 會呼叫 `run_multi_agent_l1_pipeline()`，最後仍把結果寫回同一個 `tree.json` meeting node。

## 3. 模組分工

### 3.1 Bridge 入口

檔案：`long_term/bridge.py`

責任：

- 提供 `--mode multi-agent`
- 解析 transcript / meeting metadata
- 呼叫 `run_multi_agent_l1_pipeline()`
- 把 final meeting node 插入既有 `tree.json`
- 保留和既有 L2 / L3 summarize 相容

設計重點：

- multi-agent 不是獨立儲存系統，而是新的 L1 producer。
- canonical storage 仍是 `tree.json`。

### 3.2 Context Planner

檔案：`long_term/multi_agent_agents.py`

函式：`plan_context_windows(...)`

責任：

- 把 transcript 轉成 deterministic windows
- 決定每輪 segmentation 的 primary window
- 讓整個 pipeline 的全域座標固定

現在做法：

- 固定 `window_size`
- 固定 `lookback_lines`
- 固定 `lookahead_lines`
- `start = end + 1` 線性往前推

設計理由：

- 避免上游 segmentation 反過來改變整條 pipeline 的切窗基準
- 方便比較不同 prompt / verifier 版本
- 降低 error propagation

限制：

- 這層不懂語意，只負責固定工作面
- 固定 window 本身不是語義邊界，仍需要 downstream 補救

### 3.3 Segmentation Agent

檔案：`long_term/multi_agent_agents.py`

函式：`segmentation_agent(...)`

責任：

- 在單一 primary window 內切出 topic-coherent segments
- 為每個 segment 給出 `topic_label`
- 判斷 `needs_more_context`

輸出：`SegmentProposal`

欄位：

- `segment_id`
- `line_start`
- `line_end`
- `topic_label`
- `needs_more_context`

設計理由：

- 把語義切段責任集中在單一 stage
- 讓 downstream 不再直接重讀 transcript 做自由切分

目前限制：

- segment 會被 clamp 回 primary window
- 語義切段本身仍由 LLM 決定，因此仍可能切得太粗或太碎

### 3.3.1 Segment Coverage Validator / Repair

檔案：`long_term/multi_agent_validators.py`

函式：`repair_segment_coverage(...)`、`coarsen_segments_for_window(...)`

責任：

- 檢查每個 primary window 內哪些 transcript lines 被 segment 覆蓋
- 記錄 uncovered ranges / overlap ranges
- 對 uncovered ranges 補 deterministic fallback segment
- repair segment 會借用鄰近 segment topic，並標記 `needs_more_context`
- 將過碎的相鄰 segments 合併成 durable segments，避免 80 行內容被切成十幾個 micro-batches

設計理由：

- 防止 segmentation 漏行後，下游 idea unit / L1 agent 完全看不到內容
- repair segment 仍使用原始 line range，不改動 canonical transcript 座標
- repair segment 後續仍可被 continuation merge 接回相鄰語意 batch
- coarsening 讓 downstream idea unit / L1 agents 看到較完整的討論範圍

輸出 artifact：

- `segment_coverage_validation.json`
- `segment_coarsening.json`

### 3.4 Continuation Merge

檔案：`long_term/multi_agent_pipeline.py`

函式：`build_continuation_batches(...)`

責任：

- 消費 `needs_more_context`
- 把相鄰 segments 合成 bounded extraction batch
- 為下游 type agents 定義真正的 extraction scope

目前 merge 條件：

- 相鄰
- 至少一側 `needs_more_context`，且 topic 相似，或左側已明確要求延續
- 或者跨 primary window 邊界且 topic、邊界 transcript text、或相鄰 idea units 的相似度足夠高

輸出 artifact：

- `continuation_merges.json`
- `extraction_batches.json`

設計理由：

- 把跨窗補救明確化，而不是讓 segmentation 直接輸出跨窗 segment
- 保留固定窗口的穩定性，同時補償邊界語意截斷
- 對 topic label 不一致但邊界內容仍連續的情況，仍可合併成同一個 extraction batch

目前限制：

- merge 只負責把相鄰 segment 變成 extraction batch
- 漏行補救由前一層 segment coverage validator 負責

### 3.5 Idea Unit Agent

檔案：`long_term/multi_agent_agents.py`

函式：`idea_unit_agent(...)`

責任：

- 把單一 segment 轉成較小的共享 idea units
- 提供所有 type agents 共用的中介表示
- 不在這一層做 type classification

輸出：`IdeaUnit`

欄位：

- `unit_id`
- `segment_id`
- `line_start`
- `line_end`
- `text`
- `completeness`
- `uncertainty_note`

設計理由：

- 先把 transcript abstraction 做成共享底座
- 避免每個 type agent 各自重新 invent segmentation
- 保持中介表示小、局部、可引用

為什麼不是直接對 batch 抽 idea units：

- batch 是 extraction scope，不是最小表示單位
- 直接對 batch 抽 unit 容易產生過胖、混合多語義的大 unit
- segment-level unit 比較容易追責與做 local grounding

目前限制：

- `completeness` / `uncertainty_note` 目前只記錄，不影響 acceptance

### 3.5.1 Idea Unit Quality Validator / Repair

檔案：`long_term/multi_agent_validators.py`

函式：`repair_idea_units_for_segment(...)`

責任：

- 檢查 idea unit 是否空白、超出 segment、過胖、過短、過長、或高度重疊
- 對超出 segment 的 unit 做 line bound clamp
- 對過胖 unit 用原 transcript lines 拆成 bounded fallback chunks
- 如果某個 segment 完全沒有可用 unit，補 fallback idea unit
- 如果某些 segment lines 沒被任何 idea unit 覆蓋，補 transcript-based fallback unit
- idea-unit agent 仍被要求最多輸出 8 個 units，但 validator 補漏後允許最多 12 個 units
- 只有超過 validator 上限時才做 deterministic compaction，避免把不同觀點硬壓進同一個 unit
- compaction 會優先維持每個 idea unit 不超過 8 行，避免補漏後又產生過胖 unit

設計理由：

- 避免 type agents 吃到過胖或重複的中介表示
- 讓 representation 問題在進入 L1 typed extraction 前就被記錄與補救
- 防止逐句 idea unit 被逐一升級成 L1 objects
- 防止重要 transcript lines 在 segment 已覆蓋的情況下，仍因 idea-unit abstraction 被下游看不見

輸出 artifact：

- `idea_unit_quality_validation.json`

### 3.6 Typed L1 Agents

檔案：`long_term/multi_agent_agents.py`

函式：`l1_type_agent(...)`

目前實作類型：

- `decision`
- `todo`
- `method_change`
- `result`

責任：

- 只在單一 extraction batch 內提 candidate
- 每個 agent 只做自己的 operational type
- 允許同一 idea unit 支持多個 type

現在的 bounded 機制：

- prompt 只看到 batch 內的 idea units
- candidate 保存 `extraction_scope`
- candidate 保存 `segment_ids`
- 程式端用 `allowed_unit_ids` 白名單過濾 `source_unit_ids`
- 每個 batch/type 最多保留 2 個候選，並依 importance / confidence 排序取前段

設計理由：

- 真正把 type agent 從 monolithic transcript reader 變成 bounded extractor
- 讓 candidate 可以回溯到具體 batch 與 segment

目前限制：

- `open_question` / `argument` 尚未接進 multi-agent loop
- 目前只在「整個 batch 沒有任何 typed candidate」時跑一次 general fallback

### 3.6.1 Fallback L1 Agent

檔案：`long_term/multi_agent_agents.py`

函式：`l1_fallback_agent(...)`

責任：

- 當 decision / todo / method_change / result 四個 typed agents 對同一 batch 都沒有產出時，做一次保守的 general L1 檢查
- 只允許輸出既有四個 multi-agent L1 類型
- 仍受 `source_unit_ids` 白名單限制，不能引用 batch 外內容

設計理由：

- 避免「有內容但剛好每個 typed agent 都沒抓到」造成重要 L1 漏失
- fallback 是 bounded 且 optional，不取代 typed agents

輸出 artifact：

- `batch_fallbacks.json`

### 3.7 Evidence Grounding Agent

檔案：`long_term/multi_agent_verifier.py`

函式：`ground_candidates(...)`

責任：

- 把 `source_unit_ids` 映射回 idea units
- 再映射回 transcript evidence lines
- 建立 `evidence_quote`
- 計算 purely local `support_score`

現在的支撐分數來源：

- lexical jaccard
- content token coverage
- evidence token coverage
- span inclusion

實作在：`long_term/multi_agent_tools.py` 的 `local_alignment_score(...)`

設計理由：

- 把 acceptance 從「模型說自己很有把握」改成「本地證據真的支持 candidate」

目前限制：

- local alignment 仍是 lexical / span-based heuristic
- 還沒有對 paraphrase 型 evidence 做更強的本地語義檢查

### 3.8 Cross-Type Conflict Resolver

檔案：`long_term/multi_agent_reducer.py`

函式：`resolve_cross_type_conflicts(...)`

責任：

- 處理部分 type pair 的 overlap
- 在 evidence span 重疊且文本高度相似時 merge
- 否則允許同 evidence 的多 type 共存

設計理由：

- ontology overlap 不等於 bug
- resolver 的工作是分辨 redundancy 與合理多重標註

目前限制：

- collision policy 還不是完整 ontology governance
- 目前只覆蓋部分 type pair

### 3.9 Deterministic Verifier

檔案：`long_term/multi_agent_verifier.py`

函式：`verify_l1_candidates(...)`

責任：

- 檢查合法 type
- 檢查空 content
- 檢查 evidence lines 是否存在且在範圍內
- 檢查 `support_score` 是否太低
- 檢查 duplicate

可能 rejection reasons：

- `invalid_type`
- `empty_content`
- `missing_evidence_lines`
- `evidence_out_of_bounds`
- `weak_grounding`
- `duplicate_of:<candidate_id>`

設計理由：

- 在寫回 canonical schema 前加 deterministic gate

目前限制：

- verifier 只驗證 candidate correctness；upstream segmentation / idea-unit 品質由前面的 validator / repair stages 處理

### 3.10 Reducer / Persist

檔案：`long_term/multi_agent_reducer.py`

函式：`reduce_l1_patch(...)`

責任：

- 把 verified candidates 轉成 canonical L1 objects
- 套用共用 importance calibration
- 套用 multi-agent 專用 importance cap，避免 model 自評把普通細節全部推到高分
- 將「研究 / 比較 / 評估 / 確認」這類 follow-up suggestion 從誤判的 `decision` / `method_change` 校正回 `todo`
- 將純描述性結構定義（例如 object schema / memory hierarchy）從誤判的 `decision` / `method_change` / `todo` 校正回 `result`
- 將尚未採用的 proposed method / proposed decision 校正為 `result`，避免把討論中的方案誤當成已落地的流程變更
- 對 goal statement 和低 grounding support 的 candidate 加上 importance cap
- 對同 evidence / 高相似內容做 final dedupe
- 對同 evidence、相鄰 evidence、或同概念鍵的 decision / method_change 中英重複做保守合併
- 合併 tool-calling 候選時保留 `Read` / `Write` 這類具體函式細節
- 計算同一嚴格 viewpoint key 是否在分離 transcript episodes 中反覆出現，並給予有上限的小幅 importance bonus
- 產出 `final_patch.json`
- 產出 `viewpoint_recurrence.json`
- 產出 `final_meeting_node.json`

設計理由：

- 讓 multi-agent 輸出仍符合既有 `tree.json` schema
- 保持與 L2 / L3 summarize 相容
- 將「同一觀點被會議反覆提到」變成可檢查的 importance 訊號，而不是只停留在中介 candidate

Viewpoint recurrence 規則：

- reducer 會分開使用 `concept_keys` 和 `viewpoint_keys`：`concept_keys` 可用於保守去重，`viewpoint_keys` 才能觸發 recurrence importance bonus
- `viewpoint_keys` 比 `concept_keys` 嚴格，例如 `compare_memory_architecture_with_rag`、`long_term_forgetting_decay`；單純同屬 RAG / memory / demo 大主題不會自動視為同一觀點
- evidence lines 排序後，行號間隔大於 10 行才算新的 episode；連續幾行反覆講同一件事只算同一 episode
- 2 個 episodes 給 `+0.02`、3 個 episodes 給 `+0.04`、4 個以上 episodes 給 `+0.06`
- bonus 只小幅調整既有 importance，並受 type cap 限制：`decision` / `method_change` 最高 `0.93`，`result` / `todo` 最高 `0.84`
- `viewpoint_recurrence.json` 會列出 affected objects 的 `base_importance` / `adjusted_importance` / `actual_bonus`，以及已達 type cap 的 `capped_objects` 或被更強 recurrence key 蓋過的 `superseded_by_stronger_viewpoint_count`
- canonical memory object 不新增欄位；recurrence 細節寫在 artifact，方便檢查但不改既有 schema

## 4. Artifact 設計

每次 multi-agent run 都會落一組 research artifacts：

- `run_meta.json`
- `graph_events.jsonl`
- `window_plans.json`
- `segments.json`
- `segment_coverage_validation.json`
- `segment_coarsening.json`
- `continuation_merges.json`
- `extraction_batches.json`
- `idea_units.json`
- `idea_unit_quality_validation.json`
- `raw_candidates.json`
- `batch_fallbacks.json`
- `grounded_candidates.json`
- `conflict_resolution.json`
- `verified_candidates.json`
- `rejected_candidates.json`
- `final_patch.json`
- `viewpoint_recurrence.json`
- `final_meeting_node.json`
- `prompts/`
- `responses/`

這些 artifact 的研究價值在於：

- 可以回看每一層怎麼切
- 可以追 candidate 從哪個 batch 來
- 可以查 grounding 為何接受或拒絕
- 可以定位失敗是在 segmentation、type extraction、grounding、還是 reduction

## 5. 已完成的關鍵設計

目前已經實際落地的設計重點：

1. 明確的多階段責任邊界
2. bounded type extraction，而不是全 transcript typed prompting
3. continuation merge 真正消費 `needs_more_context`
4. grounding acceptance 不再依賴 model self-confidence
5. candidate 保留 `extraction_scope` 與 `segment_ids`
6. segment coverage validator 會補 uncovered transcript lines
7. idea unit quality validator 會修補空白、過胖、重複或越界 unit
8. over-fragmented segments / idea units 會先保留語意邊界，只有超過 validator 上限才壓縮
9. typed L1 agents 每個 batch/type 有 candidate 上限
10. reducer 會做 multi-agent 專用 dedupe 與 importance cap
11. reducer 會把跨 episode 反覆出現的同一觀點轉成小幅、有上限的 importance bonus
12. batch empty-yield 時有 bounded fallback L1 agent
13. focused tests 覆蓋核心行為
14. 與既有 `tree.json` / summarize 流程相容

## 6. 現在還缺的設計

以下是目前距離「完整研究型 multi-agent L1 系統」還缺的關鍵部分。

### 6.1 Ontology Completion

目前 multi-agent loop 只實作四類：

- `decision`
- `todo`
- `method_change`
- `result`

還沒完整納入：

- `open_question`
- `argument`

缺少後果：

- multi-agent L1 還不是 full-schema extraction
- 一部分現有 long-term ontology 仍未被顯式多 agent 化

### 6.2 Repair / Fallback Loop

目前已補上最小 repair / fallback：

- segmentation uncovered lines 會補 fallback segment
- idea units 空白、越界、過胖、重複時會被修補或丟棄
- over-fragmented segments 會被 deterministic coarsening；idea units 會先補 coverage gap，只有超過 validator 上限才 compact
- batch 完全無 candidate 時會跑一次 bounded fallback L1 agent

還未補的是更昂貴的 model retry 類閉環：

- grounding rejection rate 異常時的 upstream retry signal
- segmentation / idea unit repair 後重新要求 LLM 改寫，而不是只做 deterministic fallback

### 6.3 Evaluation Harness

目前有單元測試，但還缺 run-level evaluation metrics。

建議至少補：

- segment coverage rate
- uncovered line ratio
- continuation merge rate
- batch candidate yield
- verifier rejection breakdown
- support score distribution
- cross-type collision rate
- final L1 count stability across reruns
- 與 monolithic baseline 的差異比較

### 6.4 Operational Guardrails

目前 artifacts 很完整，但 operation 資訊還不夠。

建議補：

- per-stage latency
- token / cost usage
- stage-level retry telemetry
- artifact schema version
- partial rerun support

### 6.5 L2 / L3 Multi-Agent 化

目前 multi-agent 真正完成的是 L1 extraction。L2 / L3 仍是舊 summarize pipeline。

這不是 bug，但代表整體 long-term system 還沒有 end-to-end multi-agent 化。

## 7. 目前可對外怎麼描述

比較精確的描述方式：

> 目前已完成 long-term L1 的 explicit multi-agent extraction pipeline，具備 bounded extraction、artifact traceability、segment/idea-unit upstream validation、bounded fallback、local grounding 與 deterministic verification；但 full ontology coverage、model-based repair retry、evaluation harness 與 operational telemetry 尚未補齊。

這個描述比直接說「long-term multi-agent 已完成」更準確。

## 8. 代辦清單

以下代辦依優先度排序。

### Must Have

- [x] 實作 `segment_coverage_validator`
- [x] 實作 `idea_unit_quality_validator`
- [x] 將 validator 結果寫入 artifact
- [x] 為 uncovered / invalid spans 增加 focused tests
- [ ] 建立 stage-level metrics summary

### Should Have

- [ ] 將 `open_question` 接進 multi-agent loop
- [ ] 將 `argument` 接進 multi-agent loop
- [ ] 定義完整 cross-type ontology overlap policy
- [x] 增加 bounded fallback 策略
- [x] 增加 batch-level empty-yield diagnostics
- [ ] 增加 model-based retry 策略

### Nice to Have

- [ ] 加入 per-stage latency / token telemetry
- [ ] 支援 stage rerun / partial rerun
- [ ] 做 L1 monolithic vs multi-agent 的系統性比較報表
- [ ] 規劃 L2 / L3 multi-agent 化路線

## 9. 測試現況

目前 focused tests 已覆蓋三個核心保證：

1. mismatch grounding 不會因為高 confidence 被誤收
2. type agent 只會吃指定 bounded units
3. cross-window continuation merge 真的會形成 batch
4. segment coverage 漏行會補 fallback segment
5. idea unit 過胖會被拆成 bounded chunks
6. fallback L1 agent 仍受 bounded unit IDs 限制
7. over-fragmented segments 會被 coarsen
8. idea-unit validator 會補 coverage gap，並避免過早把不同觀點 compact 在一起
9. typed L1 agent 每個 batch/type 會限制候選數
10. reducer 會 dedupe、校正 type，並校準 multi-agent importance
11. reducer 只會因為分離 episodes 提高 importance，連續行號 evidence 不會灌高分

此外 full suite 目前也應能通過。這表示後段控制邏輯已有基本穩定性，且 upstream representation quality 已有第一版 deterministic validator / repair。

## 10. 建議提交範圍

如果要把這次 multi-agent L1 變更 push 上去，建議先只提交以下檔案：

- `long_term/README.md`
- `long_term/bridge.py`
- `long_term/cli.py`
- `long_term/multi_agent_agents.py`
- `long_term/multi_agent_logger.py`
- `long_term/multi_agent_pipeline.py`
- `long_term/multi_agent_reducer.py`
- `long_term/multi_agent_state.py`
- `long_term/multi_agent_tools.py`
- `long_term/multi_agent_validators.py`
- `long_term/multi_agent_verifier.py`
- `long_term/docs/MULTI_AGENT_L1_ARCHITECTURE.md`
- `tests/test_multi_agent_pipeline.py`

先不要一起提交的檔案：

- `meeting_recording/` 下面的錄音、轉檔、`Zone.Identifier`
- root 下這次不直接相關的額外文件

原因是這些檔案與 multi-agent L1 主修改無直接關聯，混進同一個 commit 會讓 review 與回溯變差。
