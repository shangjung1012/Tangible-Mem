# Long-term Memory 技術文件

## 一、設計目標

長期記憶（Long-term Memory, LTM）的核心問題是：

> **「我們當初為什麼這樣做？」**

長期記憶以**時間軸為絕對主軸**，保留每一個研究決策的完整因果鏈，讓系統能夠追溯「演算法改了 3 次的完整過程」。

設計上參考 TiMem 論文的核心概念：
- **時間記憶樹 (Temporal Memory Tree, TMT)**：三層樹狀結構，高層節點的時間區間必須完全涵蓋子節點（時間包含約束 Temporal Containment）
- **複雜度感知的智慧分流 (Complexity-Aware Recall)**：先判斷問題複雜度，再決定要挖哪一層記憶

---

## 二、三層樹狀結構

```
L3: Project Profile（研究計畫輪廓）
       │  時間區間涵蓋所有 Phase
       ├── L2: Phase P-2026-01（月度 / Sprint 摘要）
       │         │  時間區間涵蓋本月所有 Meeting
       │         ├── L1: Meeting Bmr001
       │         ├── L1: Meeting Bmr002
       │         └── L1: Meeting Bmr003
       │
       └── L2: Phase P-2026-02
                 ├── L1: Meeting Bmr010
                 └── ...
```

### L1：Meeting Level（會議層）

每次會議對應一個節點，節點內有多個 **記憶物件 (Memory Object)**。

每個 Memory Object 的結構：

| 欄位 | 型態 | 說明 |
|---|---|---|
| `obj_id` | `str` | 唯一 ID，格式 `L1-{meeting_id}-{seq:03d}` |
| `type` | `enum` | `decision` \| `todo` \| `method_change` \| `result` \| `open_question` \| `argument` |
| `content` | `str` | 記憶內容（繁體中文）|
| `importance` | `float` | 重要性 0.0～1.0 |
| `evidence` | `str` | 從逐字稿引用的支持句 |
| `related_topics` | `list[str]` | 主題關鍵字，用於因果鏈追蹤 |
| `related_obj_ids` | `list[str]` | 預留：與其他 Memory Object 的關聯 |

**六種 type 含義：**
- `decision`：會議中做出的決策或結論（影響後續研究方向）
- `todo`：被指派的待辦事項
- `method_change`：方法論、演算法、流程的變更（因果鏈的最重要元素）
- `result`：實驗結果、發現、觀察報告
- `open_question`：尚未解決、需要後續追蹤的研究問題
- `argument`：決策背後的論點、推理與取捨

**importance 評分標準：**
- 0.8～1.0：影響整個研究方向的重大決策
- 0.5～0.7：重要的技術決策或中等優先的待辦
- 0.3～0.4：一般性討論結論
- 0.1～0.2：瑣碎行政事項

### L2：Phase Level（階段層）

一個月或一個 Sprint 的彙整摘要。由 L1 的記憶物件聚合而來。

| 欄位 | 說明 |
|---|---|
| `phase_id` | 如 `P-007` |
| `time_range` | `{start, end}` 日期字串 |
| `summary` | 本階段主軸，1-2 句、60 字內 |
| `changes` | 本期淨方法變化，最多 5 條；每條含 `status` 與 `method` |
| `open_to_next` | 留給下一階段的真正懸案，最多 2 條 |
| `child_meeting_ids` | 本階段包含的 meeting ID 列表（內部索引用，不進 prompt） |

`changes[].status` 只會是：
- `adopted`：本期確立
- `abandoned`：本期棄用
- `evolved`：持續演進中

### L3：Project Profile（計畫層）

整個研究計畫的長期輪廓，從所有 L2 摘要提煉而來。

| 欄位 | 說明 |
|---|---|
| `project_id` | 研究計畫識別碼 |
| `time_range` | 整個計畫的起訖時間 |
| `core_goal` | 專案核心目標，1-2 句、60 字內 |
| `current_phase` | 目前所處的大階段，1 句、30 字內 |
| `established_methods` | 跨多個 phase 都穩定成立的核心做法，最多 5 條 |
| `long_term_open_questions` | 橫跨多個 phase 的長期懸案，最多 3 條 |
| `child_phase_ids` | 所有 Phase ID 列表（內部索引用，不進 prompt） |

---

## 三、資料儲存結構（`tree.json`）

```json
{
  "tree_version": 29,
  "last_updated_utc": "2026-04-06T13:20:50Z",
  "project_profile": { ... },          // L3
  "phases": [ ... ],                   // L2 陣列
  "meetings": [                        // L1 陣列
    {
      "meeting_id": "Bmr001",
      "timestamp": "2026-04-06T13:08:17Z",
      "source_file": "/path/to/Bmr001.mrt",
      "phase_id": "P-001",             // 歸屬哪個 Phase（run summarize 後填入）
      "memory_objects": [
        {
          "obj_id": "L1-Bmr001-001",
          "type": "result",
          "content": "麥克風增益偏低。",
          "importance": 0.3,
          "evidence": "Although the gain is pretty low.",
          "related_topics": ["麥克風", "增益", "錄音品質"],
          "related_obj_ids": []
        },
        ...
      ]
    }
  ]
}
```

