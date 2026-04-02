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
uv run short_term/update_memory.py --transcript meeting_recording/transcript/49.txt
```

可選參數：

```bash
uv run short_term/update_memory.py ^
  --transcript meeting_recording/transcript/49.txt ^
  --memory short_term/current_memory.json ^
  --snapshot-dir short_term/snapshots ^
  --model gemini-2.5-flash
```
