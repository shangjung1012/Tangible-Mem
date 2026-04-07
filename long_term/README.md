# Long-term Memory（時間記憶樹）

長期記憶模組以 TiMem 概念為核心，重點是保留「跨會議的時間演進」。

## 核心概念

### 三層記憶結構

| 層級 | 名稱 | 說明 |
|---|---|---|
| **L1** | Meeting Level | 每場會議的記憶物件（`decision` / `todo` / `method_change` / `result` / `open_question` / `argument`） |
| **L2** | Phase Level | 多場會議匯總後的階段摘要 |
| **L3** | Project Profile | 專案長期方法論與演進輪廓 |

### 檢索流程（目前版本）

長期記憶採 **semantic retrieval**：

1. Query embedding
2. 對所有 L1 物件做 cosine similarity
3. `semantic + recency + importance` 合成分數
4. 取 top-k 候選
5. 複雜問題時用 Recall Gate 過濾
6. 由 L1 結果向上展開 parent chain（補 L2 / L3）
7. 組裝 prompt（L3 → L2 → L1 → short-term）

短期記憶檢索仍是 keyword-based；只有在 `recall()` 傳入 `short_term_memory` 時才會啟用。

## 主要檔案

| 檔案 | 用途 |
|---|---|
| `schema.py` | 記憶樹 schema 與 Structured Output schema |
| `io_utils.py` | `.env` 載入、JSON 讀寫 |
| `bridge.py` | 從單份逐字稿擷取 L1 記憶物件（含 API busy retry） |
| `summarize.py` | `phase`（L1→L2）與 `profile`（L2→L3） |
| `embedder.py` | embedding 計算、cosine similarity、`.embedding_cache.json` |
| `recall_planner.py` | 問題複雜度規劃（含 API busy retry + heuristic fallback） |
| `recall.py` | semantic retrieval、Recall Gate、parent chain expansion |
| `build_tree.py` | 批次處理多份 Bmr 逐字稿並可自動更新 L2/L3 |
| `test_long_term.py` | 端到端測試腳本 |
| `tree.json` | 長期記憶主資料 |
| `snapshots/` | 歷史快照 |

## 環境變數

在專案根目錄 `.env` 設定：

```env
GEMINI_API_KEY=your_api_key
# optional
GEMINI_MODEL=gemini-2.5-flash
# optional（建議在部分帳號上明確設定）
GEMINI_EMBED_MODEL=models/gemini-embedding-001
```

測試腳本可另外用：

- `LONG_TERM_TEST_LIMIT`：限制 `test_long_term.py` 處理幾場會議（例如先設 `1` 做 smoke test）
- `LONG_TERM_BRIDGE_MAX_RETRIES`：每場 bridge 呼叫最大重試次數（預設 `6`）
- `LONG_TERM_BRIDGE_INTERVAL_S`：每場 bridge 間隔秒數（預設 `0`）
- `LONG_TERM_STOP_ON_ERROR=1`：遇到單場失敗時立刻中止（預設不中止，繼續處理下一場）
- `LONG_TERM_TEST_RESUME=1`：沿用既有 `tree.json`，跳過已存在的 meeting（預設每次從空樹開始）
- `LONG_TERM_TEST_MODE`：`all` / `bridge` / `recall`（預設 `all`）
- `LONG_TERM_TEST_MEETINGS`：指定要處理的會議（逗號或空白分隔，例如 `Bmr001,Bmr002`）
- `LONG_TERM_REPORT_PATH`：Bridge 報表輸出位置（預設 `long_term/bridge_report.json`）

## 使用方式

### 1. Bridge：擷取 L1 記憶物件

```bash
uv run long_term/bridge.py \
  --transcript ICSI_original_transcripts/transcripts/Bmr001.mrt
```

可選參數：

```bash
uv run long_term/bridge.py \
  --transcript ICSI_original_transcripts/transcripts/Bmr001.mrt \
  --tree long_term/tree.json \
  --snapshot-dir long_term/snapshots \
  --model gemini-2.5-flash \
  --timestamp 2000-06-14T17:00:00Z \
  --meeting-date 2000-06-14
```

說明：

- `timestamp`：系統寫入時間（build time）
- `meeting_date`：實際會議日期（recency 計分優先使用）

### 2. Summarize：建立 L2 與 L3

建立 L2 phase：

```bash
uv run long_term/summarize.py phase \
  --phase-id P-2026-03 \
  --time-start 2026-03-01 \
  --time-end 2026-03-31 \
  --meetings Bmr005 Bmr006 Bmr007
```

