# Short-Term Memory

這個資料夾負責「一次輸入一次會議逐字稿」，把逐字稿匯入 SQLite，再透過 LangGraph pipeline 更新短期記憶。

目前以 SQLite 為唯一 canonical memory store，程式預設路徑是 `short_term/short_term_memory.db`。JSON snapshot 只由 DB 匯出給人檢視，程式更新流程不再讀 JSON 作為 memory source。

逐字稿會匯入 transcript SQLite，程式預設路徑是 `short_term/storage/transcripts.db`。更新流程使用 LangGraph local-first orchestration：Gemini sub-agent 只負責產生候選；正式寫入前一律經過 deterministic verifier、reducer、normalizer 控制。

## 架構總覽

```text
transcript file
  -> update_memory.py
  -> transcript_store.py
  -> transcripts SQLite
  -> langgraph_update.py
       -> context planner
       -> transcript window reader
       -> segment agent
       -> parallel extraction agents
            -> meeting summary
            -> action items
            -> method changes
            -> experiment todos
            -> next meeting focus
       -> staging candidates
       -> verifier
       -> reducer
       -> normalizer
  -> short_term_memory SQLite
  -> JSON snapshot / DB snapshot / research logs
```

主要分層：

- CLI entrypoint：`update_memory.py` 負責參數、逐字稿匯入、讀取目前 memory、呼叫 LangGraph、最後輸出 snapshot。
- Workflow orchestration：`workflow/langgraph_update.py` 定義完整 LangGraph node 與 edge。
- Agents：`agents/` 內有 context planner、segment、meeting summary、action item、method change、experiment todo、next focus agent。
- Core deterministic logic：`core/verifier.py`、`core/reducer.py`、`core/normalizer.py` 決定候選是否可接受、如何合併、如何維持 schema 與最近三次會議窗口。
- Storage：`storage/sqlite_store.py` 是 official memory SQLite；`storage/transcript_store.py` 是逐字稿 SQLite；`storage/staging_store.py` 是 agent 候選暫存表。
- Retrieval：`retrieval/short_term_context.py` 和 `retrieve_qa.py` 將 structured memory 切成 chunks，支援 lexical、semantic、hybrid 檢索。
- Runtime logging：`runtime/research_logger.py` 保存 prompts、responses、candidates、final patch、final memory 和 report。

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

ID 與狀態約定：

- action item 使用 `A###`，狀態為 `open|in_progress|completed|cancelled`。
- method change 使用 `M###`，狀態為 `active|reverted|superseded`。
- experiment todo 使用 `E###`，狀態為 `open|in_progress|completed|blocked`。
- priority 使用 `high|medium|low`。

## 檔案拆分

- `update_memory.py`: CLI 入口與 LangGraph orchestration（Vertex Gemini sub-agents + SQLite）
- `workflow/langgraph_update.py`: LangGraph workflow（window planning、segmentation、extraction、verify、reduce、persist）；context 擴窗被迫停止後會重設回合計數，避免下一個 forward window 繼承舊狀態
- `agents/`: Context Planner / Segment / Summary / Action / Method / Experiment / Focus sub-agent prompt 與 JSON schema
- `storage/memory_tools.py`: sub-agent read-only memory tool 與 staging candidate write tool；read tool 只接受被允許的精確 section 名稱，對明顯誤把 `section=<payload>` 放入 section 的情況會轉成合法 section 並回傳 warning，其他非法 section 直接拒絕
- `storage/staging_store.py`: staging candidates SQLite table；agent write tool 只寫這裡，不直接寫 official memory
- `core/verifier.py`: deterministic candidate validation（ID、enum、confidence、section ownership、duplicate create；evidence 主要作為 warning/debug）
- `core/reducer.py`: verified candidates -> partial memory patch
- `runtime/research_logger.py`: 每次更新的 prompt / raw response / parsed JSON / graph event / report log
- `core/schema.py`: 短期記憶 schema、狀態常數、`response_json_schema`
- `runtime/genai_client.py`: Google Gen AI client 設定，預設使用 Vertex AI + ADC
- `llm_client.py`: legacy tool-calling helper（目前 CLI 不再使用）
- `core/normalizer.py`: 記憶資料正規化與 merge
- `storage/io_utils.py`: `.env`、JSON 讀寫與安全輸出
- `storage/sqlite_store.py`: official memory SQLite schema、讀寫與 snapshot
- `storage/transcript_store.py`: 逐字稿 SQLite 匯入、overview、行範圍讀取

