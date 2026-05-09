# short_term 短期記憶架構

`short_term` 目前是一個從 `share_mem` 累積快照產生短期記憶 JSON 的更新流程。它讀取 `share_mem/snapshots/*_bridge_*.json`，取出累積樹中最新一場會議的 L1 `memory_objects`，再把這些物件合併到短期 topic unit。輸出包含目前的 canonical 狀態 `short_term/short_term_memory.json`，以及每次更新後的人類可讀快照 `short_term/snapshots/<meeting_id>.json`。

短期記憶的設計重點是「只保留最近仍活躍的議題」。每個 unit 代表一個短期主題，保留標題、摘要、型別、相關 topic、來源 L1 object id、最近更新會議，以及更新歷史。

## 輸入與輸出

輸入：

- `share_mem/snapshots/*_bridge_*.json`：由 `share_mem` 產出的累積 bridge snapshot。檔案內必須有 `meetings[]`。
- 最新會議的 `memory_objects[]`：每個有效物件需要有 `obj_id`，並可包含 `type`、`content`、`evidence`、`related_topics` 等欄位。

輸出：

- `short_term/short_term_memory.json`：目前短期記憶的 canonical JSON 狀態。
- `short_term/snapshots/<meeting_id>.json`：每次實際更新後寫出的短期記憶快照，方便人工檢視與追蹤。
- `--dry-run` 時只會把更新結果印到 stdout，不會寫入上述輸出檔。

## 模組職責

- `schema.py`：定義預設記憶結構、schema version、預設 Gemini model，以及 Gemini merge decision 的 JSON schema。
- `snapshot_loader.py`：載入 bridge snapshot、檢查 `meetings[]`，依 `meeting_date`、`timestamp`、`meeting_id` 排序並選出最新會議。
- `merge.py`：負責候選 unit 選取、Gemini merge prompt、merge decision 解析與驗證、timeout/retry，以及把 `create_new` 或 `merge_existing` 套用到記憶狀態。
- `update_memory.py`：CLI 與主要更新流程。它載入 snapshot 和目前記憶、逐一處理最新會議的 L1 物件、更新 retention 狀態，最後寫出 canonical JSON 與 per-meeting snapshot。
- `retrieval/short_term_context.py`：正式短期記憶查詢介面。它讀取 `short_term_memory.json`，根據 query 與 unit 的 `title`、`summary`、`types`、`related_topics` 做 deterministic ranking，並輸出 app 可直接注入 prompt 的 compact context。
- `io_utils.py`：JSON 讀寫、字串正規化、去重與 UTC timestamp。
- `reset_short_term_memory.sh`：清除短期記憶的 runtime/generated artifacts，例如 `short_term_memory.json`、舊 DB 殘留檔與 snapshots；不會刪除 `meeting_recording/` 底下的來源 transcripts。
- `run_all_short_term_updates.sh`：依版本排序批次處理 `share_mem/snapshots/*_bridge_*.json`，並依 snapshot 內實際選出的 latest meeting 去重，避免同一場會議被重複更新。

## 更新流程

1. 呼叫 `short_term/update_memory.py --snapshot <bridge_snapshot>`。
2. `snapshot_loader.load_snapshot_tree()` 讀取並驗證 snapshot 內含 `meetings[]`。
3. `select_latest_meeting()` 從累積 snapshot 選出最新會議；也就是每個 bridge snapshot 只用其中最新的一場會議更新短期記憶。
4. `load_short_term_memory()` 載入 `short_term/short_term_memory.json`；若不存在則使用空白預設結構。
5. 更新 `meeting_history_ids`，並從最新會議取出有 `obj_id` 的 `memory_objects[]`。
6. 對每個 L1 object 執行 merge：
   - 先用規則找出最多 5 個候選 short-term units。
   - 再交給 Gemini 決定 `merge_existing` 或 `create_new`。
   - 將決策套用到記憶狀態，並記錄 touched unit。
7. 所有 L1 object 處理完後，未被 touched 的 units 會增加 `missed_meeting_count`，達到移除門檻時刪除。
8. 更新 `memory_version`、`last_updated_utc`、`last_updated_meeting_id`、`processed_snapshot_path`。
9. 非 dry-run 時寫出 `short_term/short_term_memory.json` 與 `short_term/snapshots/<meeting_id>.json`。

## 合併邏輯

候選 unit 先由規則產生，避免把全部記憶丟給 LLM。`select_candidate_units()` 會用以下訊號打分：