`tree_version` 每次寫入都 +1，用來追蹤版本。

---

## 四、程式碼檔案說明

```
long_term/
├── schema.py              定義所有資料結構常數與 Gemini Structured Output Schema
├── io_utils.py            環境變數、JSON 讀寫工具
├── bridge.py              Bridge — 逐字稿 → L1 記憶物件（CLI + Library）
├── build_tree.py          批次 Bridge — 處理 Bmr*.mrt，自動更新 L2/L3（CLI）
├── rebuild_snapshots.py   從現有 L1 重跑所有 L2/L3 快照（CLI）
├── summarize.py           Summarize — L1→L2 / L2→L3（CLI）
├── recall_planner.py      Recall Planner — 查詢複雜度分類（Library）
├── recall.py              Recall — 記憶樹搜尋 + Recall Gate（Library）
├── incremental_store.py   Incremental bridge 的 SQLite 工作日誌
├── gemini_incremental_extractor.py  Incremental Gemini tool-calling orchestrator
├── tree.json              主記憶樹資料（唯一持久化儲存）
└── snapshots/             版本化快照目錄
    ├── L2/                每場 meeting 加入後的 phase 快照
    └── L3/                每場 meeting 加入後的 project profile 快照
```

### `schema.py`
純常數模組，定義：
- `MEMORY_OBJ_TYPES`：`{"decision", "todo", "method_change", "result", "open_question", "argument"}`
- `DEFAULT_TREE`：空樹的初始結構
- `BRIDGE_RESPONSE_SCHEMA`：Bridge LLM 的 JSON Schema（Gemini Structured Output 格式）
- `PHASE_SUMMARY_SCHEMA`：Phase 摘要 LLM 的 JSON Schema
- `PROFILE_UPDATE_SCHEMA`：Project Profile LLM 的 JSON Schema
- `RECALL_PLAN_SCHEMA`：Recall Planner 的 JSON Schema
- `RECALL_GATE_SCHEMA`：Recall Gate 的 JSON Schema

### `io_utils.py`
提供：
- `load_api_keys()` — 從 `.env` 讀取 `GOOGLE_API_KEY` / `GEMINI_API_KEY` 系列，若啟用 Vertex AI 則允許無 key 走 ADC
- `load_env()` — 向後相容：回傳第一把 API key；Vertex ADC 模式下會回傳空字串
- `load_tree(path)` — 讀取 `tree.json`，檔案不存在時回傳空樹
- `save_json(path, data)` — 序列化寫入（自動建立父目錄）
- `utc_now_iso()` — 回傳 UTC 時間字串（如 `2026-04-06T13:20:50Z`）

### `bridge.py`
**功能：從單一逐字稿擷取 L1 記憶物件，寫入 tree.json**

核心函式：

| 函式 | 說明 |
|---|---|
| `build_bridge_prompt()` | 組裝 Gemini prompt，注入逐字稿與已知 topic 關鍵字 |
| `call_gemini_bridge()` | 呼叫 Gemini，要求回傳符合 `BRIDGE_RESPONSE_SCHEMA` 的 JSON |
| `collect_existing_topics()` | 從樹中收集所有已知 topic 關鍵字，傳給 LLM 作為參考（避免同一概念出現不同詞彙） |
| `normalize_memory_objects()` | 驗證 LLM 輸出：型態合法性、importance 範圍鉗制、補齊 obj_id |
| `insert_meeting_into_tree()` | 將會議節點插入樹，若已存在則更新，並按 meeting_id 排序 |

CLI 使用：
```bash
uv run long_term/bridge.py --transcript ./ICSI_original_transcripts/transcripts/Bmr001.mrt
```

### `build_tree.py`
**功能：批次處理 Bmr*.mrt，每場 meeting 後自動更新 L2/L3**

關鍵設計：
- **每處理完一個 meeting 就立刻存檔**（crash-safe）
- `--resume`：讀取現有 `tree.json`，跳過已有的 meeting ID，只跑缺少的
- `--dry-run`：只列出檔案和字數，不呼叫 LLM（估算 API 用量用）
- `--max-chars 15000`：截斷逐字稿超過 15000 字的部分，避免超出 token 限制
- `--meetings`：指定要處理的 meeting 範圍（支援連續範圍與個別 ID）
- `--phase-size 4`：每個 L2 Phase 包含幾場 meeting（預設 4）
- `--no-auto-summarize`：只做 L1，跳過自動 L2/L3 更新

