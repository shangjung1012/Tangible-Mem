# Short-Term Memory

這個資料夾負責「一次輸入一次會議逐字稿」，先把逐字稿轉成 SQLite，再更新短期記憶。

目前以 SQLite 為唯一 canonical 儲存（`short_term/short_term_memory.db`）。JSON 只由 DB 匯出給人檢視，程式流程不再讀 JSON 作為 memory source。
逐字稿會匯入 `short_term/transcripts.db`。更新流程使用 LangGraph local-first orchestration，讓多個受限 Gemini sub-agent 產生候選，再由 deterministic verifier / reducer / normalizer 控制寫入。

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

- `update_memory.py`: CLI 入口與 LangGraph orchestration（Vertex Gemini sub-agents + SQLite）
- `langgraph_update.py`: LangGraph workflow（window planning、segmentation、extraction、verify、reduce、persist）
- `agents.py`: Context Planner / Segment / Summary / Action / Method / Experiment / Focus sub-agent prompt、JSON schema 與 read/write tool loop
- `memory_tools.py`: sub-agent read-only memory tool 與 staging candidate write tool
- `staging_store.py`: staging candidates SQLite table；agent write tool 只寫這裡，不直接寫 official memory
- `verifier.py`: deterministic candidate validation（ID、enum、confidence、section ownership、duplicate create；evidence 主要作為 warning/debug）
- `reducer.py`: verified candidates → partial memory patch
- `research_logger.py`: 每次更新的 prompt / raw response / parsed JSON / graph event / report log
- `schema.py`: 短期記憶 schema、狀態常數、`response_json_schema`
- `genai_client.py`: Google Gen AI client 設定，預設使用 Vertex AI + ADC
- `llm_client.py`: legacy tool-calling helper（目前 CLI 不再使用）
- `normalizer.py`: 記憶資料正規化與 merge
- `io_utils.py`: `.env`、JSON 讀寫與安全輸出
- `sqlite_store.py`: official memory SQLite schema、讀寫與 snapshot
- `transcript_store.py`: 逐字稿 SQLite 匯入、overview、行範圍讀取

## 更新流程

1. 讀取單一會議逐字稿（例如 `meeting_recording/transcript/49.txt`）
2. 將逐字稿逐行匯入 transcript SQLite（預設 `short_term/transcripts.db`）
3. 只從 SQLite 讀取目前記憶；DB 為空時使用預設空記憶，不再從 JSON bootstrap
4. LangGraph 依序執行：
   - `ContextPlannerAgent` 規劃下一段 forward window 與 lookback/lookahead
   - `SegmentAgent` 判斷 idea units；若需要更多上下文，回到 planner 補讀
   - Summary / Action / Method / Experiment / Focus sub-agent 透過 tool calling 讀 official memory，並把候選寫入 staging table
   - `verifier.py` deterministic 拒絕非法 ID/enum、低 confidence、越權 section、未知 update target、疑似 duplicate create 的候選
   - `reducer.py` 合併通過候選為 partial patch
5. partial patch 交給本地 `normalizer.py`，維持既有邏輯（含最近 3 次會議裁切），再寫入 SQLite
6. 更新完成後，系統會重新從 SQLite 載入最新記憶，並在 DB 內記錄 snapshot
7. 每次更新都會從 SQLite 匯出 `short_term/snapshots/` 的 JSON snapshot，並在 `short_term/db_snapshots/` 產生 SQLite DB snapshot
8. 每次更新會建立 `short_term/research_logs/<run_id>/`，保存 prompts、raw responses、parsed JSON、graph events、候選與 final report，方便研究與調 prompt

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
  --snapshot-dir short_term/snapshots \
  --db-snapshot-dir short_term/db_snapshots \
  --model gemini-2.5-pro \
  --chunk-size 80 \
  --max-lookback-lines 20 \
  --max-lookahead-lines 40 \
  --checkpoint-db short_term/langgraph_checkpoints.db \
  --research-log-dir short_term/research_logs \
  --log-level debug
```

`--memory-json`、`--mirror-json`、`--no-bootstrap-json` 已保留為相容參數，但都是 deprecated no-op；JSON 不再作為程式資料來源。

`--max-tool-rounds` 已保留為相容參數，但不控制 LangGraph sub-agent tool loop，傳入時只會印出 deprecated warning。

研究 log 主要檔案：

- `graph_events.jsonl`: 每個 LangGraph node 的 start/end、耗時、摘要
- `prompts/*.prompt.txt`: 完整 prompt（預設保留）
- `responses/*.raw.txt` / `*.parsed.json`: LLM 原始與解析後輸出
- `tool_calls/*.json`: sub-agent read/write tool calls、參數摘要、結果摘要與錯誤
- `candidates/raw_candidates.json`: 所有 sub-agent 候選
- `candidates/verified_candidates.json`: 通過 deterministic verifier 的候選
- `candidates/rejected_candidates.json`: 被拒絕的候選與原因
- `final_patch.json` / `final_memory.json` / `report.md`: 最終寫入前後結果與人工可讀報告

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