## 整體更新 Pipeline

1. 讀取單一會議逐字稿（例如 `meeting_recording/transcript/49.txt`）
2. 將逐字稿逐行匯入 transcript SQLite（預設 `short_term/storage/transcripts.db`）
3. 只從 SQLite 讀取目前記憶；DB 為空時使用預設空記憶，不再從 JSON bootstrap
4. 建立 research log run，清掉同一個 run 的 staging candidates
5. `ContextPlannerAgent` 規劃下一段 forward window，以及可用的 lookback/lookahead
6. 從 transcript SQLite 讀取 planner 指定的 line range
7. `SegmentAgent` 將該 window 切成 idea units；如果需要更多上下文，會回到 planner 補讀，最多重試有限次。若已覆蓋可用逐字稿、planner 重複同一 range、或達到 context round 上限，pipeline 會停止該 window 的擴張並記錄 `unresolved_context`，同時重設 context round，避免影響後續 window
8. 進入 extraction fan-out，同一個 window 內會同時送出五個 section agent：
   - `meeting_summary_agent`
   - `action_item_agent`
   - `method_change_agent`
   - `experiment_todo_agent`
   - `next_focus_agent`
9. LangGraph 會等五個 extraction branch 都完成後，才進入 `collect_window_candidates`。也就是同一個 window 內是平行送出，但會等待所有分支回來再收集候選。
10. `collect_window_candidates` 合併 agent parsed JSON 與 staging table 內的候選；如果 transcript 還沒處理完，回到 planner 處理下一個 window
11. 全部 window 處理完後，`core/verifier.py` deterministic 拒絕非法 ID/enum、低 confidence、越權 section、未知 update target、疑似 duplicate create 的候選
12. `core/reducer.py` 將 verified candidates 合併為 partial memory patch
13. `core/normalizer.py` 將 patch merge 回 previous memory，遞增 `memory_version`，更新 `last_updated_utc` / `last_updated_meeting_id`，維護 `meeting_history_ids`，並裁切 `meeting_window` 到最近 3 次
14. 非 dry-run 時，將 final memory 寫回 official memory SQLite
15. CLI 重新從 SQLite 載入 persisted memory，寫入 DB 內的 `memory_snapshots`，並輸出 JSON snapshot 與 DB file snapshot
16. 每次更新會建立 `short_term/research_logs/<run_id>/`，保存 prompts、raw responses、parsed JSON、graph events、候選、final patch、final memory 與 final report

簡化 graph：

```text
load_inputs
  -> plan_next_window
  -> read_window
  -> segment_window
       -> more_context? plan_next_window
       -> start_extraction
            -> extract_meeting_summary
            -> extract_action_items
            -> extract_method_changes
            -> extract_experiment_todos
            -> extract_next_focus
          -> collect_window_candidates
               -> next_window? plan_next_window
               -> verify_candidates
  -> reduce_patch
  -> normalize_and_persist
  -> final_report
```

## 使用方式

```bash
uv run short_term/update_memory.py --transcript ./ICSI_original_transcripts/transcripts/Bmr001.mrt
```

可選參數：

```bash
uv run short_term/update_memory.py \
  --transcript meeting_recording/transcript/49.txt \
  --db short_term/short_term_memory.db \
  --transcript-db short_term/storage/transcripts.db \
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

研究 log 判讀約定：

- extraction node 的 `summary.raw_candidates` 是該 section agent 在當前 window 產生的候選數，不是全域累積候選數。
- `raw_candidates=` 顯示在一般進度列時可能代表進入該 node 前的累積狀態；以 node END 的 `summary` 判斷該 agent 本次實際產量。
- `retry` event 代表受控重試，需同時檢查後續 node 是否成功完成；只有 `ERROR`、`Traceback`、`LLM agent failed`、tool result `ok=false`、或 verifier/reducer/normalizer 失敗才代表流程失敗。
- `tool_calls/*.json` 的 `args_summary` 會截斷過長參數，避免 malformed tool call 把大段候選 JSON 寫進 log 摘要。

## 測試 Retrieval QA

可以直接對短期記憶提問。Retrieval 預設讀 SQLite；如果 DB 空且有 JSON fallback 設定，舊 helper 仍保留 bootstrap fallback。主要更新流程本身不使用 JSON bootstrap。

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