更新 L3 profile：

```bash
uv run long_term/summarize.py profile
```

### 3. Recall：程式內呼叫

```python
from pathlib import Path

from long_term.embedder import EmbedCache
from long_term.io_utils import load_env, load_tree
from long_term.recall import format_recall_for_prompt, recall
from long_term.recall_planner import plan_recall

api_key = load_env()
tree = load_tree(Path("long_term/tree.json"))
cache = EmbedCache()

query = "錄音增益問題的處理過程是什麼？"
plan = plan_recall(query, api_key)
result = recall(
    query=query,
    plan=plan,
    tree=tree,
    api_key=api_key,
    embed_cache=cache,
)

context = format_recall_for_prompt(result)
cache.save()
```

回傳重點欄位：

- `long_term_l1`：語意檢索到的 L1 記憶物件（含 `score / s_sem / s_recency / s_importance`）
- `long_term_l2`：由 parent chain 展開的 phase
- `project_profile`：L3
- `long_term_results`：`long_term_l1` 的向下相容 alias

### 4. 批次建立樹（可選）

```bash
uv run long_term/build_tree.py --resume --phase-size 4
```

`build_tree.py` 目前內部固定使用 `gemini-2.5-flash`。

### 5. 端到端測試

```bash
export GEMINI_MODEL="gemini-2.5-flash"
export GEMINI_EMBED_MODEL="models/gemini-embedding-001"
export LONG_TERM_TEST_LIMIT=1
export LONG_TERM_BRIDGE_MAX_RETRIES=8
export LONG_TERM_BRIDGE_INTERVAL_S=1
export LONG_TERM_TEST_RESUME=1
export LONG_TERM_TEST_MODE=all
export LONG_TERM_REPORT_PATH=long_term/bridge_report.json
UV_CACHE_DIR=/tmp/uv-cache uv run long_term/test_long_term.py
```

兩段式建議跑法（高負載時較穩）：

```bash
# 先只跑 Bridge，可重複執行直到 meeting 補齊
export LONG_TERM_TEST_MODE=bridge
export LONG_TERM_TEST_RESUME=1
unset LONG_TERM_TEST_LIMIT
export LONG_TERM_REPORT_PATH=long_term/bridge_report.json
UV_CACHE_DIR=/tmp/uv-cache uv run long_term/test_long_term.py

# 再單獨跑 Recall（不再打 Bridge API）
export LONG_TERM_TEST_MODE=recall
UV_CACHE_DIR=/tmp/uv-cache uv run long_term/test_long_term.py
```

若只想補某幾場：

```bash
export LONG_TERM_TEST_MODE=bridge
export LONG_TERM_TEST_MEETINGS="Bmr001,Bmr002"
export LONG_TERM_TEST_RESUME=1
UV_CACHE_DIR=/tmp/uv-cache uv run long_term/test_long_term.py
```

Bridge 跑完後會輸出報表（預設 `long_term/bridge_report.json`），其中 `pending_after_run_ids` 是仍未成功寫入 `tree.json` 的 meeting 列表。

Todo recall 快速檢查：

```bash
PYTHONPATH=long_term UV_CACHE_DIR=/tmp/uv-cache uv run python long_term/scripts/smoke_todo_recall.py
```

此腳本會驗證：

- planner 是否對「待辦」問題自動加上 `type_filter=["todo"]`
- recall 結果是否只回傳 `todo` 類型

Prompt injection A/B 測試：

```bash
# 只看 inject 了什麼（不打最終回答）
PYTHONPATH=long_term UV_CACHE_DIR=/tmp/uv-cache uv run python long_term/scripts/eval_prompt_injection.py \
  --question "錄音增益問題的處理過程是什麼？" \
  --show-only

# 同題比較：不注入 vs 注入 recall context
PYTHONPATH=long_term UV_CACHE_DIR=/tmp/uv-cache uv run python long_term/scripts/eval_prompt_injection.py \
  --question "錄音增益問題的處理過程是什麼？" \
  --show-injected-context \
  --save
```

## 可靠性與注意事項

- `bridge / planner / recall_gate / embedder` 皆有 API busy retry（503/429 等）
- `recall_planner` 若 API 暫時不可用，會退回 heuristic plan，避免整段中斷
- `recall_gate` 若失敗，會保留 raw candidates 繼續流程
- `.embedding_cache.json` 僅為加速工具，可刪除後重建
- `meeting_date` 缺失時，recency 會 fallback 到 `timestamp`；若仍不可解析，採中性分數 `0.5`
