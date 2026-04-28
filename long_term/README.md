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
# optional: 要輪流使用多把 key 時，改用這行
GEMINI_API_KEYS=key_1,key_2,key_3
# optional: 也可改用 GEMINI_API_KEY_1 / 2 / 3 寫法
GEMINI_MODEL=gemini-2.5-flash
GEMINI_EMBED_MODEL=models/gemini-embedding-001
```

## 常用流程

### 1. 單場 Bridge

預設是既有 full-transcript 模式：一次把整份逐字稿送給 Gemini，輸出 L1 記憶物件後寫回 `tree.json`。

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

也可以改用 incremental Gemini function-calling 模式。這個模式會先把逐字稿切成 SQLite 工作表中的逐行資料，讓 Gemini 透過 `read_transcript` 逐段讀取、更新 issue table、建立 raw L1 candidates；接著在寫入正式 L1 前先做一層輕量 candidate review，最後仍回到既有 normalizer 與 `tree.json` 輸出流程。

```bash
uv run long_term/cli.py bridge \
  --transcript meeting_recording/transcript/grace/16.txt \
  --mode incremental \
  --incremental-db long_term/incremental_bridge.db \
  --chunk-size 40
```

補充：

- `--mode full` 是預設值，保留原本 full-transcript bridge 行為。
- `--mode incremental` 需要 `.env` 中的 `GEMINI_API_KEY`；如果有 `GEMINI_API_KEYS=key_1,key_2,key_3`，每次 Gemini model call 會自動輪替使用，預設模型同樣是 `gemini-2.5-flash`。
- incremental 會把進度印到 stderr，例如目前 round、掃到第幾行、issues / raw L1 數量；`--max-tool-rounds 0` 代表依逐字稿長度自動估算上限。長會議會定期從 SQLite 工作狀態重建 Gemini context，避免 input token 歷史持續膨脹。
- `--incremental-db` 是工作日誌，不是 canonical long-term store；正式輸出仍是 `long_term/tree.json` 和 snapshots。
- incremental 的 raw L1 candidate 不是直接進 `tree.json`：會先做一層 deterministic review，包含近似重複候選合併、同 issue checklist fragment 合併、缺少 evidence 的 speculative object 降權或丟棄、以及 linked issue 語意對齊的小幅加減分。這一層只作用在 incremental working objects，不改 final L1 schema。
- `update_issue` 會優先記錄 `forward_scan` 的代表性 evidence 行，而不是把長段落的每一行都塞進 `issue_mentions`；`create_l1_object` 會優先使用 `update_issue` 回傳的 exact `issue_id`，若模型只傳 `issue_key` 也會在儲存時解析成 canonical issue。
- `importance` 會經過共用校準：L1 物件依 evidence / related topics / 高影響語意微調；incremental issues 會先用 `issue_key` / 相似 title-summary 合併同一議題，再用 `episode_count`（相隔超過 15 行才算再次出現）設定最低合理分數，避免連續幾行 evidence 灌高重要性。若 raw L1 object 連到高 importance issue，會在進入 normalizer 前得到最多 `+0.08` 的小幅 bonus；final `tree.json` 的 L1 schema 不變。

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

本地單元測試，不打 API：

```bash
uv run python -m unittest discover -s tests
```

打 API 的 smoke check：

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
