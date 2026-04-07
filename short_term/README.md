# Short-Term Memory

這個資料夾負責「一次輸入一次會議逐字稿」，並更新短期記憶 JSON。

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

- `update_memory.py`: CLI 入口與流程 orchestration
- `schema.py`: 短期記憶 schema、狀態常數、`response_json_schema`
- `llm_client.py`: Gemini prompt 組裝與 Structured Output（`response_json_schema`）
- `normalizer.py`: 記憶資料正規化與 merge
- `io_utils.py`: `.env`、JSON 讀寫與安全輸出

## 更新流程

1. 讀取 `current_memory.json`
2. 讀取單一會議逐字稿（例如 `meeting_recording/transcript/49.txt`）
3. 呼叫 Gemini 回傳同 schema 的更新記憶
4. 本地維護 `meeting_history_ids`，再依最後三個 meeting id 裁切 `meeting_window`
5. 正規化欄位與狀態
6. 覆寫 `current_memory.json`，並存一份 snapshot 到 `short_term/snapshots/`

## 使用方式

```bash
uv run short_term/update_memory.py --transcript ./ICSI_original_transcripts/transcripts/Bmr001.mrt
```

可選參數：

```bash
uv run short_term/update_memory.py \
  --transcript meeting_recording/transcript/49.txt \
  --memory short_term/current_memory.json \
  --snapshot-dir short_term/snapshots \
  --model gemini-2.5-flash
```

## 測試 Retrieval QA

可以直接對 `current_memory.json` 提問，流程會先從結構化記憶中找出最相關片段，再交給 Gemini 生成回答。

目前支援三種檢索模式：

- `lexical`: 關鍵字/字詞重疊
- `semantic`: embedding 語意相似度
- `hybrid`: 結合 lexical 與 semantic，通常最穩

單次提問：

```bash
uv run short_term/retrieve_qa.py \
  --question "目前有哪些高優先的 action items？" \
  --show-context
```

指定 semantic retrieval：

```bash
uv run short_term/retrieve_qa.py \
  --question "最近大家卡住的研究工作是什麼？" \
  --retrieval-mode semantic \
  --show-context
```

指定 hybrid retrieval：

```bash
uv run short_term/retrieve_qa.py \
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
