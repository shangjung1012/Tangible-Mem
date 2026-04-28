# Short-Term Memory

這個資料夾負責「一次輸入一次會議逐字稿」，先把逐字稿轉成 SQLite，再更新短期記憶。

目前以 SQLite 為主要儲存（`short_term/short_term_memory.db`），避免每次覆寫大型 JSON 的風險。
逐字稿會匯入 `short_term/transcripts.db`，讓 Gemini（透過 Vertex AI / Google Gen AI SDK）使用 tool calling 自行決定要讀哪幾行，而不是一次吃完整逐字稿。

## 記憶結構

固定欄位如下：

- `memory_version`
- `last_updated_utc`
- `last_updated_meeting_id`
- `meeting_history_ids`（從舊到新的完整會議 id 序列，由本地維護）
- `meeting_window`（只保留最近 3 次）
- `action_items`（只保留最近 3 次會議範圍內建立或更新過的項目，含 proposer、created_time_hint、dependencies、status、history）
- `method_changes`
- `experiment_todos`
- `next_meeting_focus`

## 檔案拆分

- `update_memory.py`: CLI 入口與流程 orchestration（Gemini tool calling + SQLite）
- `schema.py`: 短期記憶 schema、狀態常數、`response_json_schema`
- `genai_client.py`: Google Gen AI client 設定，預設使用 Vertex AI + ADC
- `llm_client.py`: Gemini prompt、tool calling（read/write memory）與 structured fallback
- `normalizer.py`: 記憶資料正規化與 merge
- `io_utils.py`: `.env`、JSON 讀寫與安全輸出
- `sqlite_store.py`: SQLite schema、讀寫、snapshot 與 JSON bootstrap
- `transcript_store.py`: 逐字稿 SQLite 匯入、overview、行範圍讀取

## 更新流程

1. 讀取單一會議逐字稿（例如 `meeting_recording/transcript/49.txt`）
2. 將逐字稿逐行匯入 transcript SQLite（預設 `short_term/transcripts.db`）
3. 讀取 SQLite 目前記憶（若 DB 為空，會從 `current_memory.json` bootstrap 一次）
4. 呼叫 Gemini tool calling：
   - `read_transcript_overview()` 取得逐字稿行數與頭尾預覽
   - `read_transcript_lines(start_line, end_line, limit)` 分段讀逐字稿
   - `read_short_term_memory(section, offset, limit)` 分段讀目前記憶
   - `write_short_term_memory(updated_memory)` 對確認的小批更新逐步寫入
5. 寫入工具會套用本地 normalizer，維持既有邏輯（含最近 3 次會議裁切），並直接落到 SQLite
6. 更新完成後，系統會重新從 SQLite 載入最新記憶，並在 DB 內記錄 snapshot
7. 每次更新都會從 SQLite 匯出 `short_term/snapshots/` 的 JSON snapshot，並在 `short_term/db_snapshots/` 產生 SQLite DB snapshot（另可選擇輸出 JSON mirror）

## 使用方式

```bash
uv run short_term/update_memory.py --transcript ./ICSI_original_transcripts/transcripts/Bmr001.mrt
```

可選參數：

```bash
uv run short_term/update_memory.py \
  --transcript meeting_recording/transcript/49.txt \
  --db short_term/short_term_memory.db \
  --transcript-db short_term/transcripts.db \
  --memory-json short_term/current_memory.json \
  --mirror-json \
  --snapshot-dir short_term/snapshots \
  --db-snapshot-dir short_term/db_snapshots \
  --model gemini-2.5-pro
```

## 測試 Retrieval QA

可以直接對短期記憶提問（預設讀 SQLite，DB 空時可由 JSON bootstrap），流程會先從結構化記憶中找出最相關片段，再交給 Gemini 生成回答。

目前支援三種檢索模式：

- `lexical`: 關鍵字/字詞重疊
- `semantic`: embedding 語意相似度
- `hybrid`: 結合 lexical 與 semantic，通常最穩

單次提問：

```bash
uv run short_term/retrieve_qa.py \
  --db short_term/short_term_memory.db \
  --question "目前有哪些高優先的 action items？" \
  --show-context
```

指定 semantic retrieval：

```bash
uv run short_term/retrieve_qa.py \
  --db short_term/short_term_memory.db \
  --question "最近大家卡住的研究工作是什麼？" \
  --retrieval-mode semantic \
  --show-context
```

指定 hybrid retrieval：

```bash
uv run short_term/retrieve_qa.py \
  --db short_term/short_term_memory.db \
  --question "哪一些事情是 Adam 在負責而且還沒完成？" \
  --retrieval-mode hybrid \
  --show-context
```

互動模式：

```bash
uv run short_term/retrieve_qa.py --show-context
```

只測 retrieval、不呼叫 LLM：

```bash
uv run short_term/retrieve_qa.py \
  --question "IBM 數據傳輸現在到哪了？" \
  --show-context \
  --no-llm
```

`--show-context` 會在最終回答前，先印出這次檢索到的 memory chunks，方便你檢查：

- 抓到了哪些 chunk
- 每個 chunk 的 `chunk_id` / 類型 / 內容
- retrieval score，以及 lexical / semantic 分數

這個參數很適合拿來 debug 檢索效果，或比較不同 `--retrieval-mode` 的差異。

embedding 會快取在 `short_term/.embedding_cache.json`，避免每次都重算 chunk embeddings。

## Vertex AI 設定

short-term 預設走 Vertex AI，不再需要 `GEMINI_API_KEY`。本機需先完成 ADC：

```bash
gcloud auth application-default login
gcloud config set project virtual-mentor-494016
```

可在 `.env` 明確設定：

```bash
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=virtual-mentor-494016
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=/Users/shangjung/.config/gcloud/application_default_credentials.json
```

若 `GOOGLE_CLOUD_PROJECT` 沒設定，程式會嘗試讀取目前的 `gcloud config get-value project`。若 `GOOGLE_APPLICATION_CREDENTIALS` 沒設定，程式會預設讀取 `~/.config/gcloud/application_default_credentials.json`。如需暫時切回 Gemini Developer API，設定 `GOOGLE_GENAI_USE_VERTEXAI=false` 並提供 `GEMINI_API_KEY` 或 `GOOGLE_API_KEY`。
