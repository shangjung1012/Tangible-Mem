# Long-term Memory（時間記憶樹）

`long_term/` 是 Virtual Mentor 的跨會議記憶模組。它會把單場會議整理成 L1 記憶，再逐步彙整成 L2 phase 與 L3 project profile，供 recall 在回答問題時補上長期背景。

## 先看這裡

- 指令入口：`uv run long_term/cli.py --help`
- 主資料：`long_term/tree.json`
- 歷史快照：`long_term/snapshots/`
- 系統設計：`long_term/ARCHITECTURE.md`

最常用的幾個指令：

```bash
uv run long_term/cli.py bridge --transcript ICSI_original_transcripts/transcripts/Bmr001.mrt
uv run long_term/cli.py build-tree --resume --phase-size 4
uv run long_term/cli.py rebuild-snapshots --dry-run
uv run long_term/cli.py smoke-todo
```

## 記憶層級

| 層級 | 內容 | 產生方式 |
| --- | --- | --- |
| `L1` | 單場會議的 `decision` / `todo` / `method_change` / `result` / `open_question` / `argument` | `bridge` |
| `L2` | 一個 phase 的 `summary` / `changes` / `open_to_next` | `summarize phase` |
| `L3` | 專案整體的 `core_goal` / `current_phase` / `established_methods` / `long_term_open_questions` | `summarize profile` |

Recall 目前走 semantic retrieval：先用 embedding 對 L1 做搜尋，再把 `semantic + recency + importance` 合成分數，必要時經過 Recall Gate，最後沿 parent chain 補回對應的 L2 / L3。

## 資料夾怎麼看

| 路徑 | 用途 |
| --- | --- |
| `cli.py` | long-term 專用 CLI 入口 |
| `bridge.py` | 從單場逐字稿擷取 L1 記憶 |
| `summarize.py` | `L1 -> L2` 與 `L2 -> L3` 的彙整 |
| `recall.py` / `recall_planner.py` | recall 規劃、檢索、格式化 prompt |
| `build_tree.py` / `rebuild_snapshots.py` | 批次建樹與重建 snapshots |
| `scripts/` | smoke test / 評估腳本 |
| `tree.json` | 長期記憶主資料 |
| `snapshots/` | L2 / L3 snapshots 與評估輸出 |
| `docs/` | 設計稿與重構筆記 |
| `archive/` | 舊備份與 redesign preview，平常可忽略 |

## 環境變數

在專案根目錄的 `.env` 至少放：

```env
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-2.5-flash
GEMINI_EMBED_MODEL=models/gemini-embedding-001
```

`test` 指令另外會讀這些變數：

- `LONG_TERM_TEST_MODE=all|bridge|recall`
- `LONG_TERM_TEST_RESUME=1`
- `LONG_TERM_TEST_MEETINGS="Bmr001,Bmr002"`
- `LONG_TERM_TEST_LIMIT=1`
- `LONG_TERM_BRIDGE_MAX_RETRIES=8`
- `LONG_TERM_BRIDGE_INTERVAL_S=1`
- `LONG_TERM_STOP_ON_ERROR=1`
- `LONG_TERM_REPORT_PATH=long_term/bridge_report.json`

## 常用流程

### 1. 單場 Bridge

```bash
uv run long_term/cli.py bridge \
  --transcript ICSI_original_transcripts/transcripts/Bmr001.mrt
```

常見補充參數：

```bash
uv run long_term/cli.py bridge \
  --transcript ICSI_original_transcripts/transcripts/Bmr001.mrt \
  --tree long_term/tree.json \
  --snapshot-dir long_term/snapshots \
  --model gemini-2.5-flash \
  --timestamp 2000-06-14T17:00:00Z \
  --meeting-date 2000-06-14
```

### 2. 手動建立 L2 / L3

```bash
uv run long_term/cli.py summarize phase \
  --phase-id P-007 \
  --time-start Bmr027 \
  --time-end Bmr030 \
  --meetings Bmr027 Bmr028 Bmr029 Bmr030
```

```bash
uv run long_term/cli.py summarize profile
```

### 3. 批次建立整棵樹

```bash
uv run long_term/cli.py build-tree --resume --phase-size 4
```

補充：

- `--dry-run` 只看會處理哪些會議
- `--no-auto-summarize` 只建 L1，不自動補 L2 / L3
- `--meetings Bmr001:Bmr005 Bmr009` 可只跑指定範圍
- `build_tree.py` 目前內部 bridge model 固定是 `gemini-2.5-flash`

### 4. 用既有 `tree.json` 重建 snapshots

```bash
uv run long_term/cli.py rebuild-snapshots --dry-run
uv run long_term/cli.py rebuild-snapshots --phase-size 4
```

這個流程不會重打 L1 bridge，只會根據現有 `tree.json` 重跑 L2 / L3。

### 5. 驗證與評估

端對端測試：

```bash
export LONG_TERM_TEST_MODE=all
export LONG_TERM_TEST_RESUME=1
export LONG_TERM_REPORT_PATH=long_term/bridge_report.json
UV_CACHE_DIR=/tmp/uv-cache uv run long_term/cli.py test
```

只檢查 todo recall：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run long_term/cli.py smoke-todo
```

評估 prompt injection：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run long_term/cli.py eval-injection \
  --question "錄音增益問題的處理過程是什麼？" \
  --show-only
```

## 需要更細節時

- 系統設計與資料流：`long_term/ARCHITECTURE.md`
- retrieve redesign 筆記：`long_term/docs/RETRIEVE_IMPLEMENTATION_PLAN.md`
- L2 / L3 redesign 筆記：`long_term/docs/L2_L3_REDESIGN_PLAN.md`

如果只是要開始跑 long-term，優先記住 `uv run long_term/cli.py --help` 就夠了。