- 來源 `obj_id` 已在 unit 的 `source_obj_ids` 中。
- L1 object 與 unit 的 `related_topics` Jaccard 相似度。
- L1 object 的 `content`、`evidence`、`related_topics` 與 unit 的 `title`、`summary`、`related_topics` token 相似度。
- `type` 與 unit 既有 `types` 相同時給小幅加分。

Gemini 只會看到新的 L1 object、會議資訊與候選 units。它必須回傳 JSON decision：

- `create_new`：建立新的 `S###` unit，記錄 `created_meeting_id`、`last_updated_meeting_id`、`source_obj_ids` 與 `update_history`。
- `merge_existing`：只能合併到候選 unit id 之一；若回傳未知 `unit_id` 會被拒絕。

來源限制：

- Gemini prompt 明確要求不可發明 source object id。
- 實際寫入 `source_obj_ids` 時只使用目前 L1 object 的 `obj_id`。
- `merge_existing` 只能指向候選清單中的既有 unit；程式會驗證該 `unit_id` 是否存在。

## Retention 規則

每個 unit 都有 `missed_meeting_count`：

- unit 在本次更新被建立或合併時，`missed_meeting_count` 重設為 `0`。
- 本次沒有被任何 L1 object 更新的 unit，`missed_meeting_count` 加 `1`。
- `missed_meeting_count >= 2` 的 unit 會被移除。

因此短期記憶只保留最近兩次處理中仍相關的議題：本次會議有更新的 unit 會留下；上一場還在、但本場沒被更新的 unit 也會暫留一次；連續兩場未被更新就會消失。這就是「只記得最近兩場會議」在目前 JSON update 流程中的實作意義。

## CLI 使用方式

單一 snapshot dry-run：

```bash
uv run short_term/update_memory.py \
  --snapshot share_mem/snapshots/example_bridge_0318.json \
  --dry-run
```

單一 snapshot 實際更新：

```bash
uv run short_term/update_memory.py \
  --snapshot share_mem/snapshots/example_bridge_0318.json
```

批次處理所有 bridge snapshots：

```bash
./run_all_short_term_updates.sh
```

批次腳本會先讀取每個 cumulative snapshot 的實際 latest meeting，再針對每個 meeting 只選一份 snapshot。若同一個 meeting 有多份 snapshot，會優先選檔名 suffix 與實際 latest meeting 相符的檔案，避免同一場會議重複處理造成 `memory_version`、`source_obj_ids` 或 `update_history` 膨脹。

指定 snapshot 目錄或起始會議：

```bash
./run_all_short_term_updates.sh /path/to/share_mem/snapshots
START_FROM=0318 ./run_all_short_term_updates.sh
```

重設短期記憶 runtime 狀態：

```bash
./reset_short_term_memory.sh --dry-run
./reset_short_term_memory.sh --yes
```

常用環境變數：

- `GEMINI_MODEL`：指定 merge decision 使用的 Gemini model；預設為 `gemini-2.5-pro`。
- `SHORT_TERM_MERGE_TIMEOUT_S`：每個 L1 object 呼叫 Gemini 的 timeout 秒數；預設為 `60`。
- `SHORT_TERM_MERGE_RETRIES`：Gemini transient error 的重試次數；預設為 `2`。
- `START_FROM`：批次腳本從指定 meeting id 開始處理。
- `SNAPSHOT_DIR`：批次腳本的預設 snapshot 來源目錄，可被第一個位置參數覆蓋。

## Retrieval

正式 retrieval 入口：

```python
short_term.retrieval.short_term_context.retrieve_short_term_context(
    query,
    api_key,
    retrieval_mode="hybrid",
    top_k=6,
    max_context_chars=4000,
)
```

目前版本是 deterministic lexical ranking，`api_key` 與 `retrieval_mode` 先保留在介面中，方便之後替換成 semantic/hybrid retrieval 而不改 app 呼叫端。

`app/memory_context.py::retrieve_short_term_context_adapter` 已經接到這個 module；router 判定問題需要 short-term 時，會回傳 `S###` unit 的摘要、最近更新會議與 source L1 ids。

## 目前限制

- 目前 retrieval 是 lexical ranking，尚未使用 embedding 或 LLM reranker。
- 目前 canonical 狀態是 JSON，不是 SQLite；reset script 仍會清掉一些舊 DB/runtime 殘留檔。
- 每個 L1 object 的 merge decision 需要 LLM 呼叫，會帶來成本、latency、timeout 與 transient failure 風險。
- `short_term/snapshots/<meeting_id>.json` 是人類可讀的 generated output，主要供檢視與除錯，不應手動當成來源資料維護。