CLI 使用：
```bash
# 從頭跑所有 meeting（含自動 L2/L3）
uv run build_tree.py

# 斷點續跑（只補缺少的）
uv run build_tree.py --resume

# 只看會處理哪些檔案（不呼叫 LLM）
uv run build_tree.py --dry-run

# 只跑 Bmr001 到 Bmr010（連續範圍）
uv run build_tree.py --meetings Bmr001:Bmr010

# 只跑指定幾場
uv run build_tree.py --meetings Bmr001 Bmr003 Bmr007

# 混合用法：Bmr001~005 加上 Bmr009
uv run build_tree.py --meetings Bmr001:Bmr005 Bmr009

# 確認範圍選到哪些（不呼叫 LLM）
uv run build_tree.py --meetings Bmr001:Bmr008 --dry-run

# 只做 L1，不自動跑 L2/L3
uv run build_tree.py --no-auto-summarize
```

### `rebuild_snapshots.py`
**功能：從現有 L1 資料出發，重跑所有 L2/L3 累積快照**

當 L1 已經建立完成（如用 `build_tree.py --no-auto-summarize` 批次跑完），用此腳本補生成所有快照，無需重打 L1 的 API。

快照命名規則：
- `snapshots/L2/P-001__Bmr001.json` — Phase 1，只含第 1 場
- `snapshots/L2/P-001__Bmr005.json` — Phase 1，含第 1~4 場（完整）
- `snapshots/L2/P-002__Bmr006.json` — Phase 2，只含第 5 場
- `snapshots/L3/Bmr001.json` — 看過 1 場後的 project profile
- `snapshots/L3/Bmr031.json` — 看過全部 29 場後的 project profile

CLI 使用：
```bash
# 確認執行計畫（不呼叫 LLM）
uv run rebuild_snapshots.py --dry-run

# 正式跑（共 58 次 API：29 次 L2 + 29 次 L3）
uv run rebuild_snapshots.py

# 調整 Phase 大小
uv run rebuild_snapshots.py --phase-size 6
```

### `summarize.py`
**功能：L1 → L2 Phase 摘要，L2 → L3 Project Profile**

`phase` 子命令（L1 → L2）：
1. 從 `tree.json` 撈出指定 meeting 的所有 L1 記憶物件
2. 展開成純文字清單（含 type、importance、content）
3. 呼叫 Gemini，要求輸出 `PHASE_SUMMARY_SCHEMA` 格式的摘要
4. 產生 `summary`、`changes`、`open_to_next`
5. 更新 `tree.json` 中的 `phases` 陣列，並將相關 meeting 的 `phase_id` 填入

`profile` 子命令（L2 → L3）：
1. 讀取所有 L2 phases
2. 呼叫 Gemini，要求輸出 `PROFILE_UPDATE_SCHEMA` 格式的計畫輪廓
3. 產生 `core_goal`、`current_phase`、`established_methods`、`long_term_open_questions`
4. 自動計算整個計畫的時間區間（min start / max end）

CLI 使用：
```bash
# 建立 L2 Phase 摘要
uv run long_term/summarize.py phase \
  --phase-id P-007 \
  --time-start Bmr027 \
  --time-end Bmr030 \
  --meetings Bmr027 Bmr028 Bmr029 Bmr030

# 更新 L3 計畫輪廓
uv run long_term/summarize.py profile
```

### `recall_planner.py`
**功能：判斷問題的複雜度，決定要搜尋哪些記憶層**

輸出結構：
```json
{
  "complexity": "complex",
  "reasoning": "問題涉及時間跨度較長的演進史",
  "search_targets": ["long_term_l1", "long_term_l2", "long_term_l3"],
  "keywords": ["演算法", "架構", "演進"],
  "time_range_hint": "過去半年"
}
```

| complexity | 路由 | 典型問題 |
|---|---|---|
| `simple` | `short_term` | 「上次會議決定怎麼處理缺失值？」 |
| `complex` | `long_term_l1` + `l2` + `l3` | 「半年來模型架構的演進史為何？」 |

### `recall.py`
**功能：依照 recall plan 搜尋記憶，回傳結構化結果**

核心搜尋函式：

| 函式 | 說明 |
|---|---|
| `search_l1_semantic()` | 對所有 L1 記憶物件做 semantic + recency + importance 檢索 |
| `get_l3_profile()` | 直接回傳 L3 project profile（若有資料） |
| `expand_parent_chain()` | 由 L1 命中結果向上補齊所屬 L2 與 singleton L3 |
| `recall_gate()` | 當 candidates > 3 時，呼叫 LLM 過濾雜訊，只保留真正相關的 |
| `recall()` | 主編排器，依 plan 調用上述函式，組合最終結果 |
| `format_recall_for_prompt()` | 將 recall 結果格式化成可注入 system prompt 的文字 |

