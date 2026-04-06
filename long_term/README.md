# Long-term Memory（時間記憶樹）

長期記憶模組，以「時間軸與演進」為主軸，基於 TiMem 的時間記憶樹 (Temporal Memory Tree) 設計。

## 三層結構

| 層級 | 名稱 | 說明 |
|------|------|------|
| **L1** | Meeting Level | 每次會議擷取多個記憶物件 (`decision` / `todo` / `method_change` / `result`) |
| **L2** | Phase / Monthly Level | 月度或衝刺期的彙整摘要，由 L1 匯聚而來 |
| **L3** | Project Profile | 研究計畫的長期輪廓，記錄最終確立的方法論與核心價值觀 |

時間包含約束 (Temporal Containment)：高層節點的時間區間必須完全涵蓋子節點。

## 檔案結構

| 檔案 | 用途 |
|------|------|
| `schema.py` | 記憶樹 schema、Gemini Structured Output JSON Schema |
| `io_utils.py` | 環境變數、JSON 讀寫 |
| `bridge.py` | **CLI** — 從逐字稿擷取 L1 記憶物件 |
| `summarize.py` | **CLI** — L1→L2 階段摘要、L2→L3 計畫輪廓 |
| `recall_planner.py` | **Library** — 查詢複雜度分類與路由 |
| `recall.py` | **Library** — 時間軸記憶檢索 + 過濾閘門 (Recall Gate) |
| `tree.json` | 主記憶樹資料 |
| `snapshots/` | 版本化快照 |

## 使用方式

### 1. Bridge：擷取 L1 記憶物件

從一份會議逐字稿擷取 memory objects 並寫入 `tree.json`：

```bash
uv run long_term/bridge.py --transcript ./ICSI_original_transcripts/transcripts/Bmr001.mrt
```

可選參數：

```bash
uv run long_term/bridge.py \
  --transcript ./ICSI_original_transcripts/transcripts/Bmr001.mrt \
  --tree long_term/tree.json \
  --snapshot-dir long_term/snapshots \
  --model gemini-2.5-flash \
  --timestamp 2000-06-14T17:00:00Z
```

`--dry-run` 只列印結果不寫檔。

### 2. Summarize：建立 L2 階段摘要

將指定的 L1 會議匯聚成一個階段性摘要：

```bash
uv run long_term/summarize.py phase \
  --phase-id P-2026-03 \
  --time-start 2026-03-01 \
  --time-end 2026-03-31 \
  --meetings Bmr005 Bmr006 Bmr007
```

### 3. Summarize：更新 L3 計畫輪廓

根據所有 L2 摘要更新研究計畫的長期輪廓：

```bash
uv run long_term/summarize.py profile
```

### 4. Recall：檢索記憶（程式庫呼叫）

```python
from pathlib import Path
from long_term.recall_planner import plan_recall
from long_term.recall import recall, format_recall_for_prompt
from long_term.io_utils import load_tree, load_env

api_key = load_env()
tree = load_tree(Path("long_term/tree.json"))

plan = plan_recall("我們為什麼放棄使用 A 演算法？", api_key)
result = recall("我們為什麼放棄使用 A 演算法？", plan, tree, api_key)
context = format_recall_for_prompt(result)
```

## 更新流程

```
會議結束
  │
  ▼
bridge.py ──► L1 memory objects 寫入 tree.json
  │
  ▼ （每月 / 每個 Sprint）
summarize.py phase ──► L2 階段摘要
  │
  ▼ （定期）
summarize.py profile ──► L3 計畫輪廓
  │
  ▼ （對話時）
recall_planner ──► 判斷複雜度
  │
  ├─ simple  ──► 短期記憶 (BM25)
  └─ complex ──► 長期時間軸 + Recall Gate ──► 注入 prompt
```

## 檢索機制：複雜度感知的智慧分流 (Complexity-Aware Recall)

| 問題類型 | 路由 | 範例 |
|----------|------|------|
| 簡單/執行型 | `short_term` | 「上次會議決定怎麼處理缺失值？」 |
| 複雜/演進型 | `long_term_l1` + `l2` + `l3` → Recall Gate | 「我們這半年模型架構的演進史為何？」 |

### 因果關係保留

如果演算法改了 3 次（產生 3 個 `method_change`），它們會被嚴格按照時間先後排列在時間軸上。`recall.trace_method_changes()` 可沿時間軸調出完整的方法變更證據鏈。
