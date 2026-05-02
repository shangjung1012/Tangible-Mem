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

`context_planner -> segmentation_agent -> continuation_merge -> idea_unit_agent -> bounded l1_decision/todo/method_change/result_agent -> evidence_grounding_agent -> cross_type_conflict_resolver -> verify_l1_candidates -> reduce_l1_patch -> persist_l1`

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
- 沒有 coverage validator 保證 primary window 內每行都被覆蓋
- 沒有 overlap / underspan / overspan 的 deterministic 檢查

### 3.4 Continuation Merge

檔案：`long_term/multi_agent_pipeline.py`

函式：`build_continuation_batches(...)`

責任：

- 消費 `needs_more_context`
- 把相鄰 segments 合成 bounded extraction batch
- 為下游 type agents 定義真正的 extraction scope

目前 merge 條件：

- 相鄰
- 至少一側 `needs_more_context`
- topic 相似，或左側已明確要求延續

輸出 artifact：

- `continuation_merges.json`
- `extraction_batches.json`

設計理由：

- 把跨窗補救明確化，而不是讓 segmentation 直接輸出跨窗 segment
- 保留固定窗口的穩定性，同時補償邊界語意截斷

目前限制：

- 只做 merge policy，還不是 repair policy
- 如果 segmentation 階段就漏掉某些行，continuation merge 無法補救

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

- 沒有 deterministic quality validator
- 沒有檢查 unit 是否過胖、過碎、過度重疊
- `completeness` / `uncertainty_note` 目前只記錄，不影響 acceptance

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

設計理由：

- 真正把 type agent 從 monolithic transcript reader 變成 bounded extractor
- 讓 candidate 可以回溯到具體 batch 與 segment

目前限制：

- `open_question` / `argument` 尚未接進 multi-agent loop
- 還沒有 batch-level rejection / retry policy

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

- verifier 只驗證 candidate correctness，不驗證 upstream segmentation / idea-unit 品質

### 3.10 Reducer / Persist

檔案：`long_term/multi_agent_reducer.py`

函式：`reduce_l1_patch(...)`

責任：

- 把 verified candidates 轉成 canonical L1 objects
- 套用共用 importance calibration
- 產出 `final_patch.json`
- 產出 `final_meeting_node.json`

設計理由：

- 讓 multi-agent 輸出仍符合既有 `tree.json` schema
- 保持與 L2 / L3 summarize 相容

## 4. Artifact 設計

每次 multi-agent run 都會落一組 research artifacts：

- `run_meta.json`
- `graph_events.jsonl`
- `window_plans.json`
- `segments.json`
- `continuation_merges.json`
- `extraction_batches.json`
- `idea_units.json`
- `raw_candidates.json`
- `grounded_candidates.json`
- `conflict_resolution.json`
- `verified_candidates.json`
- `rejected_candidates.json`
- `final_patch.json`
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
6. focused tests 覆蓋核心行為
7. 與既有 `tree.json` / summarize 流程相容

## 6. 現在還缺的設計

以下是目前距離「完整研究型 multi-agent L1 系統」還缺的關鍵部分。

### 6.1 Segment Coverage Validator

目前沒有檢查 primary window 內每一行是否至少被一個 segment 覆蓋。

缺少後果：

- 邊界內容可能兩邊 window 都不收
- continuation merge 無法補救已經漏掉的行

建議補上：

- 每個 primary window 的 covered lines
- uncovered line ratio
- gap spans artifact
- 高缺口時的 warning 或 fallback

### 6.2 Idea Unit Quality Validator

目前沒有檢查：

- unit 是否過胖
- unit 是否過碎
- unit 是否完整落在 segment 內
- units 是否高度重疊

缺少後果：

- downstream type extraction 容易被過大或過碎的 unit 影響
- verifier 很難分辨是 candidate 問題還是 representation 問題

### 6.3 Ontology Completion

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

### 6.4 Repair / Fallback Loop

目前 continuation 是 merge policy，不是 repair policy。

還缺：

- segmentation coverage 不足時重切
- idea units 過少或過胖時重抽
- batch 完全無 candidate 時的 fallback extraction
- grounding rejection rate 異常時的 upstream retry signal

### 6.5 Evaluation Harness

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

### 6.6 Operational Guardrails

目前 artifacts 很完整，但 operation 資訊還不夠。

建議補：

- per-stage latency
- token / cost usage
- stage-level retry telemetry
- artifact schema version
- partial rerun support

### 6.7 L2 / L3 Multi-Agent 化

目前 multi-agent 真正完成的是 L1 extraction。L2 / L3 仍是舊 summarize pipeline。

這不是 bug，但代表整體 long-term system 還沒有 end-to-end multi-agent 化。

## 7. 目前可對外怎麼描述

比較精確的描述方式：

> 目前已完成 long-term L1 的 explicit multi-agent extraction pipeline，具備 bounded extraction、artifact traceability、local grounding 與 deterministic verification；但 segmentation / idea-unit upstream validation、ontology completeness、repair loop 與 evaluation harness 尚未補齊。

這個描述比直接說「long-term multi-agent 已完成」更準確。

## 8. 代辦清單

以下代辦依優先度排序。

### Must Have

- [ ] 實作 `segment_coverage_validator`
- [ ] 實作 `idea_unit_quality_validator`
- [ ] 將 validator 結果寫入 artifact
- [ ] 為 uncovered / invalid spans 增加 focused tests
- [ ] 建立 stage-level metrics summary

### Should Have

- [ ] 將 `open_question` 接進 multi-agent loop
- [ ] 將 `argument` 接進 multi-agent loop
- [ ] 定義完整 cross-type ontology overlap policy
- [ ] 增加 fallback / retry 策略
- [ ] 增加 batch-level empty-yield diagnostics

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

此外 full suite 目前也應能通過。這表示後段控制邏輯已有基本穩定性，但 upstream representation quality 仍缺 explicit validator。

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
- `long_term/multi_agent_verifier.py`
- `long_term/docs/MULTI_AGENT_L1_ARCHITECTURE.md`
- `tests/test_multi_agent_pipeline.py`

先不要一起提交的檔案：

- `meeting_recording/` 下面的錄音、轉檔、`Zone.Identifier`
- root 下這次不直接相關的額外文件

原因是這些檔案與 multi-agent L1 主修改無直接關聯，混進同一個 commit 會讓 review 與回溯變差。