**目前的檢索策略：**
- 長期記憶 L1：使用 embedding 做 semantic retrieval，再混合 recency 與 importance 分數
- 長期記憶 L2 / L3：由 L1 命中結果往上展開 parent chain
- 短期記憶：仍使用 `_keyword_score()` 做簡單 keyword matching

---

## 五、完整流程

### Phase 1：建立記憶樹（一次性 or 增量）

```
會議逐字稿 (.mrt / .txt)
       │
       ▼
[build_tree.py / bridge.py]
  1. 解析 MRT XML → 純文字逐字稿
  2. 呼叫 Gemini bridge prompt
  3. 取得 memory_objects (decision/todo/method_change/result)
  4. 正規化：驗證 type、鉗制 importance、補齊 obj_id
  5. 插入 tree.json 的 meetings 陣列
  6. 立刻存檔（crash-safe）
       │
       ▼
     tree.json (L1 版)
       │
       ▼
[summarize.py phase]（每月 / 每個 Sprint 執行一次）
  1. 讀取指定 meeting 的 L1 記憶物件
  2. 呼叫 Gemini phase summary prompt
  3. 產生 summary、changes、open_to_next
  4. 寫入 tree.json 的 phases 陣列
  5. 將相關 meeting 的 phase_id 填入
       │
       ▼
     tree.json (L1 + L2 版)
       │
       ▼
[summarize.py profile]（定期執行）
  1. 從所有 L2 phases 提煉
  2. 產生 core_goal、current_phase、established_methods、long_term_open_questions
  3. 寫入 tree.json 的 project_profile
       │
       ▼
     tree.json (L1 + L2 + L3 完整版)
```

### Phase 2：對話時的記憶檢索

```
使用者提問
       │
       ▼
[recall_planner.plan_recall()]
  Gemini 判斷 complexity = simple / complex
  輸出 search_targets + keywords + time_range_hint
       │
       ├── simple ──► search short_term → STM 的 meeting_window + action_items
       │
       └── complex ──► search long_term_l1 / l2 / l3
                        (keyword matching，回傳候選集)
                          │
                          ▼
                    [recall_gate()]（candidates > 3 時觸發）
                    呼叫 Gemini 過濾雜訊
                          │
                          ▼
                    按時間排序（因果鏈保留）
       │
       ▼
[format_recall_for_prompt()]
  格式化成文字，可直接注入 system prompt
       │
       ▼
Persona Agent (Gemini) 帶著記憶背景回答
```

### 因果鏈追蹤範例

問：「我們為什麼放棄使用對數能量分析？」

```
recall_planner → complex
keywords: ["對數能量", "能量分析", "放棄"]

search_l1(obj_types=["method_change"]) →
  semantic + recency + importance 排序後的候選：
    [Bmr009] 建議調整時間窗大小，從固定 200ms 改為變動窗
    [Bmr009] 決定從直接能量而非對數能量開始分析
    [Bmr010] 補充直接能量方案的後續觀察

recall_gate() →
  只保留真正與「對數能量 → 直接能量」這條路徑相關的物件

format_recall_for_prompt() →
  === 長期記憶檢索結果（按時間排序）===
  [Bmr009] (method_change) 決定從直接能量而非對數能量開始...
  [Bmr009] (result) 對數能量會壓縮距離，難以觀察變化
```

---

## 六、呼叫 LLM 的次數

| 操作 | LLM 呼叫次數 |
|---|---|
| `bridge.py` 一筆會議 | 1 次 |
| `build_tree.py` 29 場 Bmr | 29 次 |
| `summarize.py phase` 一個 Phase | 1 次 |
| `summarize.py profile` | 1 次 |
| `recall_planner.plan_recall()` 一次查詢 | 1 次 |
| `recall_gate()`（candidates > 3 時）| 1 次 |
| **每次對話查詢合計** | **2 次**（planner + gate） |

---

## 七、擴充方向（目前尚未實作）

1. **時間範圍提示落地**：`plan_recall()` 已能產生 `time_range_hint`，但 `recall()` 目前尚未真正用它做篩選或加權。

2. **跨會議因果連結 `related_obj_ids`**：目前欄位預留但未填，未來 bridge 可在同主題 memory object 之間建立顯式關聯邊，讓圖搜尋成為可能。

3. **STM ↔ LTM 自動橋接**：目前 `short_term/current_memory.json` 與 `long_term/tree.json` 是獨立的，理想上會議結束後應自動觸發 bridge，並在 recall 時自動傳入 STM。

4. **L2 自動觸發**：目前需要手動執行 `summarize.py phase`，可以設定為「每月 1 日自動匯聚」的排程任務。
